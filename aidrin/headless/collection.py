"""Shared collection execution for CLI, Python, MCP and web adapters."""

import math
import threading

from aidrin.file_handling.collection import (
    CollectionTable,
    SOURCE_COLUMNS,
    make_collection_table,
    normalize_members,
    using_collection_table,
)


_metric_lock = threading.RLock()


def collection_metrics():
    """Discover metrics whose registry contract permits collection inputs."""
    from aidrin.headless.api import METRIC_REGISTRY

    return {name: meta for name, meta in METRIC_REGISTRY.items() if meta.get("collection_modes")}


def _requests(metrics, mode):
    available = collection_metrics()
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("metrics must be a non-empty list of metric requests")
    requests = []
    for request in metrics:
        if not isinstance(request, dict) or set(request) - {"name", "parameters", "source_columns"}:
            raise ValueError("Each metric request accepts name, parameters and source_columns")
        name = request.get("name")
        name = name.replace("-", "_") if isinstance(name, str) else ""
        if name not in available or mode not in available[name]["collection_modes"]:
            raise ValueError(f"Metric does not support {mode} collections: {name}")
        parameters = request.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("Metric parameters must be an object")
        # Input and output policy belong to the collection executor; do not let
        # nested parameters replace the selected input or write image files.
        if set(parameters).intersection({
            "file_path", "file_type", "file_name", "loader", "data_loader", "selected_keys",
            "save_images", "image_dir", "session_id", "strip_visualizations", "_include_visualization",
        }):
            raise ValueError("Metric parameters cannot override collection inputs or output policy")
        columns = request.get("source_columns", [])
        if not isinstance(columns, list) or any(column not in SOURCE_COLUMNS for column in columns) or len(set(columns)) != len(columns):
            raise ValueError(f"source_columns must be a distinct list chosen from {SOURCE_COLUMNS}")
        if set(columns).difference(available[name].get("collection_source_columns", ())):
            raise ValueError(f"Metric does not support collection source columns: {name}")
        requests.append((name, parameters, columns))
    if len({request[0] for request in requests}) != len(requests):
        raise ValueError("Metric names must be unique within a collection assessment")
    return requests


def _json_scores(value):
    """Keep feature names and encode undefined scores as JSON null."""
    if isinstance(value, dict):
        return {str(key): _json_scores(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_scores(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _assess(table, requests):
    from aidrin.headless.api import run_metric

    metrics, errors = {}, {}
    for name, parameters, source_columns in requests:
        try:
            # AIDRIN runners can generate Matplotlib figures even when their
            # output is later stripped. Serialize collection metric calls.
            with _metric_lock, using_collection_table(table, source_columns) as file_info:
                result = run_metric(
                    name, file_info[0], file_type=file_info[2], file_name=file_info[1],
                    save_images=False, _include_visualization=False, **parameters,
                )
            if isinstance(result, dict) and (result.get("Error") or result.get("error")):
                errors[name] = str(result.get("Error") or result.get("error"))
            else:
                if isinstance(result, dict):
                    # Charts are top-level fields. Score dictionaries use arbitrary
                    # dataset column names, including words such as "plot".
                    result = {key: value for key, value in result.items()
                              if not (isinstance(key, str) and isinstance(value, str) and key.lower().endswith(" visualization"))}
                metrics[name] = _json_scores(result)
        except Exception as exc:
            errors[name] = str(exc)
    status = "partial" if metrics and errors else "error" if errors else "ok"
    return {"sources": table.sources, "status": status, "metrics": metrics, "errors": errors}


def run_collection_metrics(files, metrics, mode="independent"):
    """Assess an explicit ordered selection with registered tabular metrics.

    Independent mode isolates each member, including load failures. Stacked
    mode requires every member to load with the same columns and dtypes; any
    load/schema failure raises before metrics run. Metric failures are explicit
    per-dataset errors. All execution is sequential and in memory. Source
    columns are opt-in for each metric, never silently added to measurements.
    """
    if mode not in {"independent", "stacked"}:
        raise ValueError("mode must be independent or stacked")
    members = normalize_members(files)
    requests = _requests(metrics, mode)
    selection = [{"id": member.id, "name": member.display_name} for member in members]
    datasets = []
    if mode == "stacked":
        frames = [member.load() for member in members]
        datasets.append(_assess(make_collection_table(members, frames), requests))
    else:
        for member in members:
            try:
                frame = member.load()
                table = CollectionTable(frame, [{
                    "id": member.id, "name": member.display_name, "start_row": 0, "row_count": len(frame),
                }])
                datasets.append(_assess(table, requests))
            except Exception as exc:
                datasets.append({"sources": [{"id": member.id, "name": member.display_name}],
                                 "status": "error", "metrics": {}, "errors": {"input": str(exc)}})
    return {
        "format": "aidrin.collection-assessment", "version": 1, "mode": mode,
        "selection": selection, "datasets": datasets,
        "summary": {"selected_files": len(members), "datasets": len(datasets),
                    "datasets_with_errors": sum(dataset["status"] != "ok" for dataset in datasets)},
    }
