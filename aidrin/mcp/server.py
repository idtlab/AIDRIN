"""AIDRIN MCP Server — exposes AIDRIN data-readiness capabilities as Claude tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from aidrin.headless.api import (
    generate_metric_template,
    list_available_metrics,
    run_agentic_index,
    run_agentic_pipeline,
    run_custom_metric_logic,
    run_custom_metric_remedy,
    run_metric,
)
from aidrin.headless.config import HeadlessConfig
from aidrin.telemetry import mlflow_sink

# Importing this module means the process is serving MCP, so sessions opened
# implicitly inside run_batch_metrics are attributed to the right interface.
mlflow_sink.set_default_interface("mcp")

mcp_server = MCPServer("aidrin")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


def _executor(endpoint: str | None, profile: str | None):
    """Return the remote executor when asked for one, else the local api module."""
    if not endpoint and not profile:
        from aidrin.headless import api

        return api
    from aidrin.compute.executor import RemoteExecutor
    from aidrin.compute.profiles import resolve

    return RemoteExecutor(resolve(endpoint=endpoint, profile=profile))


# ---------------------------------------------------------------------------
# Dataset summary
# ---------------------------------------------------------------------------


@mcp_server.tool()
def summarize_dataset(
    file_path: str,
    file_type: str | None = None,
    max_features: int | None = None,
    endpoint: str | None = None,
    profile: str | None = None,
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
        endpoint: Optional Globus Compute endpoint UUID. When set, the summary runs
                  on that endpoint and file_path must be a path visible there.
        profile: Optional configured endpoint profile name (see list_remote_profiles).
    """
    return _dumps(
        _executor(endpoint, profile).summarize_dataset(
            file_path, file_type=file_type, max_features=max_features
        )
    )


# ---------------------------------------------------------------------------
# Built-in metrics
# ---------------------------------------------------------------------------


@mcp_server.tool()
def list_metrics(category: str | None = None) -> str:
    """
    List all available AIDRIN metrics grouped by category.

    Args:
        category: Optional filter. One of: data-quality, data-structure,
                  impact-of-data-on-AI, fairness-and-bias, data-governance,
                  custom_metrics. Omit for all.
    """
    # The catalogue is wrapped rather than extended: the model is told to iterate
    # the category mapping, so a stray boolean beside the category keys would be
    # read as a category.
    return _dumps(
        {
            "metrics": list_available_metrics(category=category),
            "mlflow_enabled": mlflow_sink.is_enabled(),
        }
    )


@mcp_server.tool()
def run_data_quality_check(
    file_path: str,
    file_type: str | None = None,
    endpoint: str | None = None,
    profile: str | None = None,
) -> str:
    """
    Run the three core data-quality metrics (completeness, duplicity, outliers) on a dataset.
    Fast path — no column arguments needed.

    Args:
        file_path: Absolute path to the dataset (CSV, Parquet, Excel, HDF5, JSON, NPZ).
        file_type: Optional file-type override (csv, parquet, xlsx, hdf5, json, npz).
        endpoint: Optional Globus Compute endpoint UUID. When set, the metric runs
                  on that endpoint and file_path must be a path visible there.
        profile: Optional configured endpoint profile name (see list_remote_profiles).
    """
    result = _executor(endpoint, profile).run_data_quality(
        file_path, file_type=file_type, strip_visualizations=True
    )
    return _dumps(result)


@mcp_server.tool()
def run_aidrin_metric(
    file_path: str,
    metric: str,
    file_type: str | None = None,
    rules_json: str | None = None,
    rules_file: str | None = None,
    max_outliers: int = 100,
    max_export_rows: int = 10000,
    max_results: int = 100,
    scan_limit: int | None = None,
    stop_after_outliers: bool = False,
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
    required_columns: str | None = None,
    duplicate_columns: str | None = None,
    threshold: float | None = None,
    frequency: str | None = None,
    timestamp_column: str | None = None,
    batch_column: str | None = None,
    target_columns: str | None = None,
    path_targets: str | list[str] | None = None,
    base_dir: str | None = None,
    target_match: str = "exact",
    endpoint: str | None = None,
    profile: str | None = None,
    session_id: str | None = None,
) -> str:
    """
    Run a single AIDRIN built-in metric against a dataset.
    Use list_metrics first to discover available metrics and their required arguments.
    Comma-separated strings are accepted for all multi-column arguments.

    Args:
        file_path: Absolute path to the dataset.
        metric: Metric name, e.g. completeness, outliers-custom, k_anonymity, class_imbalance.
        file_type: File-type override.
        rules_json: JSON array of valid-value rules when metric is outliers-custom.
        rules_file: Server-local path to a JSON array of valid-value rules when metric is outliers-custom.
        max_outliers: Preview cap per custom outlier rule; 0 means unlimited.
        max_export_rows: Export row cap per custom outlier rule; 0 means unlimited.
        max_results: Maximum detail records for file-reference-validation; 0 means unlimited.
        scan_limit: Optional maximum values to scan for custom outliers or file-reference-validation.
        stop_after_outliers: Stop scanning after the preview cap is reached.
        columns: Comma-separated columns (required by: correlations, representation_rate, hipaa_compliance).
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
        required_columns: Comma-separated required columns (row_level_completeness).
        duplicate_columns: Comma-separated columns to compare for duplicates (duplicity_by_features).
        threshold: Coverage threshold in [0, 1] (feature_coverage_ratio, default 0.9).
        frequency: Interval frequency for temporal_completeness (default "D").
            One of: min (minute), h (hourly), D (daily), W (weekly),
            ME (month-end), QE (quarter-end), YE (year-end).
        timestamp_column: Datetime column (temporal_completeness).
        batch_column: Batch/partition column (null_count_trend).
        target_columns: Comma-separated columns to count nulls in (null_count_trend, optional).
        path_targets: Comma-separated exact targets or one regex string. Use a list for multiple regex patterns.
        base_dir: Server-local directory used to resolve relative file references.
        target_match: Interpret path_targets as exact names or full-match regular expressions.
        endpoint: Optional Globus Compute endpoint UUID. When set, the metric runs
                  on that endpoint and file_path must be a path visible there.
        profile: Optional configured endpoint profile name (see list_remote_profiles).
    """
    kwargs: dict[str, Any] = {
        k: v
        for k, v in [
            ("columns", columns),
            ("rules_json", rules_json),
            ("rules_file", rules_file),
            ("max_outliers", max_outliers),
            ("max_export_rows", max_export_rows),
            ("max_results", max_results),
            ("scan_limit", scan_limit),
            ("stop_after_outliers", stop_after_outliers),
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
            ("required_columns", required_columns),
            ("duplicate_columns", duplicate_columns),
            ("threshold", threshold),
            ("frequency", frequency),
            ("timestamp_column", timestamp_column),
            ("batch_column", batch_column),
            ("target_columns", target_columns),
            ("path_targets", path_targets),
            ("base_dir", base_dir),
            ("target_match", target_match),
        ]
        if v is not None
    }
    if session_id and not endpoint and not profile:
        kwargs["session_id"] = session_id

    result = _executor(endpoint, profile).run_metric(
        metric,
        file_path,
        file_type=file_type,
        strip_visualizations=True,
        save_images=False,
        **kwargs,
    )
    return _dumps(result)


@mcp_server.tool()
def verify_file_references(
    file_path: str,
    path_targets: str | list[str],
    file_type: str | None = None,
    base_dir: str | None = None,
    max_results: int = 100,
    scan_limit: int | None = None,
    target_match: str = "exact",
) -> str:
    """
    Validate file references stored in selected dataset targets and return file metadata.
    Relative references and all filesystem checks are resolved on the MCP server host.

    Args:
        file_path: Absolute path to the manifest dataset.
        path_targets: Comma-separated exact targets or one regex string. Use a list for multiple regex patterns.
        file_type: Optional file-type override.
        base_dir: Server-local directory used to resolve relative references. Defaults to
                  the manifest's parent directory.
        max_results: Maximum invalid and metadata detail records; 0 means unlimited.
        scan_limit: Optional maximum reference values to scan; omitted or 0 means unlimited.
        target_match: Interpret path_targets as exact names or full-match regular expressions.
    """
    result = run_metric(
        "file-reference-validation",
        file_path,
        file_type=file_type,
        path_targets=path_targets,
        base_dir=base_dir,
        max_results=max_results,
        scan_limit=scan_limit,
        target_match=target_match,
        strip_visualizations=True,
        save_images=False,
    )
    return _dumps(result)


@mcp_server.tool()
def run_custom_outlier_check(
    file_path: str,
    rules_json: str | None = None,
    rules_file: str | None = None,
    file_type: str | None = None,
    max_outliers: int = 100,
    max_export_rows: int = 10000,
    scan_limit: int | None = None,
    stop_after_outliers: bool = False,
) -> str:
    """
    Run Custom Criteria Outliers against selected dataset targets.
    Rules are a JSON array using the same criteria-tree syntax as the web UI:
    each rule has id, target, target_type, criteria, and optional name,
    allow_missing, and target_match. Set target_match to regex to apply a rule
    to every target whose complete name matches target.
    Criteria define expected valid values and support numeric ranges, regex
    patterns, and nested and/or/not operators. Values that do not satisfy the
    rule are flagged as outliers.

    Args:
        file_path: Absolute path to the dataset.
        rules_json: JSON array of valid-value rules. Provide this or rules_file.
        rules_file: Server-local path to a JSON array of valid-value rules.
        file_type: Optional file-type override.
        max_outliers: Preview cap per rule; 0 means unlimited.
        max_export_rows: Export row cap per rule; 0 means unlimited.
        scan_limit: Optional maximum values to scan per rule.
        stop_after_outliers: Stop scanning after the preview cap is reached.
    """
    result = run_metric(
        "outliers-custom",
        file_path,
        file_type=file_type,
        rules_json=rules_json,
        rules_file=rules_file,
        max_outliers=max_outliers,
        max_export_rows=max_export_rows,
        scan_limit=scan_limit,
        stop_after_outliers=stop_after_outliers,
        strip_visualizations=True,
        save_images=False,
    )
    return _dumps(result)


@mcp_server.tool()
def run_batch(
    config_path: str,
    endpoint: str | None = None,
    profile: str | None = None,
) -> str:
    """
    Run multiple AIDRIN metrics declared in a YAML or JSON batch config file.

    Args:
        config_path: Absolute path to a YAML or JSON batch config.
        endpoint: Optional Globus Compute endpoint UUID. config_path is read
                  locally; each metric's file_path inside it must be a path visible on that endpoint.
        profile: Optional configured endpoint profile name (see list_remote_profiles).
    """
    config = HeadlessConfig.from_file(config_path)
    result = _executor(endpoint, profile).run_batch_metrics(config, strip_visualizations=True)
    return _dumps(result)


@mcp_server.tool()
def list_remote_profiles() -> str:
    """
    List configured Globus Compute endpoint profiles for remote execution.
    Use before asking the user for an endpoint UUID: if a profile exists, pass
    its name as the `profile` argument to the run tools instead.
    """
    from aidrin.compute.profiles import list_profiles

    return _dumps(list_profiles())


# ---------------------------------------------------------------------------
# Custom metrics and remedies
# ---------------------------------------------------------------------------


@mcp_server.tool()
def run_custom_metric(
    metric_name_or_path: str,
    file_path: str,
    file_type: str | None = None,
) -> str:
    """
    Run the metric() method of a CustomDR class defined in a .py file.

    Args:
        metric_name_or_path: Full path to the custom .py file, OR a metric name that
                             resolves to aidrin/custom_metrics/<name>.py relative to cwd.
        file_path: Absolute path to the dataset (CSV, Parquet, Excel, HDF5, JSON, NPZ).
        file_type: Optional file-type override (csv, parquet, xlsx, hdf5, json, npz).
    """
    result = run_custom_metric_logic(metric_name_or_path, file_path, file_type=file_type)
    return _dumps(result)


@mcp_server.tool()
def run_custom_remedy(
    metric_name_or_path: str,
    file_path: str,
    output_dir: str | None = None,
    file_type: str | None = None,
) -> str:
    """
    Run the remedy() method of a CustomDR class, apply it to the dataset,
    and save the remedied data as a CSV file. The remedied output is always
    CSV regardless of the input format, since JSON/NPZ/HDF5 are flattened on
    read and don't round-trip losslessly back into their original structure.

    Args:
        metric_name_or_path: Full path to the custom .py file, or metric name.
        file_path: Absolute path to the dataset (CSV, Parquet, Excel, HDF5, JSON, NPZ).
        output_dir: Directory to write the remedied CSV.
                    Defaults to <script_dir>/remedy_data/.
        file_type: Optional file-type override (csv, parquet, xlsx, hdf5, json, npz).
    """
    saved_path = run_custom_metric_remedy(
        metric_name_or_path,
        file_path,
        output_dir=output_dir,
        file_type=file_type,
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
        result = run_agentic_index(config_path)
    except ImportError:
        return _dumps({"error": "Agentic dependencies not installed. Run: pip install 'aidrin[agentic]'"})
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
    resolved = Path(config_path).resolve()
    if not resolved.exists():
        return _dumps({"error": f"Config file not found: {resolved}"})

    try:
        combined = run_agentic_pipeline(
            str(resolved),
            output_path=output_path,
            skip_vector=skip_vector,
        )
    except ImportError:
        return _dumps({"error": "Agentic dependencies not installed. Run: pip install 'aidrin[agentic]'"})

    return _dumps(combined)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Assessment tracking (MLflow)
# ---------------------------------------------------------------------------


@mcp_server.tool()
def start_assessment(file_path: str) -> str:
    """
    Open an MLflow-tracked assessment and return its session_id.

    Only useful when list_metrics reports mlflow_enabled: true. Pass the returned
    session_id to each run_aidrin_metric call, then call end_assessment. Each
    metric becomes its own MLflow run nested under one parent run carrying the
    dataset's aggregated readiness scores.

    Args:
        file_path: Absolute path to the dataset being assessed.
    """
    session = mlflow_sink.start_session(file_path=file_path, interface="mcp")
    if session is None:
        return _dumps({"tracking": "disabled", "session_id": None})
    return _dumps({"tracking": "enabled", "session_id": session.session_id})


@mcp_server.tool()
def end_assessment(session_id: str, report_path: str | None = None) -> str:
    """
    Close a tracked assessment, writing its aggregated readiness scores.

    Args:
        session_id: The id returned by start_assessment.
        report_path: Optional path to the finished markdown report, attached to
                     the parent run as an artifact.
    """
    mlflow_sink.end_session(session_id, report_path=report_path)
    return _dumps({"session_id": session_id, "closed": True})


def main() -> None:
    mcp_server.run()


if __name__ == "__main__":
    main()
