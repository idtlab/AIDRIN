"""AIDRIN MCP Server — exposes AIDRIN data-readiness capabilities as Claude tools."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from aidrin.headless.api import (
    generate_metric_template,
    list_available_metrics,
    run_batch_metrics,
    run_custom_metric_logic,
    run_custom_metric_remedy,
    run_data_quality,
    run_metric,
    summarize_dataset as _summarize_dataset,
)
from aidrin.headless.config import HeadlessConfig

mcp_server = FastMCP("aidrin")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


# ---------------------------------------------------------------------------
# Dataset summary
# ---------------------------------------------------------------------------


@mcp_server.tool()
def summarize_dataset(
    file_path: str,
    file_type: str | None = None,
    max_features: int | None = None,
) -> str:
    """
    Summarize a dataset's numerical and categorical features.
    Returns shape, column names, descriptive stats (mean/std/min/max/quartiles),
    and missing counts. Use as the first step when assessing a dataset to identify
    column roles (target, sensitive attributes, quasi-identifiers, id column).

    Args:
        file_path: Absolute path to the dataset (CSV, Parquet, Excel, HDF5, JSON, NPZ).
        file_type: Optional file-type override (csv, parquet, xlsx, hdf5, json, npz).
        max_features: Limit stats to N features total, split evenly between numerical
                      and categorical. All column names still appear in 'columns'.
                      If one type has fewer columns than its share, the remainder goes
                      to the other type.
    """
    return _dumps(_summarize_dataset(file_path, file_type=file_type, max_features=max_features))


# ---------------------------------------------------------------------------
# Built-in metrics
# ---------------------------------------------------------------------------


@mcp_server.tool()
def list_metrics(category: str | None = None) -> str:
    """
    List all available AIDRIN metrics grouped by category.

    Args:
        category: Optional filter. One of: data-quality, impact-of-data-on-AI,
                  fairness-and-bias, data-governance, custom_metrics. Omit for all.
    """
    return _dumps(list_available_metrics(category=category))


@mcp_server.tool()
def run_data_quality_check(file_path: str, file_type: str | None = None) -> str:
    """
    Run the three core data-quality metrics (completeness, duplicity, outliers) on a dataset.
    Fast path — no column arguments needed.

    Args:
        file_path: Absolute path to the dataset (CSV, Parquet, Excel, HDF5, JSON, NPZ).
        file_type: Optional file-type override (csv, parquet, xlsx, hdf5, json, npz).
    """
    result = run_data_quality(file_path, file_type=file_type, strip_visualizations=True)
    return _dumps(result)


@mcp_server.tool()
def run_aidrin_metric(
    file_path: str,
    metric: str,
    file_type: str | None = None,
    columns: str | None = None,
    target_column: str | None = None,
    cat_columns: str | None = None,
    num_columns: str | None = None,
    quasi_identifiers: str | None = None,
    sensitive_column: str | None = None,
    id_column: str | None = None,
    eval_columns: str | None = None,
    y_true_column: str | None = None,
    sensitive_attribute_column: str | None = None,
    epsilon: float | None = None,
    distance_metric: str | None = None,
) -> str:
    """
    Run a single AIDRIN built-in metric against a dataset.
    Use list_metrics first to discover available metrics and their required arguments.
    Comma-separated strings are accepted for all multi-column arguments.

    Args:
        file_path: Absolute path to the dataset.
        metric: Metric name, e.g. completeness, k_anonymity, class_imbalance.
        file_type: File-type override.
        columns: Comma-separated columns (required by: correlations, representation_rate).
        target_column: Target/label column (required by: class_imbalance, feature_relevance).
        cat_columns: Comma-separated categorical columns (feature_relevance).
        num_columns: Comma-separated numerical columns (feature_relevance).
        quasi_identifiers: Comma-separated quasi-identifier columns (k_anonymity, l_diversity, t_closeness, entropy_risk).
        sensitive_column: Sensitive attribute column (l_diversity, t_closeness).
        id_column: ID column (single_attribute_risk, multiple_attribute_risk).
        eval_columns: Comma-separated evaluation columns (single_attribute_risk, multiple_attribute_risk).
        y_true_column: Ground-truth column (statistical_rates).
        sensitive_attribute_column: Sensitive attribute column (statistical_rates).
        epsilon: Epsilon value for differential_privacy.
        distance_metric: Distance metric override (class_imbalance).
    """
    kwargs: dict[str, Any] = {
        k: v
        for k, v in [
            ("columns", columns),
            ("target_column", target_column),
            ("cat_columns", cat_columns),
            ("num_columns", num_columns),
            ("quasi_identifiers", quasi_identifiers),
            ("sensitive_column", sensitive_column),
            ("id_column", id_column),
            ("eval_columns", eval_columns),
            ("y_true_column", y_true_column),
            ("sensitive_attribute_column", sensitive_attribute_column),
            ("epsilon", epsilon),
            ("distance_metric", distance_metric),
        ]
        if v is not None
    }
    result = run_metric(
        metric,
        file_path,
        file_type=file_type,
        strip_visualizations=True,
        save_images=False,
        **kwargs,
    )
    return _dumps(result)


@mcp_server.tool()
def run_batch(config_path: str) -> str:
    """
    Run multiple AIDRIN metrics declared in a YAML or JSON batch config file.

    Args:
        config_path: Absolute path to a YAML or JSON batch config.
    """
    config = HeadlessConfig.from_file(config_path)
    result = run_batch_metrics(config, strip_visualizations=True)
    return _dumps(result)


# ---------------------------------------------------------------------------
# Custom metrics and remedies
# ---------------------------------------------------------------------------


@mcp_server.tool()
def run_custom_metric(metric_name_or_path: str, file_path: str) -> str:
    """
    Run the metric() method of a CustomDR class defined in a .py file.

    Args:
        metric_name_or_path: Full path to the custom .py file, OR a metric name that
                             resolves to aidrin/custom_metrics/<name>.py relative to cwd.
        file_path: Absolute path to the dataset CSV.
    """
    result = run_custom_metric_logic(metric_name_or_path, file_path)
    return _dumps(result)


@mcp_server.tool()
def run_custom_remedy(
    metric_name_or_path: str,
    file_path: str,
    output_dir: str | None = None,
) -> str:
    """
    Run the remedy() method of a CustomDR class, apply it to the dataset,
    and save the remedied data as a CSV file.

    Args:
        metric_name_or_path: Full path to the custom .py file, or metric name.
        file_path: Absolute path to the dataset CSV.
        output_dir: Directory to write the remedied CSV.
                    Defaults to <script_dir>/remedy_data/.
    """
    saved_path = run_custom_metric_remedy(
        metric_name_or_path,
        file_path,
        output_dir=output_dir,
    )
    return _dumps({
        "remedied_file": saved_path,
        "message": f"Remedied dataset saved to {saved_path}",
    })


@mcp_server.tool()
def create_custom_metric(name: str, directory: str) -> str:
    """
    Generate a CustomDR template .py file with metric() and remedy() method stubs
    ready for you to fill in.

    Args:
        name: Name for the custom metric module (e.g. my_audit). No spaces or special chars.
        directory: Directory path where the template file should be created.
    """
    try:
        path = generate_metric_template(name, directory)
    except FileExistsError as exc:
        return _dumps({"error": str(exc)})

    return _dumps({
        "template_file": path,
        "next_steps": [
            f"Edit {path} — implement metric() to return a dict, remedy() to return a DataFrame.",
            f"Run metric via MCP:  call run_custom_metric  with metric_name_or_path='{path}'",
            f"Apply remedy via MCP: call run_custom_remedy with metric_name_or_path='{path}'",
            f"Or via CLI: aidrin run custom {path} <dataset.csv> metric",
        ],
    })


# ---------------------------------------------------------------------------
# Agentic pipeline
# ---------------------------------------------------------------------------


@mcp_server.tool()
def agentic_build_index(config_path: str) -> str:
    """
    Build the FAISS vector index from domain-literature PDFs declared in the agentic YAML config.
    Run this once before agentic_run when using RAG-based retrieval.
    Requires: pip install 'aidrin[agentic]'

    Args:
        config_path: Absolute path to the agentic YAML config file.
    """
    try:
        from aidrin.agentic.vector_db_builder import VectorDBBuilder
    except ImportError:
        return _dumps({"error": "Agentic dependencies not installed. Run: pip install 'aidrin[agentic]'"})

    result = VectorDBBuilder(Path(config_path).resolve()).build()
    return _dumps(result)


@mcp_server.tool()
def agentic_run(
    config_path: str,
    output_path: str | None = None,
    skip_vector: bool = False,
) -> str:
    """
    Run the full AIDRIN agentic evaluation pipeline:
      1. Profile the dataset
      2. Build / reuse the FAISS vector index
      3. Retrieve relevant literature passages for each question
      4. Generate and self-heal Python analysis code
      5. Score query complexity
      6. Generate remediation recommendations
    Returns the combined JSON result (profile + per-question results + token usage).
    Requires: pip install 'aidrin[agentic]'

    Args:
        config_path: Absolute path to the agentic YAML config file.
        output_path: Optional path to also write the full JSON results to disk.
        skip_vector: If true, skip rebuilding the vector index and use the existing one.
    """
    try:
        import yaml
        from aidrin.agentic.data_profiler import DataProfiler
        from aidrin.agentic.vector_db_builder import VectorDBBuilder
        from aidrin.agentic.run import _run_query, _json_safe
        from aidrin.agentic.token_tracker import get_tracker
    except ImportError:
        return _dumps({"error": "Agentic dependencies not installed. Run: pip install 'aidrin[agentic]'"})

    resolved = Path(config_path).resolve()
    if not resolved.exists():
        return _dumps({"error": f"Config file not found: {resolved}"})

    get_tracker().reset()
    profiler = DataProfiler(config_path=resolved)
    profile_result = profiler.profile()

    cfg = yaml.safe_load(resolved.read_text()) or {}

    if not skip_vector and cfg.get("vector_store"):
        builder = VectorDBBuilder(resolved)
        if not builder.exists():
            builder.build()

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
                pool.submit(_run_query, resolved, text, profile_result, loader): text
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

    if output_path:
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
        combined["_saved_to"] = str(out)

    return _dumps(combined)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    mcp_server.run()


if __name__ == "__main__":
    main()
