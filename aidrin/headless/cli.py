import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional
import os

from .api import (
    METRIC_REGISTRY,
    list_available_metrics,
    run_batch_metrics,
    run_data_quality,
    run_metric,
    generate_metric_template,
    run_custom_metric_remedy,
)
from .config import HeadlessConfig


def _parse_list(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _dump_result(result: object) -> None:
    sys.stdout.write(json.dumps(result, indent=2))
    sys.stdout.write("\n")


def _summarize_data_quality(result: dict) -> None:
    """Print a compact summary of data quality results."""
    # Completeness
    comp = result.get("completeness", {})
    overall_comp = comp.get("Overall Completeness", "N/A")
    scores = comp.get("Completeness scores", {})
    n_features = len(scores)
    if scores:
        vals = list(scores.values())
        min_comp = min(vals)
        incomplete = sum(1 for v in vals if v < 1.0)
    else:
        min_comp = "N/A"
        incomplete = 0

    # Duplicity
    dup = result.get("duplicity", {})
    dup_scores = dup.get("Duplicity scores", {})
    dup_ratio = dup_scores.get("Overall duplicity of the dataset", "N/A")

    # Outliers
    out = result.get("outliers", {})
    out_scores = out.get("Outlier scores", {})
    overall_outlier = out_scores.get("Overall outlier score", "N/A")
    feature_outliers = {k: v for k, v in out_scores.items() if k != "Overall outlier score"}
    if feature_outliers:
        max_outlier = max(feature_outliers.values())
        high_outlier = sum(1 for v in feature_outliers.values() if v > 0.05)
    else:
        max_outlier = "N/A"
        high_outlier = 0

    print(f"Data Quality Summary ({n_features} features)")
    print(f"{'='*45}")
    print(f"Completeness:  {_fmt(overall_comp)}  (min: {_fmt(min_comp)}, incomplete: {incomplete}/{n_features})")
    print(f"Duplicity:     {_fmt(dup_ratio)}")
    print(f"Outliers:      {_fmt(overall_outlier)}  (max: {_fmt(max_outlier)}, >5%: {high_outlier}/{n_features})")


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _round_floats(obj, ndigits: int = 4):
    """Recursively round float values for cleaner CLI output."""
    from numbers import Number

    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, list):
        return [_round_floats(item, ndigits) for item in obj]
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    # Keep other numerics (int, Decimal) unchanged
    if isinstance(obj, Number):
        return obj
    return obj


def _summarize_metric(metric_name: str, result: dict) -> None:
    """Print a compact summary for a single metric result."""
    if metric_name == "completeness":
        overall = result.get("Overall Completeness", "N/A")
        scores = result.get("Completeness scores", {})
        n = len(scores)
        if scores:
            vals = list(scores.values())
            incomplete = sum(1 for v in vals if v < 1.0)
            print(f"Completeness ({n} features): {_fmt(overall)}  (min: {_fmt(min(vals))}, incomplete: {incomplete}/{n})")
        else:
            print(f"Completeness: {_fmt(overall)}")
    elif metric_name == "duplicity":
        dup_scores = result.get("Duplicity scores", {})
        ratio = dup_scores.get("Overall duplicity of the dataset", "N/A")
        print(f"Duplicity: {_fmt(ratio)}")
    elif metric_name == "outliers":
        scores = result.get("Outlier scores", {})
        overall = scores.get("Overall outlier score", "N/A")
        feature_scores = {k: v for k, v in scores.items() if k != "Overall outlier score"}
        n = len(feature_scores)
        if feature_scores:
            mx = max(feature_scores.values())
            high = sum(1 for v in feature_scores.values() if v > 0.05)
            print(f"Outliers ({n} features): {_fmt(overall)}  (max: {_fmt(mx)}, >5%: {high}/{n})")
        else:
            print(f"Outliers: {_fmt(overall)}")
    else:
        # Generic: print top-level keys with scalar values, count dict/list values
        for k, v in result.items():
            if "visualization" in k.lower():
                continue
            if isinstance(v, dict):
                print(f"{k}: ({len(v)} entries)")
            elif isinstance(v, list):
                print(f"{k}: [{len(v)} items]")
            else:
                print(f"{k}: {_fmt(v)}")


def _build_run_kwargs(args: argparse.Namespace) -> dict:
    return {
        "columns": _parse_list(getattr(args, "columns", None)),
        "target_column": getattr(args, "target_column", None),
        "quasi_identifiers": _parse_list(getattr(args, "quasi_identifiers", None)),
        "sensitive_column": getattr(args, "sensitive_column", None),
        "epsilon": getattr(args, "epsilon", None),
        "id_column": getattr(args, "id_column", None),
        "eval_columns": _parse_list(getattr(args, "eval_columns", None)),
        "distance_metric": getattr(args, "distance_metric", None),
        "cat_columns": _parse_list(getattr(args, "cat_columns", None)),
        "num_columns": _parse_list(getattr(args, "num_columns", None)),
        "y_true_column": getattr(args, "y_true_column", None),
        "sensitive_attribute_column": getattr(args, "sensitive_attribute_column", None),
        # Default to no image generation/saving for headless usage
        "save_images": getattr(args, "save_images", False),
        "image_dir": getattr(args, "image_dir", None),
        "verbose": getattr(args, "verbose", False),
        # Do not emit viz payloads by default
        "strip_visualizations": getattr(args, "no_viz", True),
    }


def _configure_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--file-type", dest="file_type", default=None, help="Input file type override")
    parser.add_argument("--save-images", dest="save_images", action="store_true", help="Save visualizations to disk")
    parser.add_argument("--no-save-images", dest="save_images", action="store_false", help="Do not save visualizations")
    parser.set_defaults(save_images=True)
    parser.add_argument("--image-dir", default=None, help="Directory to write images")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show progress output")
    parser.add_argument("--no-viz", action="store_true", help="Strip visualization data from output", default=True)
    parser.add_argument("--detail", action="store_true", help="Output full JSON instead of summary", default=True)


def _configure_minimal_run_args(parser: argparse.ArgumentParser) -> None:
    """Lightweight args for top-level metric shortcuts."""
    parser.add_argument("-v", "--verbose", action="store_true", help="Show progress output")


def _add_required_metric_args(parser: argparse.ArgumentParser, required_args: List[str]) -> None:
    """Attach only the args needed for a specific metric."""
    for arg in required_args:
        if arg == "columns":
            parser.add_argument("columns", help="Comma-separated column list", metavar="columns")
        elif arg == "target-column":
            parser.add_argument("target_column", help="Target column name", metavar="target-column")
        elif arg == "quasi-identifiers":
            parser.add_argument("quasi_identifiers", help="Comma-separated quasi-identifier columns", metavar="quasi-identifiers")
        elif arg == "sensitive-column":
            parser.add_argument("sensitive_column", help="Sensitive column name", metavar="sensitive-column")
        elif arg == "epsilon":
            parser.add_argument("epsilon", type=float, help="Epsilon for differential privacy", metavar="epsilon")
        elif arg == "id-column":
            parser.add_argument("id_column", help="ID column for Markov risk metrics", metavar="id-column")
        elif arg == "eval-columns":
            parser.add_argument("eval_columns", help="Comma-separated eval columns", metavar="eval-columns")
        elif arg == "distance-metric":
            parser.add_argument("distance_metric", help="Distance metric", metavar="distance-metric")
        elif arg == "cat-columns":
            parser.add_argument(
                "cat_columns",
                nargs="?",
                default=None,
                help="Comma-separated categorical columns (optional; provide at least one of categorical-columns or numerical-columns)",
                metavar="categorical-columns",
            )
        elif arg == "num-columns":
            parser.add_argument(
                "num_columns",
                nargs="?",
                default=None,
                help="Comma-separated numerical columns (optional; provide at least one of categorical-columns or numerical-columns)",
                metavar="numerical-columns",
            )
        elif arg == "y-true-column":
            parser.add_argument("y_true_column", help="Ground truth column", metavar="y-true-column")
        elif arg == "sensitive-attribute-column":
            parser.add_argument("sensitive_attribute_column", help="Sensitive attribute column", metavar="sensitive-attribute-column")


def _agentic_build_index(args: argparse.Namespace) -> None:
    try:
        from aidrin.agentic.vector_db_builder import VectorDBBuilder
    except ImportError:
        sys.stderr.write("Error: agentic dependencies not installed. Run: pip install 'aidrin[agentic]'\n")
        sys.exit(1)
    result = VectorDBBuilder(Path(args.config).resolve()).build()
    print(json.dumps(result, indent=2))


def _agentic_run(args: argparse.Namespace) -> None:
    try:
        import yaml
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from aidrin.agentic.data_profiler import DataProfiler
        from aidrin.agentic.vector_db_builder import VectorDBBuilder
        from aidrin.agentic.run import _run_query, _json_safe
        from aidrin.agentic.token_tracker import get_tracker
    except ImportError:
        sys.stderr.write("Error: agentic dependencies not installed. Run: pip install 'aidrin[agentic]'\n")
        sys.exit(1)

    config_path = Path(args.config).resolve()
    get_tracker().reset()

    profiler = DataProfiler(config_path=config_path)
    profile_result = profiler.profile()

    cfg = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}

    if not args.skip_vector and cfg.get("vector_store"):
        builder = VectorDBBuilder(config_path)
        if not builder.exists():
            vector_result = builder.build()
            if getattr(args, "verbose", False):
                sys.stderr.write(json.dumps(vector_result, indent=2) + "\n")

    retrieval_cfg = cfg.get("retrieval", {}) or {}
    questions_raw = retrieval_cfg.get("questions") or []
    if not questions_raw:
        single = retrieval_cfg.get("question", "")
        questions_raw = single if isinstance(single, list) else ([single] if single else [])

    def _parse_q(q):
        return (q["text"], q.get("loader")) if isinstance(q, dict) else (q, None)

    parsed_questions = [_parse_q(q) for q in questions_raw]

    max_workers = int(retrieval_cfg.get("max_workers", 4))
    query_results = []
    if parsed_questions:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(parsed_questions))) as pool:
            futures = {
                pool.submit(_run_query, config_path, text, profile_result, loader): text
                for text, loader in parsed_questions
            }
            for future in as_completed(futures):
                try:
                    query_results.append(future.result())
                except Exception as exc:
                    query_results.append({"question": futures[future], "error": str(exc)})

    combined = _json_safe({
        "profile": profile_result,
        "queries": query_results,
        "token_usage": get_tracker().to_dict(),
    })

    if args.output:
        out = Path(args.output).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
        sys.stderr.write(f"Results written to: {out}\n")

    print(json.dumps(combined, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="aidrin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "add-custom-module",
        help="Create a new custom module template (metric + remedy) in a directory you specify",
    )
    create_parser.add_argument(
        "name",
        help="Name of the custom module (e.g. 'my_audit'). No spaces or special characters.",
    )
    create_parser.add_argument(
        "--dir",
        dest="custom_dir",
        required=True,
        help="Directory to create the module in (e.g. --dir /path/to/my_project)",
    )

    list_parser = subparsers.add_parser("list", help="List available metrics")
    list_parser.add_argument("--category", default=None)

    run_parser = subparsers.add_parser("run", help="Run a metric (per-metric help via: aidrin run <metric> -h)")
    run_subparsers = run_parser.add_subparsers(dest="metric", required=True)

    # Built-in metrics
    for metric_name, meta in METRIC_REGISTRY.items():
        extra_help = ""
        if metric_name == "feature_relevance":
            extra_help = (
                " (provide categorical-columns or numerical-columns; example: "
                "aidrin feature-relevance data.csv \"gender\" \"age,income\" target)"
            )
        metric_cli = metric_name.replace("_", "-")
        mparser = run_subparsers.add_parser(metric_cli, help=meta["description"] + extra_help)
        mparser.add_argument("file_path", help="Path to the dataset CSV")
        _add_required_metric_args(mparser, meta.get("required_args", []))
        _configure_minimal_run_args(mparser)
        mparser.set_defaults(_metric_key=metric_name, _action="metric")

    # Custom metric / remedy runner
    custom_parser = run_subparsers.add_parser(
        "custom",
        help="Run a custom metric or remedy from a .py file",
    )
    custom_parser.add_argument("name", help="Path to the custom module file (e.g. /path/to/my_audit.py)")
    custom_parser.add_argument("file_path", help="Path to the dataset CSV")
    custom_parser.add_argument("action", nargs="?", choices=["metric", "remedy"], default="metric", help="Run metric (default) or remedy")
    _configure_minimal_run_args(custom_parser)

    batch_parser = subparsers.add_parser("batch", help="Run metrics from config file (JSON or YAML)")
    batch_parser.add_argument("config_path")
    batch_parser.add_argument("-v", "--verbose", action="store_true", help="Show progress output")
    batch_parser.add_argument(
        "--viz",
        dest="no_viz",
        action="store_false",
        help="Include visualization data in output",
        default=True,
    )

    # Fast data quality command
    dq_parser = subparsers.add_parser("data-quality", help="Run fast data quality metrics (completeness, duplicity, outliers)")
    dq_parser.add_argument("file_path")
    dq_parser.add_argument("--file-type", dest="file_type", default=None)
    dq_parser.add_argument("-v", "--verbose", action="store_true", help="Show progress output")
    dq_parser.add_argument("--detail", action="store_true", help="Output full per-feature JSON instead of summary")

    # Agentic evaluation commands
    agentic_parser = subparsers.add_parser("agentic", help="Agentic evaluation commands (requires aidrin[agentic])")
    agentic_sub = agentic_parser.add_subparsers(dest="agentic_command", required=True)

    build_parser = agentic_sub.add_parser("build-index", help="Build vector index from domain literature")
    build_parser.add_argument("-c", "--config", required=True, help="Path to YAML config")
    build_parser.add_argument("-v", "--verbose", action="store_true", help="Show progress output")

    agentic_run_parser = agentic_sub.add_parser("run", help="Run the agentic evaluation pipeline")
    agentic_run_parser.add_argument("-c", "--config", required=True, help="Path to YAML config")
    agentic_run_parser.add_argument("-o", "--output", default=None, help="Path to write JSON results")
    agentic_run_parser.add_argument("--skip-vector", dest="skip_vector", action="store_true",
                                    help="Skip rebuilding the vector index; use existing one")
    agentic_run_parser.add_argument("-v", "--verbose", action="store_true", help="Print vector build info to stderr")

    argv = sys.argv[1:]
    # Shortcut: allow `aidrin <metric> ...` (dash or underscore) to map to `aidrin run <metric> ...`
    if argv:
        metric_key = argv[0].replace("-", "_")
        if metric_key in METRIC_REGISTRY:
            argv = ["run", metric_key] + argv[1:]
    args = parser.parse_args(argv)

    try:
        if args.command == "add-custom-module":
            target_dir = args.custom_dir or os.getcwd()
            try:
                path = generate_metric_template(args.name, target_dir)
                print(f"Template successfully created at: {path}")
                print("Edit the 'metric' and 'remedy' methods to add your logic.")
                print(f"Run the metric via: aidrin run custom {path} <dataset> metric")
                print(f"Run the remedy via: aidrin run custom {path} <dataset> remedy")
            except FileExistsError as e:
                print(f"{e}")
            return
        if args.command == "list":
            _dump_result(_round_floats(list_available_metrics(category=args.category)))
            return

        if args.command == "run":
            # Built-in metrics
            metric_key = getattr(args, "_metric_key", None)
            if metric_key:
                if metric_key == "feature_relevance" and not (args.cat_columns or args.num_columns):
                    sys.stderr.write(
                        "Error: provide at least one of categorical-columns or numerical-columns\n"
                    )
                    sys.exit(2)
                result = run_metric(
                    metric_key,
                    args.file_path,
                    file_type=getattr(args, "file_type", None),
                    **_build_run_kwargs(args),
                )
                if getattr(args, "detail", True):
                    _dump_result(_round_floats(result))
                else:
                    _summarize_metric(metric_key, result)
                return

            # Custom metrics/remedies
            if args.metric == "custom":
                if args.action == "remedy":
                    output_path = run_custom_metric_remedy(
                        args.name,
                        args.file_path,
                        output_dir=None,
                        file_type=getattr(args, "file_type", None),
                        **_build_run_kwargs(args),
                    )
                    print(f"Remedied data saved to: {output_path}")
                    return
                result = run_metric(
                    args.name,
                    args.file_path,
                    file_type=getattr(args, "file_type", None),
                    **_build_run_kwargs(args),
                )
                if getattr(args, "detail", True):
                    _dump_result(_round_floats(result))
                else:
                    _summarize_metric(args.name.strip().lower(), result)
                return

        # Top-level metric shortcut (e.g., `aidrin completeness ...`)
        if args.command in METRIC_REGISTRY:
            if args.command == "feature_relevance" and not (args.cat_columns or args.num_columns):
                sys.stderr.write(
                    "Error: provide at least one of categorical-columns or numerical-columns\n"
                )
                sys.exit(2)
            result = run_metric(
                args.command,
                args.file_path,
                file_type=getattr(args, "file_type", None),
                **_build_run_kwargs(args),
            )
            if getattr(args, "detail", True):
                _dump_result(_round_floats(result))
            else:
                _summarize_metric(args.command, result)
            return

        if args.command == "batch":
            config = HeadlessConfig.from_file(args.config_path)
            result = run_batch_metrics(
                config,
                verbose=args.verbose,
                strip_visualizations=args.no_viz,
            )
            _dump_result(_round_floats(result))
            return

        if args.command == "data-quality":
            result = run_data_quality(
                args.file_path,
                file_type=args.file_type,
                verbose=args.verbose,
                strip_visualizations=True,
            )
            if args.detail:
                _dump_result(_round_floats(result))
            else:
                _summarize_data_quality(result)
            return

        if args.command == "agentic":
            if args.agentic_command == "build-index":
                _agentic_build_index(args)
            elif args.agentic_command == "run":
                _agentic_run(args)
            return
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
