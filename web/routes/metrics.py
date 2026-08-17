import hashlib
import io
import json
import logging
import math
import os
import time

import pandas as pd
from celery.result import AsyncResult
from web.telemetry import get_tracer, trace_metric
from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import safe_join
from aidrin.file_handling.file_parser import read_file
from aidrin.file_handling.value_iterators import iter_targets
from aidrin.structured_data_metrics.add_noise import return_noisy_stats
from aidrin.structured_data_metrics.class_imbalance import (
    calc_imbalance_degree,
    class_distribution_plot,
)
from aidrin.structured_data_metrics.completeness import completeness
from aidrin.structured_data_metrics.custom_outliers import calculate_custom_outliers
from aidrin.structured_data_metrics.conditional_demo_disp import (
    conditional_demographic_disparity,
)
from aidrin.structured_data_metrics.feature_coverage_ratio import feature_coverage_ratio
from aidrin.structured_data_metrics.file_reference_validation import calculate_file_reference_validation
from aidrin.structured_data_metrics.null_count_trend import null_count_trend
from aidrin.structured_data_metrics.row_level_completeness import row_level_completeness
from aidrin.structured_data_metrics.duplicity_by_features import duplicity_by_features
from aidrin.structured_data_metrics.constant_feature_count import constant_feature_count
from aidrin.structured_data_metrics.temporal_completeness import temporal_completeness
from aidrin.structured_data_metrics.correlation_score import calc_correlations
from aidrin.structured_data_metrics.duplicity import duplicity
from aidrin.structured_data_metrics.kurtosis import kurtosis
from aidrin.structured_data_metrics.max_pairwise_correlation import (
    max_pairwise_correlation,
)
from aidrin.structured_data_metrics.skewness import skewness
from aidrin.structured_data_metrics.FAIRness_datacite import categorize_keys_fair
from aidrin.structured_data_metrics.FAIRness_dcat import (
    categorize_metadata,
    extract_keys_and_values,
)
from aidrin.structured_data_metrics.feature_relevance import (
    data_cleaning,
    pearson_correlation,
    plot_features,
)
from aidrin.structured_data_metrics.hipaa_compliance import detect_hipaa_identifiers
from aidrin.structured_data_metrics.outliers import outliers
from aidrin.structured_data_metrics.privacy_measure import (
    calculate_multiple_attribute_risk_score,
    calculate_single_attribute_risk_score,
    compute_entropy_risk,
    compute_k_anonymity,
    compute_l_diversity,
    compute_t_closeness,
    generate_multiple_attribute_MM_risk_scores_groupby,
    generate_single_attribute_MM_risk_scores_groupby,
)
from aidrin.structured_data_metrics.representation_rate import (
    calculate_representation_rate,
    create_representation_rate_vis,
)
from aidrin.structured_data_metrics.statistical_rate import calculate_statistical_rates
from web.routes.utils import (
    build_file_info,
    confine_to_upload_folder,
    ensure_json_serializable,
    format_dict_values,
    generate_metric_cache_key,
    get_current_user_id,
    get_result_or_default,
    is_metric_cache_valid,
    store_result,
    summary_histograms,
    categorical_distribution_charts,
)

metrics_bp = Blueprint("metrics", __name__)

metric_time_log = logging.getLogger("metric")
METRIC_CELERY_TIMEOUT = 120
FILE_REFERENCE_DEFAULT_WEB_SCAN_LIMIT = 10000


def _file_reference_allowed_roots():
    configured = current_app.config.get("FILE_REFERENCE_ALLOWED_ROOTS")
    if configured is None:
        raw = os.environ.get("AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS", "")
        if raw:
            try:
                configured = json.loads(raw)
            except json.JSONDecodeError:
                metric_time_log.warning("AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS must be a JSON array")
                configured = []
    if not isinstance(configured, (list, tuple)):
        if configured is not None:
            metric_time_log.warning("FILE_REFERENCE_ALLOWED_ROOTS must be a list of absolute directories")
        return []

    roots = []
    seen = set()
    for value in configured:
        try:
            path = os.fspath(value)
            if not os.path.isabs(path):
                raise ValueError("not absolute")
            canonical = os.path.realpath(path)
            if not os.path.isdir(canonical):
                raise ValueError("not an existing directory")
        except (TypeError, ValueError, OSError) as exc:
            metric_time_log.warning("Ignoring invalid file-reference root %r: %s", value, exc)
            continue
        key = os.path.normcase(canonical)
        if key not in seen:
            seen.add(key)
            roots.append(canonical)
    return roots


def _file_reference_root_choices(roots):
    return [
        {"id": f"root-{index}", "label": root}
        for index, root in enumerate(roots)
    ]


def _file_reference_web_scan_limit():
    value = current_app.config.get("FILE_REFERENCE_WEB_SCAN_LIMIT")
    if value is None:
        value = os.environ.get(
            "AIDRIN_FILE_REFERENCE_WEB_SCAN_LIMIT",
            FILE_REFERENCE_DEFAULT_WEB_SCAN_LIMIT,
        )
    try:
        limit = int(value)
        if limit <= 0:
            raise ValueError
    except (TypeError, ValueError):
        metric_time_log.warning(
            "Invalid file-reference web scan limit %r; using %d",
            value,
            FILE_REFERENCE_DEFAULT_WEB_SCAN_LIMIT,
        )
        return FILE_REFERENCE_DEFAULT_WEB_SCAN_LIMIT
    return limit


def _file_reference_base_dir(roots, root_id, subdirectory):
    choices = {f"root-{index}": root for index, root in enumerate(roots)}
    if root_id not in choices:
        raise ValueError("Select an allowed filesystem root.")
    root = choices[root_id]
    relative = (subdirectory or "").strip()
    if os.path.isabs(relative):
        raise ValueError("Base subdirectory must be relative to the selected root.")
    candidate = safe_join(root, relative)
    if candidate is None:
        raise ValueError("Base subdirectory must stay inside the selected root.")
    candidate = os.path.realpath(candidate)
    try:
        inside_root = (
            os.path.commonpath([os.path.normcase(candidate), os.path.normcase(root)])
            == os.path.normcase(root)
        )
    except ValueError:
        inside_root = False
    if not inside_root:
        raise ValueError("Base subdirectory must stay inside the selected root.")
    if not os.path.isdir(candidate):
        raise ValueError("Base subdirectory must identify an existing directory.")
    return candidate


# ---------------------------------------------------------------------------
# Data Quality
# ---------------------------------------------------------------------------

@metrics_bp.route("/custom-outlier-targets", methods=["GET", "POST"])
def custom_outlier_targets():
    file_path = confine_to_upload_folder(session.get("uploaded_file_path"))
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    if not file_path:
        return jsonify({"success": False, "message": "No file uploaded"}), 200
    try:
        targets = iter_targets((file_path, file_name, file_type))
        roots = _file_reference_allowed_roots()
        file_reference = {
            "enabled": bool(roots),
            "roots": _file_reference_root_choices(roots),
            "scan_limit": _file_reference_web_scan_limit(),
        }
        if not roots:
            file_reference["message"] = "File-reference validation is not configured by the server administrator."
        return jsonify({
            "success": True,
            "targets": ensure_json_serializable(targets),
            "file_reference": file_reference,
        })
    except Exception as e:
        metric_time_log.error("Custom outlier target discovery failed: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "Custom outlier target discovery failed."}), 200


@metrics_bp.route("/data-quality", methods=["GET", "POST"])
def data_quality():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = build_file_info(file_path, file_name, file_type)

    if request.method == "POST":
        start_time = time.time()
        selected = [
            m for m in (
                "completeness", "row level completeness", "feature coverage ratio",
                "temporal completeness", "null count trend",
                "outliers", "duplicity", "duplicate detection by features",
                "custom_outliers",
            ) if request.form.get(m) == "yes"
        ]
        metric_time_log.info("Data Quality request started: %s", selected)

        tracer = get_tracer()
        with tracer.start_as_current_span("metric.data_quality") as span:
            span.set_attribute("metric.pillar", "data_quality")
            span.set_attribute("metric.selected", ",".join(selected))
            span.set_attribute("file.name", file_name or "")
            span.set_attribute("file.type", file_type or "")

            try:
                if "completeness" in selected:
                    t0 = time.time()
                    with tracer.start_as_current_span("metric.completeness"):
                        compl_dict = completeness(file_info)
                    compl_dict["Description"] = (
                        "Indicate the proportion of available data for each feature, "
                        "with values closer to 1 indicating high completeness, and values near "
                        "0 indicating low completeness. If the visualization is empty, it means "
                        "that all features are complete."
                    )
                    final_dict["Completeness"] = compl_dict
                    metric_time_log.info("Completeness took %.2f seconds", time.time() - t0)

                if "row level completeness" in selected:
                    required_columns = [
                        c.strip()
                        for c in request.form.getlist("required columns for row level completeness")
                        if c.strip()
                    ]
                    if not required_columns:
                        final_dict["Row-Level Completeness"] = {
                            "Error": "No required columns selected for row-level completeness."
                        }
                    else:
                        t0 = time.time()
                        with tracer.start_as_current_span("metric.row_level_completeness"):
                            final_dict["Row-Level Completeness"] = row_level_completeness(
                                required_columns, file_info
                            )
                        metric_time_log.info(
                            "Row-Level Completeness took %.2f seconds", time.time() - t0
                        )

                if "feature coverage ratio" in selected:
                    threshold_raw = request.form.get("threshold for feature coverage ratio")
                    threshold = 0.9
                    if threshold_raw and threshold_raw.strip():
                        try:
                            threshold = float(threshold_raw)
                        except ValueError:
                            threshold = None
                    if threshold is None:
                        final_dict["Feature Coverage Ratio"] = {
                            "Error": "Invalid threshold value. Threshold must be a number in [0, 1]."
                        }
                    else:
                        t0 = time.time()
                        with tracer.start_as_current_span("metric.feature_coverage_ratio"):
                            final_dict["Feature Coverage Ratio"] = feature_coverage_ratio(
                                threshold, file_info
                            )
                        metric_time_log.info(
                            "Feature Coverage Ratio took %.2f seconds", time.time() - t0
                        )

                if "temporal completeness" in selected:
                    timestamp_column = request.form.get("timestamp column for temporal completeness")
                    frequency = request.form.get("frequency for temporal completeness") or "D"
                    if not timestamp_column:
                        final_dict["Temporal Completeness"] = {
                            "Error": "No timestamp column selected for temporal completeness."
                        }
                    else:
                        t0 = time.time()
                        with tracer.start_as_current_span("metric.temporal_completeness"):
                            final_dict["Temporal Completeness"] = temporal_completeness(
                                timestamp_column, frequency, file_info
                            )
                        metric_time_log.info(
                            "Temporal Completeness took %.2f seconds", time.time() - t0
                        )

                if "null count trend" in selected:
                    batch_column = request.form.get("batch column for null count trend")
                    target_columns = [
                        c.strip()
                        for c in request.form.getlist("target columns for null count trend")
                        if c.strip()
                    ]
                    if not batch_column:
                        final_dict["Null Count Trend"] = {
                            "Error": "No batch column selected for null count trend."
                        }
                    else:
                        t0 = time.time()
                        with tracer.start_as_current_span("metric.null_count_trend"):
                            final_dict["Null Count Trend"] = null_count_trend(
                                batch_column, target_columns, file_info
                            )
                        metric_time_log.info(
                            "Null Count Trend took %.2f seconds", time.time() - t0
                        )

                if "outliers" in selected:
                    t0 = time.time()
                    with tracer.start_as_current_span("metric.outliers"):
                        out_dict = outliers(file_info)
                    out_dict["Description"] = (
                        "Outlier scores are calculated for numerical columns using the Interquartile"
                        " Range (IQR) method, where a score of 1 indicates that all data points in a "
                        "column are identified as outliers, a score of 0 signifies no outliers are detected"
                    )
                    final_dict["Outliers"] = out_dict
                    metric_time_log.info("Outliers took %.2f seconds", time.time() - t0)

                if "duplicity" in selected:
                    t0 = time.time()
                    with tracer.start_as_current_span("metric.duplicity"):
                        dup_dict = duplicity(file_info)
                    dup_dict["Description"] = (
                        "A value of 0 indicates no duplicates, and a value closer to 1 signifies a higher "
                        "proportion of duplicated data points in the dataset"
                    )
                    final_dict["Duplicity"] = dup_dict
                    metric_time_log.info("Duplicity took %.2f seconds", time.time() - t0)

                if "duplicate detection by features" in selected:
                    dup_features = [
                        c.strip()
                        for c in request.form.getlist("features for duplicate detection")
                        if c.strip()
                    ]
                    if not dup_features:
                        final_dict["Duplicates by Selected Features"] = {
                            "Error": "No features selected for duplicate detection."
                        }
                    else:
                        t0 = time.time()
                        with tracer.start_as_current_span("metric.duplicity_by_features"):
                            final_dict["Duplicates by Selected Features"] = duplicity_by_features(
                                dup_features, file_info
                            )
                        metric_time_log.info(
                            "Duplicates by Selected Features took %.2f seconds", time.time() - t0
                        )

                if "custom_outliers" in selected:
                    t0 = time.time()
                    try:
                        rules = json.loads(request.form.get("custom_outlier_rules", "[]"))
                    except json.JSONDecodeError as e:
                        final_dict["Custom Criteria Outliers"] = {"Error": f"Invalid custom outlier rules JSON: {e}"}
                    else:
                        max_outliers = request.form.get("max_outliers", 100)
                        scan_limit = request.form.get("scan_limit") or None
                        stop_after_outliers = request.form.get("stop_after_outliers") == "yes"
                        max_export_rows = request.form.get("max_export_rows", 10000)
                        try:
                            with tracer.start_as_current_span("metric.custom_outliers"):
                                # Call the plain function, not the @shared_task
                                # wrapper: invoking the bound task synchronously
                                # confuses CodeQL's argument mapping (it aligns
                                # ``rules`` with the ``file_info`` parameter
                                # because it can't see Celery's injected
                                # ``self``), yielding false-positive
                                # py/path-injection alerts in file_parser.
                                custom_dict = calculate_custom_outliers(
                                    file_info,
                                    rules,
                                    max_outliers,
                                    scan_limit,
                                    stop_after_outliers,
                                    max_export_rows,
                                )
                        except Exception as e:
                            metric_time_log.error("Custom Criteria Outliers error: %s", e, exc_info=True)
                            final_dict["Custom Criteria Outliers"] = {
                                "Error": f"{type(e).__name__}: {e}",
                                "Description": (
                                    "Custom criteria outliers are values that violate user-defined range "
                                    "or regex rules on selected columns or native HDF5 datasets."
                                ),
                            }
                        else:
                            custom_dict["Description"] = (
                                "Custom criteria outliers are values that violate user-defined range "
                                "or regex rules on selected columns or native HDF5 datasets."
                            )
                            final_dict["Custom Criteria Outliers"] = custom_dict
                    metric_time_log.info("Custom Criteria Outliers took %.2f seconds", time.time() - t0)

            except Exception as e:
                metric_time_log.error("Data Quality error: %s", e, exc_info=True)
                return jsonify({"error": f"{type(e).__name__}: {e}"}), 200

            duration_ms = (time.time() - start_time) * 1000
            span.set_attribute("metric.duration_ms", duration_ms)
            metric_time_log.info("Data Quality completed in %.2f seconds", time.time() - start_time)
            return store_result("metrics.data_quality", final_dict)

    return get_result_or_default("metrics.data_quality", file_path, file_name)


# ---------------------------------------------------------------------------
# Readiness Report (aggregated, non-interactive)
# ---------------------------------------------------------------------------

def _grade_label(score):
    """Map a 0–1 readiness score to a coarse status label."""
    if score is None:
        return "unknown"
    if score >= 0.9:
        return "good"
    if score >= 0.7:
        return "warning"
    return "poor"


# Dataset-overview readiness thresholds (per-feature profile)
_OVERVIEW_MISSING_WARNING = 0.05
_OVERVIEW_MISSING_POOR = 0.20
_OVERVIEW_DOMINANT_WARNING = 0.95
_OVERVIEW_HIGH_CARDINALITY = 50
_OVERVIEW_ID_UNIQUE_RATIO = 0.9
_OVERVIEW_CAT_TOP_N = 5
_OVERVIEW_MAX_FEATURE_PROFILES = 500
_OVERVIEW_MAX_NUMERICAL_SUMMARY_COLS = 500
_OVERVIEW_MAX_CATEGORICAL_DIST_COLS = 50
_READINESS_MAX_DETAIL_LIST_ITEMS = 50
_PROFILE_STATUS_RANK = {"poor": 0, "warning": 1, "good": 2}


def _cap_detail_list(items, max_items):
    """Return a capped list plus metadata for UI/PDF truncation notes."""
    total = len(items)
    if total <= max_items:
        return items, {"total": total, "shown": total, "truncated": False}
    return items[:max_items], {
        "total": total,
        "shown": max_items,
        "truncated": True,
    }


def _build_numerical_summary_for_overview(num_df):
    """Build describe() summary for overview details, capped on wide datasets."""
    if num_df.empty:
        return {}, {"total": 0, "shown": 0, "truncated": False}

    total = len(num_df.columns)
    cols = num_df.columns
    truncated = total > _OVERVIEW_MAX_NUMERICAL_SUMMARY_COLS
    if truncated:
        cols = cols[:_OVERVIEW_MAX_NUMERICAL_SUMMARY_COLS]

    numerical_summary = num_df[cols].describe().to_dict()
    for v in numerical_summary.values():
        for old_key in list(v.keys()):
            if old_key in ["25%", "50%", "75%"]:
                new_key = old_key.replace("%", "th percentile")
                v[new_key] = float(v.pop(old_key))
        for stat_key, stat_val in list(v.items()):
            if stat_val is not None and not isinstance(stat_val, str):
                v[stat_key] = float(stat_val)

    return numerical_summary, {
        "total": total,
        "shown": len(cols),
        "truncated": truncated,
    }


def _classify_feature_type(series):
    """Map a pandas Series to a coarse feature type label."""
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        return "numerical"
    return "categorical"


def _feature_readiness_status(pct_missing, n_unique, n_rows, feat_type, pct_dominant):
    """Derive a per-feature readiness status from profile statistics."""
    if n_unique <= 1:
        return "poor"
    if pct_missing is not None and pct_missing > _OVERVIEW_MISSING_POOR:
        return "poor"
    if n_rows > 0 and n_unique / n_rows >= _OVERVIEW_ID_UNIQUE_RATIO:
        return "poor"
    if pct_missing is not None and pct_missing > _OVERVIEW_MISSING_WARNING:
        return "warning"
    if feat_type == "categorical" and n_unique > _OVERVIEW_HIGH_CARDINALITY:
        return "warning"
    if pct_dominant is not None and pct_dominant > _OVERVIEW_DOMINANT_WARNING:
        return "warning"
    return "good"


def _feature_summary(series, feat_type, n_unique):
    """Build a compact, type-specific summary string for one feature."""
    non_null = series.dropna()
    if len(non_null) == 0:
        return "all missing"

    if feat_type == "numerical":
        mean = non_null.mean()
        std = non_null.std()
        if pd.notna(std) and std > 0:
            return f"mean {mean:.2g}, std {std:.2g}"
        return f"min {non_null.min():.2g} – max {non_null.max():.2g}"

    if feat_type == "categorical":
        vc = non_null.value_counts(normalize=True)
        top_val = vc.index[0]
        top_pct = vc.iloc[0] * 100
        return f"{top_val} ({top_pct:.0f}%), {n_unique} categories"

    if feat_type == "datetime":
        return f"{non_null.min()} – {non_null.max()}"

    if feat_type == "boolean":
        true_pct = (non_null.astype(bool)).mean() * 100
        return f"True {true_pct:.0f}%, False {100 - true_pct:.0f}%"

    return f"{n_unique} unique values"


def _build_feature_profiles(df):
    """Compute a per-column readiness profile for every feature in *df*."""
    n_rows = len(df)
    profiles = []
    type_counts = {"numerical": 0, "categorical": 0, "datetime": 0, "boolean": 0}

    for col in df.columns:
        series = df[col]
        feat_type = _classify_feature_type(series)
        type_counts[feat_type] = type_counts.get(feat_type, 0) + 1

        n_missing = int(series.isnull().sum())
        pct_missing = round(n_missing / n_rows, 4) if n_rows else 0.0
        n_unique = int(series.nunique(dropna=True))

        pct_dominant = None
        non_null = series.dropna()
        if len(non_null) > 0:
            pct_dominant = round(
                float(non_null.value_counts(normalize=True).iloc[0]), 4
            )

        profiles.append({
            "feature": str(col),
            "type": feat_type,
            "dtype": str(series.dtype),
            "pct_missing": pct_missing,
            "n_unique": n_unique,
            "pct_dominant": pct_dominant,
            "status": _feature_readiness_status(
                pct_missing, n_unique, n_rows, feat_type, pct_dominant
            ),
            "summary": _feature_summary(series, feat_type, n_unique),
        })

    return profiles, type_counts


def _prepare_feature_profiles_for_display(
    profiles, max_profiles=_OVERVIEW_MAX_FEATURE_PROFILES
):
    """Cap profile rows for the report table, prioritizing poor then warning then good."""
    status_counts = {"poor": 0, "warning": 0, "good": 0}
    for profile in profiles:
        status = profile.get("status", "good")
        if status in status_counts:
            status_counts[status] += 1

    total = len(profiles)
    meta = {
        "total": total,
        "shown": total,
        "max": max_profiles,
        "truncated": False,
        "status_counts": status_counts,
    }
    if total <= max_profiles:
        return profiles, meta

    ranked = sorted(
        enumerate(profiles),
        key=lambda item: (
            _PROFILE_STATUS_RANK.get(item[1].get("status"), 99),
            item[0],
        ),
    )
    meta["shown"] = max_profiles
    meta["truncated"] = True
    return [profile for _, profile in ranked[:max_profiles]], meta


def _dataframe_for_overview_detail_charts(df, display_profiles):
    """Subset *df* to capped profile-table features for overview detail charts."""
    cols = [p["feature"] for p in display_profiles if p["feature"] in df.columns]
    if not cols:
        return df.iloc[:, :0]
    return df[cols]


def _build_categorical_distributions(df, top_n=_OVERVIEW_CAT_TOP_N, max_columns=None):
    """Top-*n* value counts (with percentages) for each categorical column."""
    distributions = {}
    cat_cols = [
        col for col in df.columns if _classify_feature_type(df[col]) == "categorical"
    ]
    total_cat = len(cat_cols)
    truncated = False
    if max_columns is not None and total_cat > max_columns:
        cat_cols = cat_cols[:max_columns]
        truncated = True
    for col in cat_cols:
        vc = df[col].value_counts(dropna=True)
        total = len(df[col].dropna())
        if total == 0:
            distributions[str(col)] = []
            continue
        entries = []
        for val, count in vc.head(top_n).items():
            entries.append({
                "value": str(val),
                "count": int(count),
                "pct": round(float(count) / total, 4),
            })
        distributions[str(col)] = entries
    meta = {
        "total": total_cat,
        "shown": len(cat_cols),
        "truncated": truncated,
    }
    return distributions, meta


def _build_dataset_overview_section(file_info, include_visualizations=False):
    """Build the dataset-overview portion of the readiness report.

    Returns file metadata, per-feature readiness profiles, numerical describe()
    summary, categorical top-value distributions, and numerical histograms.
    """
    file_path, file_name, file_type = file_info
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]

    n_rows = len(df)
    profiles, type_counts = _build_feature_profiles(df)
    display_profiles, profile_meta = _prepare_feature_profiles_for_display(profiles)

    file_size_bytes = None
    if file_path and os.path.exists(file_path):
        try:
            file_size_bytes = os.path.getsize(file_path)
        except OSError:
            pass

    memory_bytes = int(df.memory_usage(deep=True).sum())

    numerical_summary, numerical_summary_meta = _build_numerical_summary_for_overview(
        df.select_dtypes(include="number")
    )
    categorical_distributions, categorical_distributions_meta = (
        _build_categorical_distributions(
            df, max_columns=_OVERVIEW_MAX_CATEGORICAL_DIST_COLS
        )
    )

    overview = {
        "file_metadata": {
            "file_name": file_name,
            "file_type": file_type,
            "file_size_bytes": file_size_bytes,
            "memory_bytes": memory_bytes,
            "rows": n_rows,
            "columns": len(df.columns),
            "numerical_count": type_counts.get("numerical", 0),
            "categorical_count": type_counts.get("categorical", 0),
            "datetime_count": type_counts.get("datetime", 0),
            "boolean_count": type_counts.get("boolean", 0),
        },
        "feature_profiles": display_profiles,
        "feature_profiles_meta": profile_meta,
        "numerical_summary": numerical_summary,
        "numerical_summary_meta": numerical_summary_meta,
        "categorical_distributions": categorical_distributions,
        "categorical_distributions_meta": categorical_distributions_meta,
        "profile_thresholds": {
            "missing_warning": _OVERVIEW_MISSING_WARNING,
            "missing_poor": _OVERVIEW_MISSING_POOR,
            "dominant_warning": _OVERVIEW_DOMINANT_WARNING,
            "high_cardinality": _OVERVIEW_HIGH_CARDINALITY,
            "id_unique_ratio": _OVERVIEW_ID_UNIQUE_RATIO,
        },
        "visualizations_deferred": not include_visualizations,
    }
    if include_visualizations:
        chart_df = _dataframe_for_overview_detail_charts(df, display_profiles)
        overview["categorical_charts"] = categorical_distribution_charts(chart_df)
        overview["histograms"] = summary_histograms(chart_df, figsize=(7, 4.5))
    return overview


def _build_data_quality_section(file_info, include_visualizations=False):
    """Compute the data-quality portion of the readiness report.

    Runs completeness, outliers, and duplicity (the same functions backing the
    Data Quality tab), then derives readiness-oriented KPIs (normalized so that
    higher is always better), an overall grade, and a "needs attention" list.

    Returns a JSON-serializable dict, or ``{"error": str}`` on failure.
    """
    section = {}

    # --- Completeness -----------------------------------------------------
    compl = completeness(file_info, include_visualization=include_visualizations)
    compl_scores = compl.get("Completeness scores", {}) or {}
    overall_completeness = compl.get("Overall Completeness")

    # --- Outliers ---------------------------------------------------------
    out = outliers(file_info, include_visualization=include_visualizations)
    out_scores_raw = out.get("Outlier scores", {}) if isinstance(out, dict) else {}
    overall_outlier = None
    out_scores = {}
    if isinstance(out_scores_raw, dict):
        overall_outlier = out_scores_raw.get("Overall outlier score")
        out_scores = {
            k: v for k, v in out_scores_raw.items() if k != "Overall outlier score"
        }
    outliers_error = out.get("Error") if isinstance(out, dict) else None

    # --- Duplicity --------------------------------------------------------
    dup = duplicity(file_info)
    overall_duplicity = (
        dup.get("Duplicity scores", {}).get("Overall duplicity of the dataset")
        if isinstance(dup, dict)
        else None
    )

    # --- Normalized KPIs (higher = better) --------------------------------
    completeness_kpi = overall_completeness
    uniqueness_kpi = (1 - overall_duplicity) if overall_duplicity is not None else None
    outlier_clean_kpi = (1 - overall_outlier) if overall_outlier is not None else None

    kpis = [
        {
            "id": "completeness",
            "label": "Completeness",
            "value": completeness_kpi,
            "status": _grade_label(completeness_kpi),
            "hint": "Share of non-missing values across the dataset.",
        },
        {
            "id": "uniqueness",
            "label": "Uniqueness",
            "value": uniqueness_kpi,
            "status": _grade_label(uniqueness_kpi),
            "hint": "1 − proportion of duplicate rows.",
        },
        {
            "id": "outlier_cleanliness",
            "label": "Outlier-cleanliness",
            "value": outlier_clean_kpi,
            "status": _grade_label(outlier_clean_kpi),
            "hint": "1 − mean outlier proportion (IQR method) across numerical features.",
        },
    ]

    present = [k["value"] for k in kpis if k["value"] is not None]
    grade = sum(present) / len(present) if present else None

    # --- Needs attention --------------------------------------------------
    incomplete = sorted(
        (
            {"feature": col, "completeness": score}
            for col, score in compl_scores.items()
            if isinstance(score, (int, float)) and score < 1.0
        ),
        key=lambda x: x["completeness"],
    )
    high_outliers = sorted(
        (
            {"feature": col, "outlier_proportion": score}
            for col, score in out_scores.items()
            if isinstance(score, (int, float)) and score > 0
        ),
        key=lambda x: x["outlier_proportion"],
        reverse=True,
    )

    section = {
        "grade": grade,
        "grade_status": _grade_label(grade),
        "auto_selection": {
            "selection_criteria": {
                "analysis_scope": {
                    "rule": (
                        "Completeness, outliers, and duplicity run on the full dataset "
                        "automatically — no column selection required."
                    ),
                    "selected": "all columns",
                },
            },
        },
        "kpis": kpis,
        "needs_attention": {
            "incomplete_features": incomplete,
            "outlier_features": high_outliers,
            "duplicate_rows": (
                overall_duplicity if overall_duplicity not in (None, 0) else 0
            ),
        },
        "details": {
            "completeness": {
                "overall": overall_completeness,
                "scores": compl_scores,
                "visualization": compl.get("Completeness Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            },
            "outliers": {
                "overall": overall_outlier,
                "scores": out_scores,
                "visualization": out.get("Outliers Visualization") if include_visualizations and isinstance(out, dict) else None,
                "visualization_deferred": not include_visualizations,
                "error": outliers_error,
            },
            "duplicity": {"overall": overall_duplicity},
        },
        "visualizations_deferred": not include_visualizations,
    }
    return section


# Impact-on-AI tuning constants
_CORR_MAX_COLUMNS = 25          # cap analysed columns to keep heatmaps readable
_CORR_HIGH_CARD_MAX = 50        # drop categorical columns with more unique values
_CORR_ID_UNIQUE_RATIO = 0.9     # drop categorical columns that look like IDs
_CORR_REDUNDANT_THRESHOLD = 0.8 # |score| at/above which a pair is "redundant"
_CORR_LEAKAGE_THRESHOLD = 0.95  # |score| at/above which a pair is "leakage risk"
_CORR_ISOLATED_THRESHOLD = 0.1  # max |score| below which a feature is "isolated"


def _prune_columns_for_corr(df):
    """Select columns worth feeding into the all-pairs correlation analysis.

    Drops columns that are useless or pathological for correlation:
    constants, ID-like / high-cardinality categoricals. Numerical columns are
    always kept (they are cheap to correlate). The result is capped at
    ``_CORR_MAX_COLUMNS`` (numerical prioritized) to keep the computation and
    heatmaps tractable.

    Returns ``(kept_columns, dropped)`` where *dropped* is a list of
    ``{"feature": str, "reason": str}``.
    """
    n_rows = max(len(df), 1)
    numeric_cols = list(df.select_dtypes(exclude=["object", "string", "category"]).columns)
    categorical_cols = list(df.select_dtypes(include=["object", "string", "category"]).columns)

    kept_numeric = []
    kept_categorical = []
    dropped = []

    for col in numeric_cols:
        if df[col].nunique(dropna=True) <= 1:
            dropped.append({"feature": col, "reason": "constant column"})
        else:
            kept_numeric.append(col)

    for col in categorical_cols:
        nunique = df[col].nunique(dropna=True)
        if nunique <= 1:
            dropped.append({"feature": col, "reason": "constant column"})
        elif nunique / n_rows >= _CORR_ID_UNIQUE_RATIO:
            dropped.append({"feature": col, "reason": "ID-like (near-unique values)"})
        elif nunique > _CORR_HIGH_CARD_MAX:
            dropped.append({"feature": col, "reason": f"high cardinality ({nunique} categories)"})
        else:
            kept_categorical.append(col)

    # Cap total columns, prioritizing numerical features
    kept = kept_numeric + kept_categorical
    if len(kept) > _CORR_MAX_COLUMNS:
        for col in kept[_CORR_MAX_COLUMNS:]:
            dropped.append({"feature": col, "reason": "exceeded column cap"})
        kept = kept[:_CORR_MAX_COLUMNS]

    return kept, dropped


def _pairwise_signals(scores):
    """Derive readiness signals from a flat ``{"a vs b": score}`` mapping.

    Collapses the symmetric/asymmetric directional entries into one record per
    unordered pair (keeping the largest-magnitude score), then classifies pairs
    as redundant or leakage-risk and flags features that are not meaningfully
    related to anything else ("isolated").
    """
    pair_max = {}
    for key, val in scores.items():
        if " vs " not in key or not isinstance(val, (int, float)):
            continue
        a, b = key.split(" vs ", 1)
        if a == b:
            continue
        ukey = tuple(sorted([a, b]))
        abs_score = abs(val)
        if ukey not in pair_max or abs_score > pair_max[ukey]["abs_score"]:
            pair_max[ukey] = {
                "a": ukey[0],
                "b": ukey[1],
                "score": round(float(val), 3),
                "abs_score": abs_score,
            }

    pairs = list(pair_max.values())
    pairs.sort(key=lambda p: p["abs_score"], reverse=True)

    leakage = [
        {"a": p["a"], "b": p["b"], "score": p["score"]}
        for p in pairs
        if p["abs_score"] >= _CORR_LEAKAGE_THRESHOLD
    ]
    redundant = [
        {"a": p["a"], "b": p["b"], "score": p["score"]}
        for p in pairs
        if _CORR_REDUNDANT_THRESHOLD <= p["abs_score"] < _CORR_LEAKAGE_THRESHOLD
    ]
    top = [{"a": p["a"], "b": p["b"], "score": p["score"]} for p in pairs[:8]]

    # Per-feature connectivity: the strongest relationship each feature has
    connectivity = {}
    for p in pairs:
        connectivity[p["a"]] = max(connectivity.get(p["a"], 0.0), p["abs_score"])
        connectivity[p["b"]] = max(connectivity.get(p["b"], 0.0), p["abs_score"])
    isolated = sorted(
        f for f, c in connectivity.items() if c < _CORR_ISOLATED_THRESHOLD
    )

    return {
        "redundant": redundant,
        "leakage": leakage,
        "top": top,
        "isolated": isolated,
    }


def _build_impact_on_ai_section(file_info, include_visualizations=False):
    """Compute the Impact-on-AI portion of the readiness report.

    Runs an automated, non-interactive all-pairs correlation analysis (numerical
    via vectorized pandas correlation, categorical via Theil's U) over a pruned,
    capped set of columns, then derives redundancy / leakage / isolation signals.

    Returns a JSON-serializable dict, or ``{"error": str}`` on failure.
    """
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]

    kept, dropped = _prune_columns_for_corr(df)
    dropped_capped, dropped_meta = _cap_detail_list(
        dropped, _READINESS_MAX_DETAIL_LIST_ITEMS
    )
    if len(kept) < 2:
        return {
            "error": "Not enough usable columns for correlation analysis after pruning.",
            "columns_analyzed": len(kept),
            "columns_dropped": dropped_capped,
        }

    corr = calc_correlations(kept, file_info, include_visualization=include_visualizations)
    if isinstance(corr, dict) and "Message" in corr:
        return {"error": corr["Message"], "columns_dropped": dropped_capped}

    scores = corr.get("Correlation Scores", {}) if isinstance(corr, dict) else {}
    signals = _pairwise_signals(scores)
    cat = corr.get("Correlations Analysis Categorical", {}) or {}
    num = corr.get("Correlations Analysis Numerical", {}) or {}

    leakage_pairs = signals["leakage"]
    redundant_pairs = signals["redundant"]
    isolated_features = signals["isolated"]
    top_pairs = signals["top"]
    n_kept = len(kept)

    leakage_kpi = 1.0 if not leakage_pairs else max(0.0, 1.0 - len(leakage_pairs) / 5.0)
    redundancy_kpi = max(0.0, 1.0 - min(len(redundant_pairs) / 10.0, 1.0))
    informativeness_kpi = (
        max(0.0, 1.0 - len(isolated_features) / n_kept) if n_kept else None
    )

    kpis = [
        {
            "id": "leakage_safety",
            "label": "Leakage safety",
            "value": leakage_kpi,
            "status": "good" if not leakage_pairs else ("warning" if len(leakage_pairs) < 3 else "poor"),
            "hint": (
                f"No pairs with |score| ≥ {_CORR_LEAKAGE_THRESHOLD}; "
                f"{len(leakage_pairs)} leakage-risk pair(s) found."
            ),
            "raw_count": len(leakage_pairs),
        },
        {
            "id": "redundancy",
            "label": "Redundancy",
            "value": redundancy_kpi,
            "status": _grade_label(redundancy_kpi),
            "hint": (
                f"1 − min(redundant pairs / 10, 1); "
                f"{len(redundant_pairs)} pair(s) with |score| ≥ {_CORR_REDUNDANT_THRESHOLD}."
            ),
            "raw_count": len(redundant_pairs),
        },
        {
            "id": "informativeness",
            "label": "Informativeness",
            "value": informativeness_kpi,
            "status": _grade_label(informativeness_kpi),
            "hint": (
                f"Share of analyzed features with a strong relationship "
                f"(max |score| ≥ {_CORR_ISOLATED_THRESHOLD})."
            ),
            "raw_count": len(isolated_features),
        },
    ]

    present = [k["value"] for k in kpis if k["value"] is not None]
    grade = sum(present) / len(present) if present else None

    return {
        "grade": grade,
        "grade_status": _grade_label(grade),
        "columns_analyzed": n_kept,
        "auto_selection": {
            "columns_selected": kept,
            "selection_criteria": {
                "columns_analyzed": {
                    "rule": (
                        f"Prune constants, ID-like categoricals (unique ratio ≥ "
                        f"{_CORR_ID_UNIQUE_RATIO}), and high-cardinality categoricals "
                        f"(>{_CORR_HIGH_CARD_MAX} categories); cap at {_CORR_MAX_COLUMNS} "
                        "columns (numerical prioritized)."
                    ),
                    "selected": kept,
                    "excluded": dropped_capped,
                    "excluded_meta": dropped_meta,
                },
                "thresholds": {
                    "redundant_threshold": _CORR_REDUNDANT_THRESHOLD,
                    "leakage_threshold": _CORR_LEAKAGE_THRESHOLD,
                    "isolated_threshold": _CORR_ISOLATED_THRESHOLD,
                },
            },
        },
        "kpis": kpis,
        "needs_attention": {
            "leakage_pairs": leakage_pairs,
            "redundant_pairs": redundant_pairs,
            "isolated_features": isolated_features,
        },
        "top_pairs": top_pairs,
        "columns_dropped": dropped_capped,
        "redundant_pairs": redundant_pairs,
        "leakage_pairs": leakage_pairs,
        "isolated_features": isolated_features,
        "details": {
            "categorical_visualization": cat.get(
                "Correlations Analysis Categorical Visualization"
            ) if include_visualizations else None,
            "numerical_visualization": num.get(
                "Correlations Analysis Numerical Visualization"
            ) if include_visualizations else None,
            "numerical_method": num.get("Method"),
            "visualizations_deferred": not include_visualizations,
        },
        "visualizations_deferred": not include_visualizations,
    }


# Fairness & Bias tuning constants
_FAIRNESS_SENSITIVE_MIN_UNIQUE = 2
_FAIRNESS_SENSITIVE_MAX_UNIQUE = 30
_FAIRNESS_MAX_SENSITIVE_COLS = 5
_FAIRNESS_ID_UNIQUE_RATIO = 0.9
_FAIRNESS_TARGET_MAX_UNIQUE = 30
_FAIRNESS_REP_RATIO_FLAG = 3.0       # probability ratio at/above which representation is flagged
_FAIRNESS_MINORITY_SHARE = 0.05      # class share below which a label is "minority"
_FAIRNESS_IMBALANCE_GOOD = 0.5       # imbalance degree below this → good
_FAIRNESS_IMBALANCE_WARNING = 1.0    # below this → warning, else poor
_FAIRNESS_TSD_FLAG = 0.15            # TSD above this → outcome-rate disparity flagged
_FAIRNESS_SENSITIVE_NAME_HINTS = (
    "gender", "sex", "race", "ethnic", "age", "religion", "marital",
    "disability", "national", "origin", "minority",
)
_FAIRNESS_TARGET_NAME_HINTS = (
    "label", "target", "class", "outcome", "decision", "y", "income",
)


def _fairness_name_hint_score(col_name, hints):
    """Return a higher score when *col_name* matches an earlier hint substring."""
    lower = col_name.lower()
    best = 0
    for i, hint in enumerate(hints):
        if hint in lower:
            best = max(best, len(hints) - i)
    return best


def _auto_select_fairness_columns(df):
    """Pick sensitive attributes and a target column for automated fairness checks.

    Returns a dict with selected columns, exclusion reasons, and the
    auto-selected positive class (mode of the target) for CDD.
    """
    n_rows = max(len(df), 1)
    cat_cols = list(df.select_dtypes(include=["object", "string", "category"]).columns)

    sensitive_candidates = []
    excluded_sensitive = []

    for col in cat_cols:
        nunique = df[col].nunique(dropna=True)
        if nunique < _FAIRNESS_SENSITIVE_MIN_UNIQUE:
            excluded_sensitive.append({"feature": col, "reason": "constant column"})
        elif nunique > _FAIRNESS_SENSITIVE_MAX_UNIQUE:
            excluded_sensitive.append({
                "feature": col,
                "reason": f"high cardinality ({nunique} categories, max {_FAIRNESS_SENSITIVE_MAX_UNIQUE})",
            })
        elif nunique / n_rows >= _FAIRNESS_ID_UNIQUE_RATIO:
            excluded_sensitive.append({"feature": col, "reason": "ID-like (near-unique values)"})
        else:
            sensitive_candidates.append({
                "feature": col,
                "nunique": int(nunique),
                "name_hint_score": _fairness_name_hint_score(col, _FAIRNESS_SENSITIVE_NAME_HINTS),
            })

    sensitive_candidates.sort(
        key=lambda c: (-c["name_hint_score"], c["nunique"], c["feature"])
    )
    selected_sensitive = [c["feature"] for c in sensitive_candidates[:_FAIRNESS_MAX_SENSITIVE_COLS]]
    for c in sensitive_candidates[_FAIRNESS_MAX_SENSITIVE_COLS:]:
        excluded_sensitive.append({"feature": c["feature"], "reason": "exceeded sensitive-column cap"})

    # Target: low-cardinality columns (2–30 unique), prefer name hints; exclude sensitives
    target_candidates = []
    sensitive_set = set(selected_sensitive)
    for col in df.columns:
        if col in sensitive_set:
            continue
        nunique = df[col].nunique(dropna=True)
        if _FAIRNESS_SENSITIVE_MIN_UNIQUE <= nunique <= _FAIRNESS_TARGET_MAX_UNIQUE:
            target_candidates.append({
                "feature": col,
                "nunique": int(nunique),
                "name_hint_score": _fairness_name_hint_score(col, _FAIRNESS_TARGET_NAME_HINTS),
            })

    target_candidates.sort(
        key=lambda c: (-c["name_hint_score"], c["nunique"], c["feature"])
    )
    target_col = target_candidates[0]["feature"] if target_candidates else None
    target_reason = None
    if target_col:
        tc = target_candidates[0]
        if tc["name_hint_score"] > 0:
            target_reason = "matched target name hint"
        elif tc == target_candidates[-1] and len(target_candidates) == 1:
            target_reason = "only eligible low-cardinality column"
        else:
            target_reason = "lowest-cardinality eligible column (after name-hint priority)"

    positive_class = None
    positive_reason = None
    if target_col is not None:
        target_series = df[target_col].dropna()
        if len(target_series) > 0:
            positive_class = target_series.mode().iloc[0]
            positive_reason = "most frequent class in auto-selected target"

    primary_sensitive = selected_sensitive[0] if selected_sensitive else None

    excluded_capped, excluded_meta = _cap_detail_list(
        excluded_sensitive, _READINESS_MAX_DETAIL_LIST_ITEMS
    )

    return {
        "sensitive_columns": selected_sensitive,
        "primary_sensitive": primary_sensitive,
        "target_column": target_col,
        "positive_class": positive_class,
        "selection_criteria": {
            "sensitive_attributes": {
                "rule": (
                    f"Categorical columns with {_FAIRNESS_SENSITIVE_MIN_UNIQUE}–"
                    f"{_FAIRNESS_SENSITIVE_MAX_UNIQUE} unique values, excluding "
                    "ID-like columns; prefer name hints "
                    f"{list(_FAIRNESS_SENSITIVE_NAME_HINTS)}; "
                    f"capped at {_FAIRNESS_MAX_SENSITIVE_COLS}."
                ),
                "name_hints": list(_FAIRNESS_SENSITIVE_NAME_HINTS),
                "selected": selected_sensitive,
                "excluded": excluded_capped,
                "excluded_meta": excluded_meta,
            },
            "target_column": {
                "rule": (
                    f"Columns with {_FAIRNESS_SENSITIVE_MIN_UNIQUE}–{_FAIRNESS_TARGET_MAX_UNIQUE} "
                    "unique values, excluding auto-selected sensitive columns; "
                    "prefer name hints "
                    f"{list(_FAIRNESS_TARGET_NAME_HINTS)}."
                ),
                "name_hints": list(_FAIRNESS_TARGET_NAME_HINTS),
                "selected": target_col,
                "reason": target_reason,
            },
            "positive_class": {
                "rule": "Most frequent value in the auto-selected target (used for CDD only).",
                "selected": str(positive_class) if positive_class is not None else None,
                "reason": positive_reason,
            },
            "thresholds": {
                "representation_ratio_flag": _FAIRNESS_REP_RATIO_FLAG,
                "minority_class_share": _FAIRNESS_MINORITY_SHARE,
                "imbalance_degree_good": _FAIRNESS_IMBALANCE_GOOD,
                "imbalance_degree_warning": _FAIRNESS_IMBALANCE_WARNING,
                "tsd_disparity_flag": _FAIRNESS_TSD_FLAG,
            },
        },
    }


def _parse_representation_flags(ratios_dict):
    """Extract per-column max probability ratio and flag extreme imbalance."""
    by_column = {}
    if not isinstance(ratios_dict, dict) or "Error" in ratios_dict:
        return [], None, ratios_dict.get("Error") if isinstance(ratios_dict, dict) else None

    for key, ratio in ratios_dict.items():
        if not isinstance(ratio, (int, float)) or "Column: '" not in key:
            continue
        # Key format: Column: 'col', Probability ratio for 'A' to 'B'
        try:
            col_part = key.split("Column: '", 1)[1]
            col = col_part.split("',", 1)[0]
        except IndexError:
            continue
        entry = by_column.setdefault(col, {"column": col, "max_ratio": 0.0, "flagged_pairs": []})
        r = float(ratio)
        if r > entry["max_ratio"]:
            entry["max_ratio"] = round(r, 3)
        if r >= _FAIRNESS_REP_RATIO_FLAG:
            pair_part = key.split("Probability ratio for ", 1)[-1]
            entry["flagged_pairs"].append({"pair": pair_part, "ratio": round(r, 3)})

    summaries = sorted(by_column.values(), key=lambda x: x["max_ratio"], reverse=True)
    worst = summaries[0]["max_ratio"] if summaries else None
    rep_balance_kpi = min(1.0, 1.0 / worst) if worst and worst > 0 else None
    return summaries, rep_balance_kpi, None


def _imbalance_status(id_score):
    if id_score is None:
        return "unknown"
    if id_score < _FAIRNESS_IMBALANCE_GOOD:
        return "good"
    if id_score < _FAIRNESS_IMBALANCE_WARNING:
        return "warning"
    return "poor"


def _build_fairness_bias_section(file_info, include_visualizations=False):
    """Compute the Fairness & Bias portion of the readiness report.

    Auto-selects sensitive attributes and a target, then runs representation
    rate, class imbalance, statistical rate, and conditional demographic
    disparity using the same functions as the Fairness & Bias tab.
    """
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]

    selection = _auto_select_fairness_columns(df)
    sensitive_cols = selection["sensitive_columns"]
    target_col = selection["target_column"]
    primary_sensitive = selection["primary_sensitive"]
    positive_class = selection["positive_class"]

    kpis = []
    needs_attention = {
        "representation_imbalance": [],
        "minority_classes": [],
        "outcome_disparities": [],
        "cdd_disparities": [],
    }
    details = {}

    # --- Representation Rate (all selected sensitive columns) ---------------
    rep_error = None
    rep_balance_kpi = None
    if sensitive_cols:
        ratios = calculate_representation_rate(sensitive_cols, file_info)
        rep_summaries, rep_balance_kpi, rep_error = _parse_representation_flags(ratios)
        needs_attention["representation_imbalance"] = [
            s for s in rep_summaries if s["max_ratio"] >= _FAIRNESS_REP_RATIO_FLAG
        ]
        rep_visualizations = {}
        if include_visualizations:
            for col in sensitive_cols:
                try:
                    vis = create_representation_rate_vis([col], file_info)
                    if isinstance(vis, str):
                        rep_visualizations[col] = vis
                except Exception:
                    pass
        details["representation_rate"] = {
            "ratios": ratios if not rep_error else None,
            "summaries": rep_summaries,
            "visualizations": rep_visualizations,
            "visualizations_deferred": not include_visualizations,
            "error": rep_error,
        }
    else:
        details["representation_rate"] = {
            "error": "No eligible sensitive-attribute columns found.",
        }

    kpis.append({
        "id": "representation_balance",
        "label": "Representation balance",
        "value": rep_balance_kpi,
        "status": _grade_label(rep_balance_kpi),
        "hint": f"1 / worst group probability ratio (flagged when ratio ≥ {_FAIRNESS_REP_RATIO_FLAG}).",
    })

    # --- Class Imbalance (auto target) --------------------------------------
    imbalance_degree = None
    ci_error = None
    if target_col:
        ci_dict = _compute_class_imbalance(
            df, target_col, "EU", include_visualization=include_visualizations
        )
        if "Error" in ci_dict:
            ci_error = ci_dict["Error"]
        else:
            imb = ci_dict.get("Imbalance degree") or {}
            imbalance_degree = imb.get("Imbalance Degree score")
            details["class_imbalance"] = {
                "visualization": ci_dict.get("Class Imbalance Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
                "imbalance_degree": imbalance_degree,
            }
            # Minority classes
            vc = df[target_col].value_counts(normalize=True, dropna=True)
            for cls, share in vc.items():
                if share < _FAIRNESS_MINORITY_SHARE:
                    needs_attention["minority_classes"].append({
                        "target_column": target_col,
                        "class": str(cls),
                        "share": round(float(share), 4),
                    })
    else:
        details["class_imbalance"] = {"error": "No eligible target column found."}

    label_balance_kpi = (
        max(0.0, 1.0 - min(float(imbalance_degree) / 2.0, 1.0))
        if imbalance_degree is not None
        else None
    )
    kpis.append({
        "id": "label_balance",
        "label": "Label balance",
        "value": label_balance_kpi,
        "status": _imbalance_status(imbalance_degree),
        "hint": (
            f"Derived from Imbalance Degree (EU); 0 = balanced. "
            f"Good < {_FAIRNESS_IMBALANCE_GOOD}, warning < {_FAIRNESS_IMBALANCE_WARNING}."
        ),
        "raw_imbalance_degree": imbalance_degree,
    })

    # --- Statistical Rate (primary sensitive + target) ----------------------
    disparity_kpi = None
    if primary_sensitive and target_col:
        sr = calculate_statistical_rates(
            target_col, primary_sensitive, file_info,
            include_visualization=include_visualizations,
        )
        if isinstance(sr, dict) and "Error" in sr:
            details["statistical_rate"] = {"error": sr["Error"]}
        else:
            tsd_scores = sr.get("TSD scores") or {}
            flagged = [
                {
                    "target_column": target_col,
                    "sensitive_column": primary_sensitive,
                    "class": str(cls),
                    "tsd": round(float(score), 4),
                }
                for cls, score in tsd_scores.items()
                if isinstance(score, (int, float)) and float(score) >= _FAIRNESS_TSD_FLAG
            ]
            flagged.sort(key=lambda x: x["tsd"], reverse=True)
            needs_attention["outcome_disparities"] = flagged
            max_tsd = max(
                (float(v) for v in tsd_scores.values() if isinstance(v, (int, float))),
                default=None,
            )
            disparity_kpi = max(0.0, 1.0 - min(max_tsd, 1.0)) if max_tsd is not None else None
            details["statistical_rate"] = {
                "sensitive": primary_sensitive,
                "target": target_col,
                "tsd_scores": tsd_scores,
                "visualization": sr.get("Statistical Rate Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            }
    else:
        details["statistical_rate"] = {
            "error": "Requires both a sensitive attribute and a target column.",
        }

    kpis.append({
        "id": "outcome_parity",
        "label": "Outcome parity",
        "value": disparity_kpi,
        "status": _grade_label(disparity_kpi),
        "hint": (
            f"1 − max TSD across classes (flagged when TSD ≥ {_FAIRNESS_TSD_FLAG}). "
            "Uses primary sensitive attribute."
        ),
    })

    # --- Conditional Demographic Disparity ----------------------------------
    if primary_sensitive and target_col and positive_class is not None:
        try:
            cdd = conditional_demographic_disparity(
                df[target_col].tolist(),
                df[primary_sensitive].tolist(),
                positive_class,
            )
            if isinstance(cdd, dict) and "Error" in cdd:
                details["cdd"] = {"error": cdd["Error"]}
            else:
                disparities = (cdd or {}).get("Disparities") or {}
                cdd_flagged = [
                    {
                        "sensitive_column": primary_sensitive,
                        "target_column": target_col,
                        "positive_class": str(positive_class),
                        "group": str(grp),
                        "disparity": info.get("disparity"),
                    }
                    for grp, info in disparities.items()
                    if str(info.get("disparity", "")).lower() == "true"
                ]
                needs_attention["cdd_disparities"] = cdd_flagged
                details["cdd"] = {
                    "sensitive": primary_sensitive,
                    "target": target_col,
                    "positive_class": str(positive_class),
                    "disparities": disparities,
                }
        except Exception as e:
            details["cdd"] = {"error": str(e)}
    else:
        details["cdd"] = {
            "error": "Requires sensitive attribute, target, and auto-positive class.",
        }

    present = [k["value"] for k in kpis if k["value"] is not None]
    grade = sum(present) / len(present) if present else None

    return {
        "grade": grade,
        "grade_status": _grade_label(grade),
        "auto_selection": selection,
        "kpis": kpis,
        "needs_attention": needs_attention,
        "details": details,
        "visualizations_deferred": not include_visualizations,
    }


# ---------------------------------------------------------------------------
# Data Governance (readiness report)
# ---------------------------------------------------------------------------

_GOV_QI_MIN_UNIQUE = 2
_GOV_QI_MAX_UNIQUE = 50
_GOV_QI_MAX_COUNT = 4
_GOV_ID_UNIQUE_RATIO = 0.9
_GOV_NUMERIC_QI_MAX_UNIQUE = 20
_GOV_MM_QI_MAX_UNIQUE = 100
_GOV_MISSING_MAX = 0.20
_GOV_SENSITIVE_MIN_UNIQUE = 2
_GOV_SENSITIVE_MAX_UNIQUE = 30
_GOV_HIPAA_MAX_COLUMNS = 40
_GOV_HIPAA_MISSING_MAX = 0.50
_GOV_DP_MAX_FEATURES = 2
_GOV_DP_EPSILON = 0.1
_GOV_SMALL_SAMPLE = 30
_GOV_WORST_GROUPS_MAX = 5

_GOV_K_GOOD = 5
_GOV_K_WARNING = 2
_GOV_L_GOOD = 3
_GOV_L_WARNING = 2
_GOV_T_GOOD = 0.10
_GOV_T_WARNING = 0.20
_GOV_MM_SINGLE_GOOD = 0.3
_GOV_MM_SINGLE_WARNING = 0.6
_GOV_MM_MULTI_GOOD = 0.5
_GOV_MM_MULTI_WARNING = 0.8

_GOV_QI_NAME_HINTS = (
    "zip", "postal", "gender", "sex", "age", "race", "ethnic", "city",
    "state", "country", "birth", "dob", "county", "region", "marital",
)
_GOV_SENSITIVE_NAME_HINTS = (
    "diagnosis", "disease", "condition", "salary", "income", "religion",
    "health", "treatment", "medication", "outcome", "disability",
)
_GOV_ID_NAME_HINTS = (
    "id", "uuid", "guid", "index", "record", "patient", "user", "member",
    "row", "case",
)
_GOV_HIPAA_NAME_HINTS = (
    "name", "address", "email", "phone", "ssn", "medical", "account",
    "notes", "text", "comment",
)
_GOV_DP_NAME_HINTS = (
    "age", "income", "salary", "score", "amount", "value", "rate", "count",
    "weight", "height",
)
_GOV_HIPAA_SERIOUS_TYPES = frozenset({
    "US_SSN", "MEDICAL_IDS", "VALID_POSTAL_CODE",
})
_SYNTHETIC_ID_COL = "__aidrin_row_index__"


def _gov_name_hint_score(col_name, hints):
    return _fairness_name_hint_score(col_name, hints)


def _column_pct_missing(series, n_rows):
    if n_rows <= 0:
        return 1.0
    return float(series.isna().sum()) / n_rows


def _column_entropy_norm(series):
    """Normalized Shannon entropy of value counts in [0, 1]."""
    vc = series.dropna().value_counts(normalize=True)
    if len(vc) <= 1:
        return 0.0
    ent = -sum(p * math.log2(p) for p in vc if p > 0)
    max_ent = math.log2(len(vc))
    return ent / max_ent if max_ent > 0 else 0.0


def _k_anonymity_status(k_val):
    if k_val is None:
        return "unknown"
    if k_val >= _GOV_K_GOOD:
        return "good"
    if k_val >= _GOV_K_WARNING:
        return "warning"
    return "poor"


def _l_diversity_status(l_val):
    if l_val is None:
        return "unknown"
    if l_val >= _GOV_L_GOOD:
        return "good"
    if l_val >= _GOV_L_WARNING:
        return "warning"
    return "poor"


def _t_closeness_status(t_val):
    if t_val is None:
        return "unknown"
    if t_val <= _GOV_T_GOOD:
        return "good"
    if t_val <= _GOV_T_WARNING:
        return "warning"
    return "poor"


def _mm_risk_status(mean_risk, good=_GOV_MM_SINGLE_GOOD, warning=_GOV_MM_SINGLE_WARNING):
    if mean_risk is None:
        return "unknown"
    if mean_risk < good:
        return "good"
    if mean_risk < warning:
        return "warning"
    return "poor"


def _hipaa_status(detected_phi):
    if not detected_phi:
        return "good", 1.0
    serious = any(
        t in _GOV_HIPAA_SERIOUS_TYPES
        for info in detected_phi.values()
        for t in (info.get("potential_types_detected") or [])
    )
    if serious:
        return "poor", 0.0
    return "warning", 0.5


def _worst_equivalence_classes(df, quasi_identifiers, max_groups=_GOV_WORST_GROUPS_MAX):
    """Return the smallest equivalence classes on *quasi_identifiers*."""
    if not quasi_identifiers:
        return [], 0

    data = df.replace("?", pd.NA)
    clean = data.dropna(subset=quasi_identifiers)
    if clean.empty:
        return [], 0

    counts = clean.groupby(quasi_identifiers, dropna=False).size()
    if counts.empty:
        return [], 0

    singleton_count = int((counts == 1).sum())
    worst_groups = []
    for keys, size in counts.nsmallest(max_groups).items():
        if len(quasi_identifiers) == 1:
            key_tuple = (keys,) if not isinstance(keys, tuple) else keys
        else:
            key_tuple = keys if isinstance(keys, tuple) else (keys,)
        qi_values = {
            qi: str(val) if pd.notna(val) else "?"
            for qi, val in zip(quasi_identifiers, key_tuple)
        }
        worst_groups.append({"size": int(size), "qi_values": qi_values})

    return worst_groups, singleton_count


def _auto_select_governance_columns(df, fairness_target=None):
    """Pick columns for automated privacy and HIPAA checks in the readiness report."""
    n_rows = max(len(df), 1)
    excluded = []

    # --- Sensitive attribute (before QIs so it can be excluded) ------------
    sensitive_candidates = []
    for col in df.columns:
        feat_type = _classify_feature_type(df[col])
        if feat_type not in ("categorical", "boolean"):
            continue
        nunique = df[col].nunique(dropna=True)
        pct_miss = _column_pct_missing(df[col], n_rows)
        if nunique < _GOV_SENSITIVE_MIN_UNIQUE:
            continue
        if nunique > _GOV_SENSITIVE_MAX_UNIQUE:
            excluded.append({
                "feature": col, "role": "sensitive",
                "reason": f"high cardinality ({nunique} categories)",
            })
            continue
        if pct_miss > _GOV_MISSING_MAX:
            excluded.append({
                "feature": col, "role": "sensitive",
                "reason": f"high missingness ({pct_miss:.0%})",
            })
            continue
        hint = _gov_name_hint_score(col, _GOV_SENSITIVE_NAME_HINTS)
        fairness_boost = 1 if fairness_target and col == fairness_target else 0
        sensitive_candidates.append({
            "feature": col,
            "nunique": int(nunique),
            "name_hint_score": hint + fairness_boost,
            "entropy": _column_entropy_norm(df[col]),
        })

    sensitive_candidates.sort(
        key=lambda c: (-c["name_hint_score"], -c["entropy"], c["feature"])
    )
    sensitive_col = (
        sensitive_candidates[0]["feature"] if sensitive_candidates else None
    )

    # --- ID column -----------------------------------------------------------
    id_candidates = []
    for col in df.columns:
        if df[col].nunique(dropna=True) == n_rows and n_rows > 0:
            id_candidates.append({
                "feature": col,
                "name_hint_score": _gov_name_hint_score(col, _GOV_ID_NAME_HINTS),
            })
    id_candidates.sort(key=lambda c: (-c["name_hint_score"], c["feature"]))
    id_synthetic = not id_candidates
    id_col = id_candidates[0]["feature"] if id_candidates else _SYNTHETIC_ID_COL

    # --- Quasi-identifiers ---------------------------------------------------
    qi_candidates = []
    for col in df.columns:
        if col == sensitive_col:
            continue
        if not id_synthetic and col == id_col:
            continue
        feat_type = _classify_feature_type(df[col])
        if feat_type == "datetime":
            excluded.append({"feature": col, "role": "quasi-identifier", "reason": "datetime column"})
            continue
        nunique = df[col].nunique(dropna=True)
        pct_miss = _column_pct_missing(df[col], n_rows)
        if nunique < _GOV_QI_MIN_UNIQUE:
            excluded.append({"feature": col, "role": "quasi-identifier", "reason": "constant column"})
            continue
        if pct_miss > _GOV_MISSING_MAX:
            excluded.append({
                "feature": col, "role": "quasi-identifier",
                "reason": f"high missingness ({pct_miss:.0%})",
            })
            continue
        if nunique / n_rows >= _GOV_ID_UNIQUE_RATIO:
            excluded.append({"feature": col, "role": "quasi-identifier", "reason": "ID-like (near-unique values)"})
            continue
        if feat_type in ("categorical", "boolean"):
            if nunique > _GOV_QI_MAX_UNIQUE:
                excluded.append({
                    "feature": col, "role": "quasi-identifier",
                    "reason": f"high cardinality ({nunique} categories)",
                })
                continue
        elif feat_type == "numerical":
            if nunique > _GOV_NUMERIC_QI_MAX_UNIQUE:
                excluded.append({
                    "feature": col, "role": "quasi-identifier",
                    "reason": f"continuous numeric ({nunique} unique values)",
                })
                continue
        else:
            excluded.append({"feature": col, "role": "quasi-identifier", "reason": f"unsupported type ({feat_type})"})
            continue

        qi_candidates.append({
            "feature": col,
            "nunique": int(nunique),
            "feat_type": feat_type,
            "name_hint_score": _gov_name_hint_score(col, _GOV_QI_NAME_HINTS),
        })

    qi_candidates.sort(
        key=lambda c: (-c["name_hint_score"], c["nunique"], c["feature"])
    )
    quasi_identifiers = [c["feature"] for c in qi_candidates[:_GOV_QI_MAX_COUNT]]
    for c in qi_candidates[_GOV_QI_MAX_COUNT:]:
        excluded.append({"feature": c["feature"], "role": "quasi-identifier", "reason": "exceeded QI cap"})

    mm_quasi_identifiers = [
        c["feature"] for c in qi_candidates[:_GOV_QI_MAX_COUNT]
        if c["feat_type"] in ("categorical", "boolean")
        and c["nunique"] <= _GOV_MM_QI_MAX_UNIQUE
    ]

    # --- HIPAA scan columns --------------------------------------------------
    hipaa_candidates = []
    for col in df.columns:
        nunique = df[col].nunique(dropna=True)
        if nunique <= 1:
            continue
        pct_miss = _column_pct_missing(df[col], n_rows)
        feat_type = _classify_feature_type(df[col])
        is_text = feat_type in ("categorical",) or str(df[col].dtype) in ("object", "string")
        if is_text and pct_miss <= _GOV_HIPAA_MISSING_MAX:
            avg_len = df[col].dropna().astype(str).str.len().mean()
            hipaa_candidates.append({
                "feature": col,
                "name_hint_score": _gov_name_hint_score(col, _GOV_HIPAA_NAME_HINTS),
                "avg_len": avg_len if pd.notna(avg_len) else 0,
            })

    hipaa_candidates.sort(
        key=lambda c: (-c["name_hint_score"], -c["avg_len"], c["feature"])
    )
    hipaa_scan_columns = [c["feature"] for c in hipaa_candidates[:_GOV_HIPAA_MAX_COLUMNS]]
    if not hipaa_scan_columns:
        hipaa_scan_columns = [
            col for col in df.columns if df[col].nunique(dropna=True) > 1
        ][: _GOV_HIPAA_MAX_COLUMNS]

    # --- DP numerical features -----------------------------------------------
    dp_candidates = []
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        nunique = df[col].nunique(dropna=True)
        if nunique <= 1:
            continue
        if nunique / n_rows >= _GOV_ID_UNIQUE_RATIO:
            continue
        if _column_pct_missing(df[col], n_rows) > _GOV_MISSING_MAX:
            continue
        dp_candidates.append({
            "feature": col,
            "name_hint_score": _gov_name_hint_score(col, _GOV_DP_NAME_HINTS),
            "pct_missing": _column_pct_missing(df[col], n_rows),
            "nunique": int(nunique),
        })
    dp_candidates.sort(
        key=lambda c: (-c["name_hint_score"], c["pct_missing"], c["nunique"], c["feature"])
    )
    dp_features = [c["feature"] for c in dp_candidates[:_GOV_DP_MAX_FEATURES]]

    qi_excluded_raw = [e for e in excluded if e["role"] == "quasi-identifier"]
    sens_excluded_raw = [e for e in excluded if e["role"] == "sensitive"]
    qi_excluded, qi_excluded_meta = _cap_detail_list(
        qi_excluded_raw, _READINESS_MAX_DETAIL_LIST_ITEMS
    )
    sens_excluded, sens_excluded_meta = _cap_detail_list(
        sens_excluded_raw, _READINESS_MAX_DETAIL_LIST_ITEMS
    )

    return {
        "quasi_identifiers": quasi_identifiers,
        "mm_quasi_identifiers": mm_quasi_identifiers,
        "sensitive_attribute": sensitive_col,
        "id_column": id_col,
        "id_synthetic": id_synthetic,
        "hipaa_scan_columns": hipaa_scan_columns,
        "dp_features": dp_features,
        "dp_epsilon": _GOV_DP_EPSILON,
        "selection_criteria": {
            "quasi_identifiers": {
                "rule": (
                    f"Categorical/boolean with {_GOV_QI_MIN_UNIQUE}–{_GOV_QI_MAX_UNIQUE} "
                    f"unique values; discrete numeric with {_GOV_QI_MIN_UNIQUE}–"
                    f"{_GOV_NUMERIC_QI_MAX_UNIQUE}; exclude ID-like, datetime, "
                    f"and >{_GOV_MISSING_MAX:.0%} missing; prefer name hints; "
                    f"capped at {_GOV_QI_MAX_COUNT}."
                ),
                "name_hints": list(_GOV_QI_NAME_HINTS),
                "selected": quasi_identifiers,
                "excluded": qi_excluded,
                "excluded_meta": qi_excluded_meta,
            },
            "sensitive_attribute": {
                "rule": (
                    f"Categorical/boolean with {_GOV_SENSITIVE_MIN_UNIQUE}–"
                    f"{_GOV_SENSITIVE_MAX_UNIQUE} unique values, excluding QIs; "
                    "prefer sensitive name hints and fairness target when eligible."
                ),
                "name_hints": list(_GOV_SENSITIVE_NAME_HINTS),
                "selected": sensitive_col,
                "excluded": sens_excluded,
                "excluded_meta": sens_excluded_meta,
            },
            "id_column": {
                "rule": (
                    "Exact-unique column preferred (name hints: id, uuid, patient, …); "
                    "otherwise synthetic row index for linkage-risk scoring only."
                ),
                "selected": id_col,
                "synthetic": id_synthetic,
            },
            "hipaa_scan_columns": {
                "rule": (
                    f"Text-like columns up to {_GOV_HIPAA_MAX_COLUMNS}, prefer HIPAA "
                    "name hints; fallback to all non-constant columns."
                ),
                "name_hints": list(_GOV_HIPAA_NAME_HINTS),
                "selected": hipaa_scan_columns,
            },
            "dp_features": {
                "rule": (
                    f"Up to {_GOV_DP_MAX_FEATURES} numerical, non-ID-like columns "
                    f"(illustrative only, ε={_GOV_DP_EPSILON})."
                ),
                "selected": dp_features,
                "epsilon": _GOV_DP_EPSILON,
            },
            "thresholds": {
                "k_good": _GOV_K_GOOD,
                "k_warning": _GOV_K_WARNING,
                "l_good": _GOV_L_GOOD,
                "l_warning": _GOV_L_WARNING,
                "t_good": _GOV_T_GOOD,
                "t_warning": _GOV_T_WARNING,
                "mm_single_good": _GOV_MM_SINGLE_GOOD,
                "mm_single_warning": _GOV_MM_SINGLE_WARNING,
                "mm_multi_good": _GOV_MM_MULTI_GOOD,
                "mm_multi_warning": _GOV_MM_MULTI_WARNING,
                "small_sample_rows": _GOV_SMALL_SAMPLE,
            },
        },
    }


def _build_data_governance_section(file_info, include_visualizations=False):
    """Compute the Data Governance portion of the readiness report."""
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]

    n_rows = len(df)
    fairness_sel = _auto_select_fairness_columns(df)
    selection = _auto_select_governance_columns(
        df, fairness_target=fairness_sel.get("target_column")
    )
    qi = selection["quasi_identifiers"]
    mm_qis = selection["mm_quasi_identifiers"]
    sensitive = selection["sensitive_attribute"]
    id_col = selection["id_column"]
    id_synthetic = selection["id_synthetic"]

    work_df = df.copy()
    if id_synthetic:
        work_df[_SYNTHETIC_ID_COL] = range(len(work_df))
        id_col = _SYNTHETIC_ID_COL

    kpis = []
    needs_attention = {
        "low_anonymity": [],
        "hipaa_phi": [],
        "high_linkage_risk": [],
        "attribute_disclosure": [],
    }
    details = {}
    small_sample = n_rows < _GOV_SMALL_SAMPLE

    # --- k-Anonymity ---------------------------------------------------------
    k_val = None
    if qi:
        k_res = compute_k_anonymity(qi, work_df, include_visualization=include_visualizations)
        if "Error" not in k_res:
            k_val = k_res.get("k-Value")
            if k_val is not None and k_val < _GOV_K_WARNING:
                worst_groups, singleton_count = _worst_equivalence_classes(work_df, qi)
                needs_attention["low_anonymity"].append({
                    "metric": "k-Anonymity",
                    "value": k_val,
                    "quasi_identifiers": list(qi),
                    "singleton_count": singleton_count,
                    "worst_groups": worst_groups,
                    "detail": (
                        f"Minimum group size {k_val} on quasi-identifiers: "
                        f"{', '.join(qi)}"
                    ),
                })
            details["k_anonymity"] = {
                "quasi_identifiers": qi,
                "k_value": k_val,
                "descriptive_statistics": k_res.get("descriptive_statistics"),
                "visualization": k_res.get("k-Anonymity Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            }
        else:
            details["k_anonymity"] = {"error": k_res.get("Error")}
    else:
        details["k_anonymity"] = {"error": "No eligible quasi-identifier columns found."}

    k_kpi = min(float(k_val) / _GOV_K_GOOD, 1.0) if k_val is not None else None
    kpis.append({
        "id": "anonymity_k",
        "label": "Anonymity (k)",
        "value": k_kpi,
        "status": _k_anonymity_status(k_val),
        "hint": f"k-Value ≥ {_GOV_K_GOOD} good, ≥ {_GOV_K_WARNING} warning (min group size on auto QIs).",
        "raw_k": k_val,
    })

    # --- l-Diversity ---------------------------------------------------------
    l_val = None
    if qi and sensitive:
        l_res = compute_l_diversity(qi, sensitive, work_df, include_visualization=include_visualizations)
        if "Error" not in l_res:
            l_val = l_res.get("l-Value")
            if l_val is not None and l_val < _GOV_L_WARNING:
                needs_attention["attribute_disclosure"].append({
                    "metric": "l-Diversity",
                    "value": l_val,
                    "sensitive_attribute": sensitive,
                    "quasi_identifiers": list(qi),
                    "detail": (
                        f"Sensitive '{sensitive}' has only {l_val} distinct value(s) "
                        f"in some groups defined by ({', '.join(qi)})"
                    ),
                })
            details["l_diversity"] = {
                "quasi_identifiers": qi,
                "sensitive_attribute": sensitive,
                "l_value": l_val,
                "descriptive_statistics": l_res.get("descriptive_statistics"),
                "visualization": l_res.get("l-Diversity Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            }
        else:
            details["l_diversity"] = {"error": l_res.get("Error")}
    else:
        details["l_diversity"] = {
            "error": "Requires quasi-identifiers and a sensitive attribute.",
        }

    l_kpi = min(float(l_val) / _GOV_L_GOOD, 1.0) if l_val is not None else None
    kpis.append({
        "id": "diversity_l",
        "label": "Attribute diversity (l)",
        "value": l_kpi,
        "status": _l_diversity_status(l_val),
        "hint": f"l-Value ≥ {_GOV_L_GOOD} good, ≥ {_GOV_L_WARNING} warning (min distinct sensitive values per QI group).",
        "raw_l": l_val,
    })

    # --- t-Closeness ---------------------------------------------------------
    t_val = None
    if qi and sensitive:
        t_res = compute_t_closeness(qi, sensitive, work_df, include_visualization=include_visualizations)
        if "Error" not in t_res:
            t_val = t_res.get("t-Value")
            if t_val is not None and t_val > _GOV_T_WARNING:
                needs_attention["attribute_disclosure"].append({
                    "metric": "t-Closeness",
                    "value": t_val,
                    "sensitive_attribute": sensitive,
                    "quasi_identifiers": list(qi),
                    "detail": (
                        f"Distribution of '{sensitive}' diverges from global "
                        f"(max TVD {t_val}) within groups of ({', '.join(qi)})"
                    ),
                })
            details["t_closeness"] = {
                "quasi_identifiers": qi,
                "sensitive_attribute": sensitive,
                "t_value": t_val,
                "descriptive_statistics": t_res.get("descriptive_statistics"),
                "visualization": t_res.get("t-Closeness Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            }
        else:
            details["t_closeness"] = {"error": t_res.get("Error")}
    else:
        details["t_closeness"] = {
            "error": "Requires quasi-identifiers and a sensitive attribute.",
        }

    t_kpi = max(0.0, 1.0 - float(t_val) / _GOV_T_WARNING) if t_val is not None else None
    kpis.append({
        "id": "distribution_t",
        "label": "Distribution leakage (t)",
        "value": t_kpi,
        "status": _t_closeness_status(t_val),
        "hint": f"Max TVD ≤ {_GOV_T_GOOD} good, ≤ {_GOV_T_WARNING} warning (lower is better).",
        "raw_t": t_val,
    })

    # --- Entropy risk --------------------------------------------------------
    if qi:
        e_res = compute_entropy_risk(qi, work_df, include_visualization=include_visualizations)
        if "Error" not in e_res:
            details["entropy_risk"] = {
                "quasi_identifiers": qi,
                "entropy_value": e_res.get("Entropy-Value"),
                "descriptive_statistics": e_res.get("descriptive_statistics"),
                "visualization": e_res.get("Entropy Risk Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            }
        else:
            details["entropy_risk"] = {"error": e_res.get("Error")}
    else:
        details["entropy_risk"] = {"error": "No eligible quasi-identifier columns found."}

    # --- Single-attribute MM risk ----------------------------------------------
    worst_single_mean = None
    single_by_qi = {}
    if mm_qis:
        for q in mm_qis:
            try:
                s_res = generate_single_attribute_MM_risk_scores_groupby(
                    work_df, id_col, [q], include_visualization=include_visualizations
                )
                if "Error" in s_res:
                    single_by_qi[q] = {"error": s_res["Error"]}
                    continue
                stats = (s_res.get("Descriptive statistics of the risk scores") or {}).get(q, {})
                mean_risk = stats.get("mean")
                if mean_risk is not None:
                    mean_risk = float(mean_risk)
                    single_by_qi[q] = {"mean_risk": round(mean_risk, 4), "stats": stats}
                    if worst_single_mean is None or mean_risk > worst_single_mean:
                        worst_single_mean = mean_risk
                    if mean_risk >= _GOV_MM_SINGLE_WARNING:
                        needs_attention["high_linkage_risk"].append({
                            "metric": "Single-attribute risk",
                            "feature": q,
                            "quasi_identifiers": [q],
                            "mean_risk": round(mean_risk, 4),
                            "detail": f"Quasi-identifier '{q}' — mean MM risk {mean_risk:.2f}",
                        })
            except Exception as exc:
                single_by_qi[q] = {"error": str(exc)}
        details["single_attribute_risk"] = {
            "id_column": id_col,
            "by_quasi_identifier": single_by_qi,
        }
        if needs_attention["low_anonymity"] and single_by_qi:
            worst_qi = None
            for q, info in single_by_qi.items():
                mr = info.get("mean_risk")
                if mr is not None and (worst_qi is None or mr > worst_qi[1]):
                    worst_qi = (q, mr)
            if worst_qi:
                needs_attention["low_anonymity"][0]["worst_single_qi"] = {
                    "feature": worst_qi[0],
                    "mean_risk": worst_qi[1],
                }
    else:
        details["single_attribute_risk"] = {
            "error": "No categorical quasi-identifiers eligible for MM risk scoring.",
        }

    single_kpi = (
        max(0.0, 1.0 - worst_single_mean) if worst_single_mean is not None else None
    )
    kpis.append({
        "id": "single_linkage_risk",
        "label": "Worst single-field risk",
        "value": single_kpi,
        "status": _mm_risk_status(worst_single_mean),
        "hint": (
            f"1 − worst mean MM risk across QIs; good < {_GOV_MM_SINGLE_GOOD}, "
            f"warning < {_GOV_MM_SINGLE_WARNING}."
        ),
        "raw_worst_mean": round(worst_single_mean, 4) if worst_single_mean is not None else None,
    })

    # --- Multiple-attribute MM risk ------------------------------------------
    multi_mean = None
    if mm_qis:
        try:
            m_res = generate_multiple_attribute_MM_risk_scores_groupby(
                work_df, id_col, mm_qis, include_visualization=include_visualizations
            )
            if "Error" not in m_res:
                m_stats = m_res.get("Descriptive statistics of the risk scores") or {}
                multi_mean = m_stats.get("mean")
                if multi_mean is not None:
                    multi_mean = float(multi_mean)
                    if multi_mean >= _GOV_MM_MULTI_WARNING:
                        needs_attention["high_linkage_risk"].append({
                            "metric": "Multiple-attribute risk",
                            "features": list(mm_qis),
                            "quasi_identifiers": list(mm_qis),
                            "mean_risk": round(multi_mean, 4),
                            "detail": (
                                f"Combined QIs ({', '.join(mm_qis)}) — "
                                f"mean MM risk {multi_mean:.2f}"
                            ),
                        })
                details["multiple_attribute_risk"] = {
                    "id_column": id_col,
                    "quasi_identifiers": mm_qis,
                    "mean_risk": round(multi_mean, 4) if multi_mean is not None else None,
                    "dataset_risk_score": m_res.get("Dataset Risk Score"),
                    "stats": m_stats,
                    "visualization": m_res.get("Multiple attribute risk scoring Visualization") if include_visualizations else None,
                    "visualization_deferred": not include_visualizations,
                }
            else:
                details["multiple_attribute_risk"] = {"error": m_res.get("Error")}
        except Exception as exc:
            details["multiple_attribute_risk"] = {"error": str(exc)}
    else:
        details["multiple_attribute_risk"] = {
            "error": "No categorical quasi-identifiers eligible for combined MM risk.",
        }

    multi_kpi = max(0.0, 1.0 - multi_mean) if multi_mean is not None else None
    kpis.append({
        "id": "linkage_risk",
        "label": "Combined linkage risk",
        "value": multi_kpi,
        "status": _mm_risk_status(
            multi_mean, good=_GOV_MM_MULTI_GOOD, warning=_GOV_MM_MULTI_WARNING
        ),
        "hint": (
            f"1 − mean MM risk on combined QIs; good < {_GOV_MM_MULTI_GOOD}, "
            f"warning < {_GOV_MM_MULTI_WARNING}."
        ),
        "raw_mean": round(multi_mean, 4) if multi_mean is not None else None,
    })

    # --- HIPAA ---------------------------------------------------------------
    hipaa_cols = selection["hipaa_scan_columns"]
    detected_phi = {}
    if hipaa_cols:
        detected_phi = detect_hipaa_identifiers(work_df, hipaa_cols)
        for col, info in detected_phi.items():
            types = info.get("potential_types_detected") or []
            serious = [t for t in types if t in _GOV_HIPAA_SERIOUS_TYPES]
            needs_attention["hipaa_phi"].append({
                "column": col,
                "total_flags": info.get("total_flags", 0),
                "types": types,
                "serious": bool(serious),
                "examples": info.get("examples") or [],
            })
        details["hipaa"] = {
            "columns_scanned": hipaa_cols,
            "detected": detected_phi,
        }
    else:
        details["hipaa"] = {"error": "No columns available to scan."}

    hipaa_status, hipaa_kpi = _hipaa_status(detected_phi)
    kpis.append({
        "id": "phi_exposure",
        "label": "PHI exposure",
        "value": hipaa_kpi,
        "status": hipaa_status,
        "hint": "Pattern scan for HIPAA-like identifiers (SSN, medical IDs, postal codes, etc.). Not full Safe Harbor certification.",
        "columns_flagged": len(detected_phi),
    })

    # --- Differential privacy (illustrative) -----------------------------------
    dp_features = selection["dp_features"]
    if dp_features:
        try:
            dp_res = return_noisy_stats(
                dp_features, _GOV_DP_EPSILON, work_df,
                save_output=False, include_visualization=include_visualizations,
            )
            if "Error" not in dp_res:
                details["differential_privacy"] = {
                    "features": dp_features,
                    "epsilon": _GOV_DP_EPSILON,
                    "illustrative": True,
                    "visualization": dp_res.get("DP Statistics Visualization") if include_visualizations else None,
                    "visualization_deferred": not include_visualizations,
                    "summary": {
                        k: v for k, v in dp_res.items()
                        if k.endswith("(before noise)") or k.endswith("(after noise)")
                    },
                }
            else:
                details["differential_privacy"] = {"error": dp_res.get("Error")}
        except Exception as exc:
            details["differential_privacy"] = {"error": str(exc)}
    else:
        details["differential_privacy"] = {
            "error": "No eligible numerical columns for illustrative DP demo.",
        }

    grade_kpis = [k for k in kpis if k["value"] is not None]
    grade = sum(k["value"] for k in grade_kpis) / len(grade_kpis) if grade_kpis else None

    return {
        "grade": grade,
        "grade_status": _grade_label(grade),
        "small_sample_warning": small_sample,
        "auto_selection": selection,
        "kpis": kpis,
        "needs_attention": needs_attention,
        "details": details,
        "visualizations_deferred": not include_visualizations,
    }


def _build_dataset_overview_visualizations(file_info):
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]
    profiles, _ = _build_feature_profiles(df)
    display_profiles, _ = _prepare_feature_profiles_for_display(profiles)
    chart_df = _dataframe_for_overview_detail_charts(df, display_profiles)
    return {
        "categorical_charts": categorical_distribution_charts(chart_df),
        "histograms": summary_histograms(chart_df, figsize=(7, 4.5)),
    }


def _build_data_quality_visualizations(file_info):
    compl = completeness(file_info, include_visualization=True)
    out = outliers(file_info, include_visualization=True)
    viz = {}
    if compl.get("Completeness Visualization"):
        viz["completeness"] = compl["Completeness Visualization"]
    if isinstance(out, dict) and out.get("Outliers Visualization"):
        viz["outliers"] = out["Outliers Visualization"]
    return viz


def _build_impact_on_ai_visualizations(file_info):
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]
    kept, _ = _prune_columns_for_corr(df)
    if len(kept) < 2:
        return {}
    corr = calc_correlations(kept, file_info, include_visualization=True)
    if isinstance(corr, dict) and "Message" in corr:
        return {}
    cat = corr.get("Correlations Analysis Categorical", {}) or {}
    num = corr.get("Correlations Analysis Numerical", {}) or {}
    viz = {}
    cat_img = cat.get("Correlations Analysis Categorical Visualization")
    num_img = num.get("Correlations Analysis Numerical Visualization")
    if cat_img:
        viz["categorical_correlation"] = cat_img
    if num_img:
        viz["numerical_correlation"] = num_img
    return viz


def _build_fairness_bias_visualizations(file_info):
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]
    selection = _auto_select_fairness_columns(df)
    sensitive_cols = selection["sensitive_columns"]
    target_col = selection["target_column"]
    primary_sensitive = selection["primary_sensitive"]
    viz = {}
    for col in sensitive_cols:
        try:
            vis = create_representation_rate_vis([col], file_info)
            if isinstance(vis, str):
                viz[f"representation_rate.{col}"] = vis
        except Exception:
            pass
    if target_col:
        ci_dict = _compute_class_imbalance(df, target_col, "EU", include_visualization=True)
        img = ci_dict.get("Class Imbalance Visualization")
        if img:
            viz["class_imbalance"] = img
    if primary_sensitive and target_col:
        sr = calculate_statistical_rates(
            target_col, primary_sensitive, file_info, include_visualization=True,
        )
        if isinstance(sr, dict) and sr.get("Statistical Rate Visualization"):
            viz["statistical_rate"] = sr["Statistical Rate Visualization"]
    return viz


def _build_data_governance_visualizations(file_info):
    """Build only chart payloads for governance (metrics already computed on initial load)."""
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]

    fairness_sel = _auto_select_fairness_columns(df)
    selection = _auto_select_governance_columns(
        df, fairness_target=fairness_sel.get("target_column")
    )
    qi = selection["quasi_identifiers"]
    mm_qis = selection["mm_quasi_identifiers"]
    sensitive = selection["sensitive_attribute"]
    id_col = selection["id_column"]
    id_synthetic = selection["id_synthetic"]
    dp_features = selection["dp_features"]

    work_df = df.copy()
    if id_synthetic:
        work_df[_SYNTHETIC_ID_COL] = range(len(work_df))
        id_col = _SYNTHETIC_ID_COL

    viz = {}
    if qi:
        k_res = compute_k_anonymity(qi, work_df, include_visualization=True)
        img = k_res.get("k-Anonymity Visualization")
        if img:
            viz["k_anonymity"] = img
        e_res = compute_entropy_risk(qi, work_df, include_visualization=True)
        img = e_res.get("Entropy Risk Visualization")
        if img:
            viz["entropy_risk"] = img
    if qi and sensitive:
        l_res = compute_l_diversity(qi, sensitive, work_df, include_visualization=True)
        img = l_res.get("l-Diversity Visualization")
        if img:
            viz["l_diversity"] = img
        t_res = compute_t_closeness(qi, sensitive, work_df, include_visualization=True)
        img = t_res.get("t-Closeness Visualization")
        if img:
            viz["t_closeness"] = img
    if mm_qis:
        m_res = generate_multiple_attribute_MM_risk_scores_groupby(
            work_df, id_col, mm_qis, include_visualization=True
        )
        img = m_res.get("Multiple attribute risk scoring Visualization")
        if img:
            viz["multiple_attribute_risk"] = img
    if dp_features:
        try:
            dp_res = return_noisy_stats(
                dp_features, _GOV_DP_EPSILON, work_df,
                save_output=False, include_visualization=True,
            )
            img = dp_res.get("DP Statistics Visualization")
            if img:
                viz["differential_privacy"] = img
        except Exception:
            pass
    return viz


_READINESS_VIZ_BUILDERS = {
    "dataset-overview": _build_dataset_overview_visualizations,
    "data-quality": _build_data_quality_visualizations,
    "impact-on-ai": _build_impact_on_ai_visualizations,
    "fairness-bias": _build_fairness_bias_visualizations,
    "data-governance": _build_data_governance_visualizations,
}


_READINESS_SECTION_BUILDERS = {
    "dataset-overview": _build_dataset_overview_section,
    "data-quality": _build_data_quality_section,
    "impact-on-ai": _build_impact_on_ai_section,
    "fairness-bias": _build_fairness_bias_section,
    "data-governance": _build_data_governance_section,
}

_READINESS_SECTION_RESPONSE_KEYS = {
    "dataset-overview": "dataset_overview",
    "data-quality": "data_quality",
    "impact-on-ai": "impact_on_ai",
    "fairness-bias": "fairness_bias",
    "data-governance": "data_governance",
}

_READINESS_CACHE_TTL_SECONDS = 30 * 60


def _readiness_section_cache_key(file_name, section, *, viz=False):
    """User/file-scoped cache key (same colon pattern as ``/cached-result``)."""
    user_id = get_current_user_id()
    if viz:
        return f"user:{user_id}:file:{file_name}:readiness_report:{section}:visualizations"
    return f"user:{user_id}:file:{file_name}:readiness_report:{section}"


def _get_cached_readiness_payload(file_name, section, *, viz=False):
    """Return cached section or visualization payload, or *(None, None)*."""
    key = _readiness_section_cache_key(file_name, section, viz=viz)
    entry = current_app.TEMP_RESULTS_CACHE.get(key)
    if entry and is_metric_cache_valid(entry):
        return entry.get("data"), entry.get("build_time_seconds")
    if entry:
        current_app.TEMP_RESULTS_CACHE.pop(key, None)
    return None, None


def _cache_readiness_payload(file_name, section, data, build_time_seconds, *, viz=False):
    """Store a successful readiness section or visualization payload."""
    if data is None:
        return
    if not viz and isinstance(data, dict) and data.get("error"):
        return
    key = _readiness_section_cache_key(file_name, section, viz=viz)
    current_app.TEMP_RESULTS_CACHE[key] = {
        "data": ensure_json_serializable(data),
        "timestamp": time.time(),
        "expires_at": time.time() + _READINESS_CACHE_TTL_SECONDS,
        "build_time_seconds": build_time_seconds,
    }


def _get_or_build_readiness_section(section, file_info, include_visualizations=False):
    """Return section data from cache or build, store on miss."""
    file_name = file_info[1]
    cached, build_time = _get_cached_readiness_payload(file_name, section)
    if cached is not None:
        metric_time_log.info("Readiness report section %s cache hit", section)
        return cached, build_time, True

    start_time = time.time()
    data = _build_readiness_section(
        section, file_info, include_visualizations=include_visualizations
    )
    build_time_seconds = round(time.time() - start_time, 2)
    _cache_readiness_payload(file_name, section, data, build_time_seconds)
    return data, build_time_seconds, False


def get_cached_readiness_report(file_name):
    """Return all cached readiness sections for ``/cached-result/readiness_report``.

    Returns a JSON-serializable dict when every section is cached, else *None*.
    Optionally includes ``fair_compliance`` when a readiness FAIR result is cached.
    """
    sections = {}
    sections_cached = {}
    for slug in _READINESS_SECTION_BUILDERS:
        cached, build_time = _get_cached_readiness_payload(file_name, slug)
        if cached is None:
            return None
        sections[slug] = {**cached, "build_time_seconds": build_time}
        sections_cached[slug] = True
    payload = {
        "cached": True,
        "sections": sections,
        "sections_cached": sections_cached,
    }
    fair_compliance = _get_cached_readiness_fair_compliance(file_name)
    if fair_compliance is not None:
        payload["fair_compliance"] = fair_compliance
    return payload


def _readiness_fair_cache_key(file_name):
    """Cache key for optional readiness-report FAIR compliance."""
    user_id = get_current_user_id()
    return f"user:{user_id}:file:{file_name}:readiness_report:fair"


def _fair_metadata_fingerprint(json_bytes, metadata_type):
    """Stable fingerprint for readiness FAIR cache invalidation."""
    digest = hashlib.sha256()
    digest.update(json_bytes)
    digest.update(b"|")
    digest.update(metadata_type.encode("utf-8"))
    return digest.hexdigest()


def _get_cached_readiness_fair_compliance(file_name):
    """Return cached readiness FAIR payload metadata, or *None*."""
    key = _readiness_fair_cache_key(file_name)
    entry = current_app.TEMP_RESULTS_CACHE.get(key)
    if entry and is_metric_cache_valid(entry):
        data = entry.get("data")
        if data is None or (isinstance(data, dict) and data.get("error")):
            return None
        return {
            "data": data,
            "metadata_type": entry.get("metadata_type"),
            "metadata_filename": entry.get("metadata_filename"),
            "metadata_fingerprint": entry.get("metadata_fingerprint"),
            "build_time_seconds": entry.get("build_time_seconds"),
            "cached": True,
        }
    if entry:
        current_app.TEMP_RESULTS_CACHE.pop(key, None)
    return None


def get_cached_readiness_fair_report(file_name):
    """Return readiness FAIR cache for ``/cached-result/readiness_report_fair``."""
    fair_compliance = _get_cached_readiness_fair_compliance(file_name)
    if fair_compliance is None:
        return None
    return {"cached": True, "fair_compliance": fair_compliance}


def _cache_readiness_fair_compliance(
    file_name,
    data,
    *,
    metadata_type,
    metadata_filename,
    metadata_fingerprint,
    build_time_seconds,
):
    """Store a successful readiness-report FAIR assessment."""
    if data is None or (isinstance(data, dict) and data.get("error")):
        return
    key = _readiness_fair_cache_key(file_name)
    current_app.TEMP_RESULTS_CACHE[key] = {
        "data": ensure_json_serializable(data),
        "timestamp": time.time(),
        "expires_at": time.time() + _READINESS_CACHE_TTL_SECONDS,
        "build_time_seconds": build_time_seconds,
        "metadata_type": metadata_type,
        "metadata_filename": metadata_filename,
        "metadata_fingerprint": metadata_fingerprint,
    }


def _run_fair_assessment(data_dict, metadata_type):
    """Run FAIR assessment for DCAT or Datacite metadata."""
    if metadata_type == "DCAT":
        extracted_json = extract_keys_and_values(data_dict)
        fair_dict = categorize_metadata(extracted_json, data_dict)
        return format_dict_values(fair_dict)
    if metadata_type == "Datacite":
        return categorize_keys_fair(data_dict)
    raise ValueError("Unknown metadata type")


def _get_or_build_readiness_visualizations(section, file_info):
    """Return visualization payload from cache or build, store on miss."""
    file_name = file_info[1]
    cached, build_time = _get_cached_readiness_payload(
        file_name, section, viz=True
    )
    if cached is not None:
        metric_time_log.info(
            "Readiness report section %s visualizations cache hit", section
        )
        return cached, build_time, True

    builder = _READINESS_VIZ_BUILDERS.get(section)
    start_time = time.time()
    visualizations = builder(file_info) if builder else {}
    build_time_seconds = round(time.time() - start_time, 2)
    _cache_readiness_payload(
        file_name, section, visualizations, build_time_seconds, viz=True
    )
    return visualizations, build_time_seconds, False


def _readiness_file_info():
    """Return ``(file_path, file_name, file_type)`` from session, or *None*."""
    file_path = session.get("uploaded_file_path")
    if not file_path:
        return None
    return (
        file_path,
        session.get("uploaded_file_name"),
        session.get("uploaded_file_type"),
    )


def _build_readiness_section(section, file_info, include_visualizations=False):
    """Build one readiness-report section; return error dict on failure."""
    builder = _READINESS_SECTION_BUILDERS.get(section)
    if builder is None:
        return None
    try:
        return builder(file_info, include_visualizations=include_visualizations)
    except Exception as e:
        metric_time_log.error(
            "Readiness report — %s error: %s", section, e, exc_info=True
        )
        return {"error": f"{type(e).__name__}: {e}"}


@metrics_bp.route("/readiness-report/<section>/visualizations", methods=["GET"])
def readiness_report_visualizations(section):
    """Return on-demand chart images for a readiness-report section."""
    if section not in _READINESS_VIZ_BUILDERS:
        return jsonify({"success": False, "message": f"Unknown section: {section}"}), 404

    file_info = _readiness_file_info()
    if file_info is None:
        return jsonify({"success": False, "message": "No file uploaded"}), 200

    try:
        visualizations, build_time_seconds, from_cache = (
            _get_or_build_readiness_visualizations(section, file_info)
        )
    except Exception as e:
        metric_time_log.error(
            "Readiness report visualizations — %s error: %s", section, e, exc_info=True
        )
        return jsonify({
            "success": False,
            "message": f"{type(e).__name__}: {e}",
        }), 200

    if not from_cache:
        metric_time_log.info(
            "Readiness report section %s visualizations built in %.2f seconds",
            section,
            build_time_seconds,
        )
    return jsonify(ensure_json_serializable({
        "success": True,
        "section": section,
        "visualizations": visualizations,
        "build_time_seconds": build_time_seconds,
        "cached": from_cache,
    }))


@metrics_bp.route("/readiness-report/<section>", methods=["GET"])
def readiness_report_section(section):
    """Return a single readiness-report section as JSON (for progressive UI loading)."""
    if section not in _READINESS_SECTION_BUILDERS:
        return jsonify({"success": False, "message": f"Unknown section: {section}"}), 404

    file_info = _readiness_file_info()
    if file_info is None:
        return jsonify({"success": False, "message": "No file uploaded"}), 200

    data, build_time_seconds, from_cache = _get_or_build_readiness_section(
        section, file_info
    )
    if not from_cache:
        metric_time_log.info(
            "Readiness report section %s built in %.2f seconds",
            section,
            build_time_seconds,
        )
    return jsonify(ensure_json_serializable({
        "success": True,
        "section": section,
        "data": data,
        "build_time_seconds": build_time_seconds,
        "cached": from_cache,
    }))


@metrics_bp.route("/readiness-report", methods=["GET"])
def readiness_report():
    """Return the full readiness report as JSON (all sections in one response)."""
    file_info = _readiness_file_info()
    if file_info is None:
        return jsonify({"success": False, "message": "No file uploaded"}), 200

    start_time = time.time()
    try:
        response = {"success": True, "sections_cached": {}}
        for slug in _READINESS_SECTION_BUILDERS:
            section_data, section_elapsed, from_cache = (
                _get_or_build_readiness_section(slug, file_info)
            )
            if isinstance(section_data, dict):
                section_data = {**section_data, "build_time_seconds": section_elapsed}
            if not from_cache:
                metric_time_log.info(
                    "Readiness report section %s built in %.2f seconds",
                    slug,
                    section_elapsed,
                )
            response["sections_cached"][slug] = from_cache
            response[_READINESS_SECTION_RESPONSE_KEYS[slug]] = section_data

        metric_time_log.info("Readiness report built in %.2f seconds", time.time() - start_time)
        return jsonify(ensure_json_serializable(response))
    except Exception as e:
        metric_time_log.error("Readiness report error: %s", e, exc_info=True)
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"}), 200


@metrics_bp.route("/readiness-report/pdf", methods=["GET"])
def readiness_report_pdf():
    """Build readiness sections (cache on miss) and return a scorecard or full PDF."""
    file_info = _readiness_file_info()
    if file_info is None:
        return jsonify({"success": False, "message": "No file uploaded"}), 400

    from web.readiness.pdf import (
        build_pdf_context,
        pdf_filename,
        render_readiness_report_pdf,
    )

    mode = request.args.get("mode", "scorecard")
    include_details = mode == "full"
    file_name = file_info[1]
    sections = {}
    visualizations: dict[str, dict] = {}
    start_time = time.time()
    try:
        for slug in _READINESS_SECTION_BUILDERS:
            data, section_elapsed, from_cache = _get_or_build_readiness_section(
                slug, file_info
            )
            if isinstance(data, dict) and data.get("error"):
                return jsonify({
                    "success": False,
                    "message": f"Could not build {slug}: {data['error']}",
                }), 500
            sections[slug] = data
            if include_details:
                viz_data, viz_elapsed, viz_cached = _get_or_build_readiness_visualizations(
                    slug, file_info
                )
                visualizations[slug] = viz_data or {}
                if not viz_cached:
                    metric_time_log.info(
                        "Readiness report PDF — %s visualizations built in %.2f seconds",
                        slug,
                        viz_elapsed,
                    )
            if not from_cache:
                metric_time_log.info(
                    "Readiness report PDF — section %s built in %.2f seconds",
                    slug,
                    section_elapsed,
                )

        fair_entry = _get_cached_readiness_fair_compliance(file_name)
        fair_data = fair_entry.get("data") if fair_entry else None
        context = build_pdf_context(
            file_name=file_name,
            sections=sections,
            fair_data=fair_data,
            include_details=include_details,
            visualizations=visualizations,
        )
        pdf_bytes = render_readiness_report_pdf(current_app, context)
        metric_time_log.info(
            "Readiness report PDF (%s) generated in %.2f seconds",
            mode,
            time.time() - start_time,
        )
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=pdf_filename(file_name, full=include_details),
        )
    except RuntimeError as e:
        metric_time_log.error("Readiness report PDF error: %s", e, exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500
    except Exception as e:
        metric_time_log.error("Readiness report PDF error: %s", e, exc_info=True)
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"}), 500


# ---------------------------------------------------------------------------
# Data Structure
# ---------------------------------------------------------------------------

@metrics_bp.route("/data-structure", methods=["GET", "POST"])
def data_structure():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = build_file_info(file_path, file_name, file_type)

    if request.method == "POST":
        start_time = time.time()
        selected = [
            m for m in (
                "constant feature count", "max pairwise correlation", "skewness", "kurtosis",
                "file_reference_validation",
            ) if request.form.get(m) == "yes"
        ]
        metric_time_log.info("Data Structure request started: %s", selected)

        tracer = get_tracer()
        with tracer.start_as_current_span("metric.data_structure") as span:
            span.set_attribute("metric.pillar", "data_structure")
            span.set_attribute("metric.selected", ",".join(selected))
            span.set_attribute("file.name", file_name or "")
            span.set_attribute("file.type", file_type or "")

            try:
                if "constant feature count" in selected:
                    t0 = time.time()
                    with tracer.start_as_current_span("metric.constant_feature_count"):
                        cfc_dict = constant_feature_count(file_info)
                    cfc_dict["Description"] = (
                        "Columns with a single distinct value carry no information "
                        "for modeling and are candidates for removal."
                    )
                    final_dict["Constant Feature Count"] = cfc_dict
                    metric_time_log.info(
                        "Constant Feature Count took %.2f seconds", time.time() - t0
                    )

                if "max pairwise correlation" in selected:
                    t0 = time.time()
                    with tracer.start_as_current_span("metric.max_pairwise_correlation"):
                        final_dict["Max Pairwise Correlation"] = max_pairwise_correlation(
                            file_info
                        )
                    metric_time_log.info(
                        "Max Pairwise Correlation took %.2f seconds", time.time() - t0
                    )

                if "skewness" in selected:
                    t0 = time.time()
                    with tracer.start_as_current_span("metric.skewness"):
                        final_dict["Skewness"] = skewness(file_info)
                    metric_time_log.info("Skewness took %.2f seconds", time.time() - t0)

                if "kurtosis" in selected:
                    t0 = time.time()
                    with tracer.start_as_current_span("metric.kurtosis"):
                        final_dict["Kurtosis"] = kurtosis(file_info)
                    metric_time_log.info("Kurtosis took %.2f seconds", time.time() - t0)

                if "file_reference_validation" in selected:
                    t0 = time.time()
                    try:
                        path_targets = []
                        target_match = request.form.get("file_reference_target_match", "exact")
                        for value in request.form.getlist("file_reference_targets"):
                            if value.strip():
                                path_targets.append(value.strip())
                        roots = _file_reference_allowed_roots()
                        if not roots:
                            raise ValueError("File-reference validation is not configured by the server administrator.")
                        base_dir = _file_reference_base_dir(
                            roots,
                            request.form.get("file_reference_root_id"),
                            request.form.get("file_reference_base_subdirectory"),
                        )
                        max_results = request.form.get("file_reference_max_results", 100)
                        with tracer.start_as_current_span("metric.file_reference_validation"):
                            reference_dict = calculate_file_reference_validation(
                                file_info,
                                path_targets,
                                base_dir=base_dir,
                                max_results=max_results,
                                scan_limit=_file_reference_web_scan_limit(),
                                allowed_roots=roots,
                                target_match=target_match,
                            )
                    except Exception as e:
                        metric_time_log.error("File Reference Validation error: %s", e, exc_info=True)
                        final_dict["File Reference Validation"] = {
                            "Error": f"{type(e).__name__}: {e}",
                            "Description": (
                                "Validates selected dataset values as references to regular files "
                                "available on the AIDRIN web server."
                            ),
                        }
                    else:
                        final_dict["File Reference Validation"] = reference_dict
                    metric_time_log.info("File Reference Validation took %.2f seconds", time.time() - t0)

            except Exception as e:
                metric_time_log.error("Data Structure error: %s", e, exc_info=True)
                return jsonify({"error": f"{type(e).__name__}: {e}"}), 200

            duration_ms = (time.time() - start_time) * 1000
            span.set_attribute("metric.duration_ms", duration_ms)
            metric_time_log.info("Data Structure completed in %.2f seconds", time.time() - start_time)
            return store_result("metrics.data_structure", final_dict)

    return get_result_or_default("metrics.data_structure", file_path, file_name)


# ---------------------------------------------------------------------------
# Fairness
# ---------------------------------------------------------------------------

@metrics_bp.route("/fairness", methods=["GET", "POST"])
def fairness():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = build_file_info(file_path, file_name, file_type)
    file = read_file(file_info)

    if request.method == "POST":
        start_time = time.time()
        selected = []
        if request.form.get("representation rate") == "yes":
            selected.append("Representation Rate")
        if request.form.get("statistical rate") == "yes":
            selected.append("Statistical Rate")
        if request.form.get("conditional demographic disparity") == "yes":
            selected.append("Conditional Demographic Disparity")
        metric_time_log.info("Fairness request started: %s", selected)

        if (
            request.form.get("representation rate") == "yes"
            and request.form.get("features for representation rate") is not None
        ):
            t0 = time.time()
            rep_dict = {}
            list_of_cols = [
                item.strip()
                for item in request.form.get("features for representation rate").split(", ")
            ]
            rep_dict["Probability ratios"] = calculate_representation_rate(list_of_cols, file_info)
            rep_dict["Representation Rate Visualization"] = create_representation_rate_vis(
                list_of_cols, file_info
            )
            rep_dict["Description"] = (
                "Represent probability ratios that quantify the relative representation "
                "of different categories within the sensitive features, highlighting "
                "differences in representation rates between various groups. Higher "
                "values imply overrepresentation relative to another"
            )
            final_dict["Representation Rate"] = rep_dict
            metric_time_log.info("Representation Rate took %.2f seconds", time.time() - t0)

        if (
            request.form.get("statistical rate") == "yes"
            and request.form.get("features for statistical rate") is not None
            and request.form.get("target for statistical rate") is not None
        ):
            try:
                t0 = time.time()
                y_true = request.form.get("target for statistical rate")
                sensitive_attribute_column = request.form.get("features for statistical rate")
                sr_dict = calculate_statistical_rates(y_true, sensitive_attribute_column, file_info)
                sr_dict["Description"] = (
                    "The graph illustrates the statistical rates of various classes across different "
                    "sensitive attributes. Each group in the graph represents a specific sensitive "
                    "attribute, and within each group, each bar corresponds to a class, with the height "
                    "indicating the proportion of that sensitive attribute within that particular class"
                )
                final_dict["Statistical Rate"] = sr_dict
                metric_time_log.info(
                    "Statistical Rate analysis took %.2f seconds", time.time() - t0
                )
            except Exception as e:
                metric_time_log.error("Error during Statistical Rate analysis: %s", e)
                final_dict["Statistical Rate"] = {"Error": str(e)}

        if request.form.get("conditional demographic disparity") == "yes":
            t0 = time.time()
            target = request.form.get("target for conditional demographic disparity")
            sensitive = request.form.get("sensitive for conditional demographic disparity")
            accepted_value = request.form.get("target value for conditional demographic disparity")
            if not accepted_value or not str(accepted_value).strip():
                final_dict["Conditional Demographic Disparity"] = {
                    "Error": (
                        "Please enter a target value for Conditional Demographic "
                        "Disparity (a value that exists in the target column)."
                    )
                }
            else:
                try:
                    cdd_result = conditional_demographic_disparity.delay(
                        file[target].to_list(), file[sensitive].to_list(), accepted_value
                    )
                    cdd_dict = cdd_result.get(timeout=60)
                except Exception as e:
                    metric_time_log.error("Error during Conditional Demographic Disparity analysis: %s", e)
                    final_dict["Conditional Demographic Disparity"] = {"Error": str(e)}
                    cdd_dict = None
                if cdd_dict is not None:
                    cdd_dict["Description"] = (
                        "The conditional demographic disparity metric evaluates the distribution "
                        "of outcomes categorized as positive and negative across various sensitive groups. "
                        "The user specifies which outcome category is considered \"positive\" for the analysis, "
                        "with all other outcome categories classified as \"negative\". The metric calculates the "
                        "proportion of outcomes classified as \"positive\" and \"negative\" within each sensitive group."
                        " A resulting disparity value of True indicates that within a specific sensitive group, "
                        "the proportion of outcomes classified as \"negative\" exceeds the proportion classified as"
                        " \"positive\". This metric provides insights into potential disparities in outcome distribution "
                        "across sensitive groups based on the user-defined positive outcome criterion."
                    )
                    final_dict["Conditional Demographic Disparity"] = cdd_dict
                    metric_time_log.info(
                        "Conditional Demographic Disparity took %.2f seconds", time.time() - t0
                    )

        duration = time.time() - start_time
        metric_time_log.info("Fairness completed in %.2f seconds", duration)
        with trace_metric("fairness", "fairness_bias", file_name=file_name, file_type=file_type) as span:
            span.set_attribute("metric.duration_ms", duration * 1000)
        return store_result("metrics.fairness", final_dict)

    return get_result_or_default("metrics.fairness", file_path, file_name)


# ---------------------------------------------------------------------------
# Correlation Analysis
# ---------------------------------------------------------------------------

@metrics_bp.route("/correlation-analysis", methods=["GET", "POST"])
def correlation_analysis():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")

    if request.method == "POST":
        metric_time_log.info("Correlation Analysis request started")
        start_time = time.time()
        try:
            if request.form.get("correlations") == "yes":
                t0 = time.time()
                cat_cols = [
                    col.strip()
                    for col in request.form.get("categorical features", "").split(",")
                    if col.strip()
                ]
                num_cols = [
                    col.strip()
                    for col in request.form.get("numerical features", "").split(",")
                    if col.strip()
                ]
                columns = cat_cols + num_cols
                file_info = build_file_info(file_path, file_name, file_type)
                metric_time_log.info("Correlation Analysis: %d categorical, %d numerical columns", len(cat_cols), len(num_cols))

                correlations_result = calc_correlations.delay(columns, file_info)
                corr_dict = correlations_result.get(timeout=METRIC_CELERY_TIMEOUT)
                if "Message" in corr_dict:
                    metric_time_log.warning("Correlation analysis failed: %s", corr_dict["Message"])
                    final_dict["Error"] = corr_dict["Message"]
                else:
                    final_dict["Correlations Analysis Categorical"] = corr_dict[
                        "Correlations Analysis Categorical"
                    ]
                    final_dict["Correlations Analysis Numerical"] = corr_dict[
                        "Correlations Analysis Numerical"
                    ]
                metric_time_log.info("Correlations took %.2f seconds", time.time() - t0)
                duration = time.time() - start_time
                metric_time_log.info("Correlation Analysis completed in %.2f seconds", duration)
                with trace_metric("correlation_analysis", "impact_on_ai", file_name=file_name, file_type=file_type) as span:
                    span.set_attribute("metric.duration_ms", duration * 1000)
                return store_result("metrics.correlation_analysis", final_dict)
            else:
                return jsonify({"message": "No correlation analysis selected"}), 200
        except Exception as e:
            metric_time_log.error("Correlation Analysis error: %s", e, exc_info=True)
            return jsonify({"error": f"{type(e).__name__}: {e}"}), 200

    return get_result_or_default("metrics.correlation_analysis", file_path, file_name)


# ---------------------------------------------------------------------------
# Feature Relevance
# ---------------------------------------------------------------------------

@metrics_bp.route("/feature-relevance", methods=["GET", "POST"])
def feature_relevance():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")

    if request.method == "POST":
        start_time = time.time()
        if request.form.get("feature relevancy") == "yes":
            cat_cols = [
                col.strip()
                for col in request.form.get("categorical features", "").split(",")
                if col.strip()
            ]
            num_cols = [
                col.strip()
                for col in request.form.get("numerical features", "").split(",")
                if col.strip()
            ]
            target = request.form.get("target for feature relevance")
            if not target:
                return jsonify({
                    "trigger": "correlationError",
                    "error": "Please select a target feature before submitting.",
                }), 200
            metric_time_log.info(
                "Feature Relevance request started: %d categorical, %d numerical columns, target=%r",
                len(cat_cols), len(num_cols), target,
            )

            try:
                if target in cat_cols or target in num_cols:
                    return jsonify({
                        "trigger": "correlationError",
                        "error": "The target feature cannot also be selected as an input feature. "
                                 "Please deselect it from the categorical/numerical features list.",
                    }), 200
                file_info = build_file_info(file_path, file_name, file_type)
                t0 = time.time()
                data_cleaning_result = data_cleaning.delay(cat_cols, num_cols, target, file_info)
                df_json = data_cleaning_result.get(timeout=METRIC_CELERY_TIMEOUT)
                metric_time_log.info("Feature Relevance — data cleaning took %.2f seconds", time.time() - t0)

                if isinstance(df_json, dict) and "Error" in df_json:
                    return jsonify({"trigger": "correlationError", "error": df_json["Error"]}), 200
                if df_json is None:
                    return jsonify({"trigger": "correlationError", "error": "Data cleaning failed"}), 200
            except Exception as e:
                metric_time_log.error("Feature Relevance — data cleaning error: %s", e, exc_info=True)
                return jsonify({"trigger": "correlationError", "error": f"{type(e).__name__}: {e}"}), 200

            try:
                t0 = time.time()
                pearson_corr_result = pearson_correlation.delay(df_json, target)
                correlations = pearson_corr_result.get(timeout=METRIC_CELERY_TIMEOUT)
                metric_time_log.info("Feature Relevance — Pearson correlation took %.2f seconds", time.time() - t0)

                if isinstance(correlations, dict) and "Error" in correlations:
                    return jsonify({"trigger": "correlationError", "error": correlations["Error"]}), 200
                if not correlations:
                    return jsonify(
                        {"trigger": "correlationError", "error": "No valid correlations could be calculated"}
                    ), 200
            except Exception as e:
                metric_time_log.error("Feature Relevance — Pearson correlation error: %s", e, exc_info=True)
                return jsonify({"trigger": "correlationError", "error": f"{type(e).__name__}: {e}"}), 200

            try:
                t0 = time.time()
                plot_features_result = plot_features.delay(correlations, target)
                f_plot = plot_features_result.get(timeout=METRIC_CELERY_TIMEOUT)
                metric_time_log.info("Feature Relevance — plot generation took %.2f seconds", time.time() - t0)
                if f_plot is None:
                    return jsonify({"trigger": "correlationError", "error": "Visualization generation failed"}), 200
            except Exception as e:
                metric_time_log.error("Feature Relevance — plot generation error: %s", e)
                return jsonify(
                    {"trigger": "correlationError", "error": f"Plot generation failed: {str(e)}"}
                ), 200

            f_dict = {
                "Pearson Correlation to Target": correlations,
                "Feature Relevance Visualization": f_plot,
                "Description": (
                    "With minimum data cleaning (drop missing values, onehot encode "
                    "categorical features, labelencode target feature), the Pearson "
                    "correlation coefficient is calculated for each feature against the "
                    "target variable. A value of 1 indicates a perfect positive "
                    "correlation, while a value of -1 indicates a perfect negative "
                    "correlation."
                ),
            }
            final_dict["Feature Relevance"] = f_dict
            duration = time.time() - start_time
            metric_time_log.info("Feature Relevance completed in %.2f seconds", duration)
            with trace_metric("feature_relevance", "impact_on_ai", file_name=file_name, file_type=file_type) as span:
                span.set_attribute("metric.duration_ms", duration * 1000)
            return store_result("metrics.feature_relevance", final_dict)
        else:
            return jsonify({"message": "No feature relevance analysis selected"}), 200

    return get_result_or_default("metrics.feature_relevance", file_path, file_name)


# ---------------------------------------------------------------------------
# Class Imbalance
# ---------------------------------------------------------------------------

@metrics_bp.route("/class-imbalance", methods=["GET", "POST"])
def class_imbalance():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = build_file_info(file_path, file_name, file_type)
    file = read_file(file_info)

    if request.method == "POST":
        start_time = time.time()
        if request.form.get("class imbalance") == "yes":
            classes = request.form.get("target features for class imbalance")
            dist_metric = request.form.get("distance metric for class imbalance") or "EU"
            metric_time_log.info(
                "Class Imbalance request started: target=%r, dist_metric=%r",
                classes,
                dist_metric,
            )

            cache_key = generate_metric_cache_key(
                file_name, "classimbalance", classes=classes, dist_metric=dist_metric
            )

            cached_entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)
            if cached_entry and is_metric_cache_valid(cached_entry):
                final_dict["Class Imbalance"] = cached_entry["data"]
                current_app.TEMP_RESULTS_CACHE[cache_key] = {
                    "data": cached_entry["data"],
                    "timestamp": time.time(),
                    "expires_at": time.time() + (30 * 60),
                }
            else:
                if cached_entry:
                    current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
                t0 = time.time()
                ci_dict = _compute_class_imbalance(file, classes, dist_metric)
                metric_time_log.info(
                    "Class Imbalance — computation took %.2f seconds", time.time() - t0
                )
                final_dict["Class Imbalance"] = ci_dict
                current_app.TEMP_RESULTS_CACHE[cache_key] = {
                    "data": ci_dict,
                    "timestamp": time.time(),
                    "expires_at": time.time() + (30 * 60),
                }

        duration = time.time() - start_time
        metric_time_log.info("Class Imbalance completed in %.2f seconds", duration)
        with trace_metric("class_imbalance", "fairness_bias", file_name=file_name, file_type=file_type) as span:
            span.set_attribute("metric.duration_ms", duration * 1000)
        return store_result("metrics.class_imbalance", final_dict)

    return get_result_or_default("metrics.class_imbalance", file_path, file_name)


def _compute_class_imbalance(file, classes, dist_metric, include_visualization=True):
    ci_dict = {}
    try:
        if include_visualization:
            ci_dict["Class Imbalance Visualization"] = class_distribution_plot(file, classes)
        ci_dict["Description"] = (
            "The chart displays the distribution of classes within the "
            "specified feature, providing a visual representation of the "
            "relative proportions of each class."
        )
        imbalance_result = calc_imbalance_degree(file, classes, dist_metric=dist_metric)
        if "Error" in imbalance_result:
            ci_dict["Error"] = imbalance_result["Error"]
            ci_dict["ErrorType"] = imbalance_result.get("ErrorType", "Processing Error")
            ci_dict["Class Imbalance Visualization"] = ""
            ci_dict["Description"] = f"Error: {imbalance_result['Error']}"
        else:
            ci_dict["Imbalance degree"] = imbalance_result
    except Exception as e:
        ci_dict["Error"] = str(e)
        ci_dict["ErrorType"] = "Processing Error"
        ci_dict["Class Imbalance Visualization"] = ""
        ci_dict["Description"] = f"Error: {str(e)}"
    return ci_dict


# ---------------------------------------------------------------------------
# Privacy Preservation
# ---------------------------------------------------------------------------

@metrics_bp.route("/privacy-preservation", methods=["GET", "POST"])
def privacy_preservation():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = build_file_info(file_path, file_name, file_type)
    file = read_file(file_info)

    if request.method == "POST":
        start_time = time.time()
        selected_privacy_metrics = [
            m for m in [
                "differential privacy" if request.form.get("differential privacy") == "yes" else None,
                "single attribute risk score" if request.form.get("single attribute risk score") == "yes" else None,
                "multiple attribute risk score" if request.form.get("multiple attribute risk score") == "yes" else None,
                "k-anonymity" if request.form.get("k-anonymity") == "yes" else None,
                "l-diversity" if request.form.get("l-diversity") == "yes" else None,
                "t-closeness" if request.form.get("t-closeness") == "yes" else None,
                "entropy risk" if request.form.get("entropy risk") == "yes" else None,
            ] if m is not None
        ]
        metric_time_log.info(
            "Privacy Preservation request started: selected=%s", selected_privacy_metrics
        )

        if request.form.get("differential privacy") == "yes":
            numerical_features_raw = request.form.get("numerical features to add noise")
            if not numerical_features_raw or not numerical_features_raw.strip():
                final_dict["DP Statistics"] = _dp_error(
                    "No numerical features selected for differential privacy."
                )
            else:
                feature_to_add_noise = [f.strip() for f in numerical_features_raw.split(",") if f.strip()]
                if not feature_to_add_noise:
                    final_dict["DP Statistics"] = _dp_error("Invalid numerical features selected.")
                else:
                    epsilon_raw = request.form.get("privacy budget")
                    epsilon = 0.1
                    if epsilon_raw and epsilon_raw.strip():
                        try:
                            epsilon = float(epsilon_raw)
                            if epsilon <= 0:
                                final_dict["DP Statistics"] = _dp_error(
                                    "Invalid epsilon value. Epsilon must be greater than 0."
                                )
                            else:
                                _process_differential_privacy(
                                    file_name, feature_to_add_noise, epsilon, file, final_dict
                                )
                        except ValueError:
                            final_dict["DP Statistics"] = _dp_error("Invalid epsilon value format.")
                    else:
                        _process_differential_privacy(
                            file_name, feature_to_add_noise, epsilon, file, final_dict
                        )

        if request.form.get("single attribute risk score") == "yes":
            id_feature = request.form.get("id feature to measure single attribute risk score")
            eval_features = request.form.getlist(
                "quasi identifiers to measure single attribute risk score"
            )
            if not eval_features or (len(eval_features) == 1 and eval_features[0] == ""):
                final_dict["Single attribute risk scoring"] = {
                    "Error": "No quasi-identifiers selected for single attribute risk scoring.",
                    "Single attribute risk scoring Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                    "ErrorType": "Selection Error",
                }
            else:
                cache_key = generate_metric_cache_key(
                    file_name, "single", id_feature=id_feature, qis=eval_features
                )
                _run_cached_async_task(
                    cache_key,
                    calculate_single_attribute_risk_score,
                    final_dict,
                    "Single attribute risk scoring",
                    file.to_json(),
                    id_feature,
                    eval_features,
                )

        if request.form.get("multiple attribute risk score") == "yes":
            id_feature = request.form.get("id feature to measure multiple attribute risk score")
            eval_features = request.form.getlist(
                "quasi identifiers to measure multiple attribute risk score"
            )
            if not eval_features or (len(eval_features) == 1 and eval_features[0] == ""):
                final_dict["Multiple attribute risk scoring"] = {
                    "Error": "No quasi-identifiers selected for multiple attribute risk scoring.",
                    "Multiple attribute risk scoring Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                    "ErrorType": "Selection Error",
                }
            elif not id_feature or not id_feature.strip():
                final_dict["Multiple attribute risk scoring"] = {
                    "Error": "No ID feature selected for multiple attribute risk scoring.",
                    "Multiple attribute risk scoring Visualization": "",
                    "Graph interpretation": "No visualization available - no ID feature selected.",
                    "ErrorType": "Selection Error",
                }
            else:
                cache_key = generate_metric_cache_key(
                    file_name, "multiple", id_feature=id_feature, qis=eval_features
                )
                _run_cached_async_task(
                    cache_key,
                    calculate_multiple_attribute_risk_score,
                    final_dict,
                    "Multiple attribute risk scoring",
                    file.to_json(),
                    id_feature,
                    eval_features,
                )

        if request.form.get("k-anonymity") == "yes":
            k_qis = request.form.getlist("quasi identifiers for k-anonymity")
            if not k_qis or (len(k_qis) == 1 and k_qis[0] == ""):
                final_dict["k-Anonymity"] = {
                    "Error": "No quasi-identifiers selected for k-anonymity calculation.",
                    "k-Anonymity Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                }
            else:
                cache_key = generate_metric_cache_key(file_name, "kanon", qis=k_qis)
                _run_cached_sync_task(
                    cache_key, compute_k_anonymity, final_dict, "k-Anonymity", k_qis, file
                )

        if request.form.get("l-diversity") == "yes":
            l_qis = request.form.getlist("quasi identifiers for l-diversity")
            l_sensitive = request.form.get("sensitive attribute for l-diversity")
            if not l_qis or (len(l_qis) == 1 and l_qis[0] == ""):
                final_dict["l-Diversity"] = {
                    "Error": "No quasi-identifiers selected for l-diversity calculation.",
                    "l-Diversity Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                }
            elif not l_sensitive or not l_sensitive.strip():
                final_dict["l-Diversity"] = {
                    "Error": "No sensitive attribute selected for l-diversity calculation.",
                    "l-Diversity Visualization": "",
                    "Graph interpretation": "No visualization available - no sensitive attribute selected.",
                }
            else:
                cache_key = generate_metric_cache_key(
                    file_name, "ldiv", qis=l_qis, sensitive=l_sensitive
                )
                _run_cached_sync_task(
                    cache_key, compute_l_diversity, final_dict, "l-Diversity",
                    l_qis, l_sensitive, file
                )

        if request.form.get("t-closeness") == "yes":
            t_qis = request.form.getlist("quasi identifiers for t-closeness")
            t_sensitive = request.form.get("sensitive attribute for t-closeness")
            if not t_qis or (len(t_qis) == 1 and t_qis[0] == ""):
                final_dict["t-Closeness"] = {
                    "Error": "No quasi-identifiers selected for t-closeness calculation.",
                    "t-Closeness Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                }
            elif not t_sensitive or not t_sensitive.strip():
                final_dict["t-Closeness"] = {
                    "Error": "No sensitive attribute selected for t-closeness calculation.",
                    "t-Closeness Visualization": "",
                    "Graph interpretation": "No visualization available - no sensitive attribute selected.",
                }
            else:
                cache_key = generate_metric_cache_key(
                    file_name, "tclose", qis=t_qis, sensitive=t_sensitive
                )
                _run_cached_sync_task(
                    cache_key, compute_t_closeness, final_dict, "t-Closeness",
                    t_qis, t_sensitive, file
                )

        if request.form.get("entropy risk") == "yes":
            entropy_qis = request.form.getlist("quasi identifiers for entropy risk")
            if not entropy_qis or (len(entropy_qis) == 1 and entropy_qis[0] == ""):
                final_dict["Entropy Risk"] = {
                    "Error": "No quasi-identifiers selected for entropy risk calculation.",
                    "Entropy Risk Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                }
            else:
                cache_key = generate_metric_cache_key(file_name, "entropy", qis=entropy_qis)
                _run_cached_sync_task(
                    cache_key, compute_entropy_risk, final_dict, "Entropy Risk",
                    entropy_qis, file
                )

        duration = time.time() - start_time
        metric_time_log.info("Privacy Preservation completed in %.2f seconds", duration)
        with trace_metric("privacy_preservation", "data_governance", file_name=file_name, file_type=file_type) as span:
            span.set_attribute("metric.duration_ms", duration * 1000)
        return store_result("metrics.privacy_preservation", final_dict)

    return get_result_or_default("metrics.privacy_preservation", file_path, file_name)


# ---------------------------------------------------------------------------
# HIPAA Compliance
# ---------------------------------------------------------------------------

@metrics_bp.route("/hipaa-compliance", methods=["GET", "POST"])
def hipaa_compliance():
    final_dict = {}
    data_file_path = session.get("uploaded_file_path")
    data_file_name = session.get("uploaded_file_name")
    data_file_type = session.get("uploaded_file_type")
    file_info = build_file_info(data_file_path, data_file_name, data_file_type)

    if request.method == "POST":
        metric_time_log.info("HIPAA Compliance Evaluation Request Started")
        start_time = time.time()
        try:
            df = read_file(file_info)
            selected_columns = request.form.getlist("HIPAA identifiers for HIPAA compliance")
            detected_hipaa = detect_hipaa_identifiers(df, selected_columns)

            final_dict["HIPAA Compliance Evaluation"] = {
                "Detected HIPAA Identifiers": detected_hipaa,
                "Description": (
                    "This metric performs a high-precision audit of the dataset to identify Protected "
                    "Health Information (PHI). It uses a hybrid approach: using pre-compiled regular "
                    "expressions for fixed-format identifiers (SSNs, emails, medical IDs, URLs, "
                    "phone/fax numbers, VIN numbers and IP addresses) and the pgeocode GeoNames "
                    "database to validate global postal codes."
                ),
            }
            final_dict = ensure_json_serializable(final_dict)

        except Exception as e:
            metric_time_log.error("HIPAA Compliance error: %s", e, exc_info=True)
            return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

        duration = time.time() - start_time
        metric_time_log.info("HIPAA Compliance Evaluation completed in %.2f seconds", duration)
        with trace_metric("hipaa_compliance", "data_governance", file_name=data_file_name, file_type=data_file_type) as span:
            span.set_attribute("metric.duration_ms", duration * 1000)
        return store_result("metrics.hipaa_compliance", final_dict)

    return get_result_or_default("metrics.hipaa_compliance", data_file_path, data_file_name)


# ---------------------------------------------------------------------------
# FAIR Assessment
# ---------------------------------------------------------------------------

@metrics_bp.route("/fair-assessment", methods=["GET", "POST"])
def fair_assessment():
    try:
        if request.method == "POST":
            start_time = time.time()
            metric_time_log.info("FAIR Assessment request started")
            if "metadata" not in request.files:
                return jsonify({"error": "No 'metadata' field found in form data"}), 400

            file = request.files["metadata"]
            if file.filename == "":
                return jsonify({"error": "No selected file"}), 400
            if not file.filename.endswith(".json"):
                return jsonify({"error": "Invalid file format. Please upload a JSON file."}), 400

            json_data = file.read()
            metadata_type = request.form.get("metadata type", "")
            readiness_context = request.form.get("readiness_context") == "1"
            dataset_file_name = (
                session.get("uploaded_file_name")
                or session.get("globus_file_name")
                or ""
            )
            metadata_fingerprint = _fair_metadata_fingerprint(json_data, metadata_type)

            if readiness_context and dataset_file_name:
                cached_fair = _get_cached_readiness_fair_compliance(dataset_file_name)
                if (
                    cached_fair is not None
                    and cached_fair.get("metadata_fingerprint") == metadata_fingerprint
                ):
                    metric_time_log.info(
                        "Readiness report FAIR compliance cache hit for %s",
                        dataset_file_name,
                    )
                    return jsonify(
                        ensure_json_serializable(
                            {
                                **cached_fair["data"],
                                "cached": True,
                                "build_time_seconds": cached_fair.get(
                                    "build_time_seconds"
                                ),
                            }
                        )
                    )

            try:
                data_dict = json.loads(json_data.decode("utf-8"))
            except json.JSONDecodeError as e:
                return jsonify({"error": f"Error parsing JSON: {str(e)}"}), 400

            try:
                result = _run_fair_assessment(data_dict, metadata_type)
            except ValueError:
                return jsonify({"error": "Unknown metadata type"}), 400
            except json.JSONDecodeError as e:
                return jsonify({"error": f"Error parsing JSON: {str(e)}"}), 400

            duration = time.time() - start_time
            metric_time_log.info("FAIR Assessment completed in %.2f seconds", duration)
            with trace_metric("fair_assessment", "understandability") as span:
                span.set_attribute("metric.duration_ms", duration * 1000)
                span.set_attribute("metadata.type", metadata_type)

            result = ensure_json_serializable(result)
            if readiness_context and dataset_file_name:
                _cache_readiness_fair_compliance(
                    dataset_file_name,
                    result,
                    metadata_type=metadata_type,
                    metadata_filename=file.filename,
                    metadata_fingerprint=metadata_fingerprint,
                    build_time_seconds=round(duration, 2),
                )
            return jsonify({**result, "cached": False, "build_time_seconds": round(duration, 2)})

        else:
            results_id = request.args.get("results_id")
            if results_id and results_id in current_app.TEMP_RESULTS_CACHE:
                entry = current_app.TEMP_RESULTS_CACHE.pop(results_id)
                return jsonify(entry["data"])

            return redirect(url_for("core.inspector"))

    except Exception as e:
        metric_time_log.error("FAIR Assessment error: %s", e, exc_info=True)
        return jsonify({"error": "An internal error occurred"}), 400


# ---------------------------------------------------------------------------
# Async task status polling
# ---------------------------------------------------------------------------

@metrics_bp.route("/check-and-update-task/<task_id>/<metric_name>", methods=["GET"])
def check_task_status(task_id, metric_name):
    try:
        task_result = AsyncResult(task_id)

        if task_result.ready():
            if task_result.successful():
                result = task_result.get()
                cache_key = f"{task_id}_{metric_name}"
                current_app.TEMP_RESULTS_CACHE[cache_key] = {
                    "data": result,
                    "timestamp": time.time(),
                }
                return jsonify({"status": "completed", "result": result})
            else:
                error = str(task_result.info) if task_result.info else "Task failed"
                return jsonify({"status": "failed", "error": error}), 500
        else:
            progress_info = (
                task_result.info if isinstance(task_result.info, dict) else {}
            )
            return jsonify(
                {
                    "status": "processing",
                    "progress": {
                        "current": progress_info.get("current", 0),
                        "total": progress_info.get("total", 100),
                        "status": progress_info.get("status", "Processing..."),
                    },
                }
            )
    except Exception as e:
        metric_time_log.error("Task status check error: %s", e, exc_info=True)
        return jsonify({"status": "error", "error": "An internal error occurred"}), 500


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _dp_error(message):
    return {
        "Error": message,
        "DP Statistics Visualization": "",
        "Graph interpretation": "No visualization available due to invalid parameters.",
        "Mean of feature (before noise)": "N/A",
        "Variance of feature (before noise)": "N/A",
        "Mean of feature (after noise)": "N/A",
        "Variance of feature (after noise)": "N/A",
        "Noisy file saved": "Failed - Invalid parameters",
    }


def _process_differential_privacy(file_name, features, epsilon, file, final_dict):
    cache_key = generate_metric_cache_key(
        file_name, "dp", features=features, epsilon=epsilon
    )
    cached_entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)

    if cached_entry and is_metric_cache_valid(cached_entry):
        final_dict["DP Statistics"] = cached_entry["data"]
        current_app.TEMP_RESULTS_CACHE[cache_key] = {
            "data": cached_entry["data"],
            "timestamp": time.time(),
            "expires_at": time.time() + (30 * 60),
        }
        return

    if cached_entry:
        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)

    try:
        noisy_stat = return_noisy_stats(features, float(epsilon), file)
        final_dict["DP Statistics"] = noisy_stat
    except Exception as e:
        error_message = str(e)
        if "Epsilon must be greater than 0" in error_message:
            noisy_stat = _dp_error("Invalid epsilon value. Epsilon must be greater than 0.")
        elif "Dataset is empty" in error_message:
            noisy_stat = {
                "Error": "Dataset is empty after removing null values or contains no valid data.",
                "DP Statistics Visualization": "",
                "Graph interpretation": "No visualization available - insufficient data.",
                "Mean of feature (before noise)": "N/A",
                "Variance of feature (before noise)": "N/A",
                "Mean of feature (after noise)": "N/A",
                "Variance of feature (after noise)": "N/A",
                "Noisy file saved": "Failed - No data to process",
            }
        else:
            noisy_stat = {
                "Error": f"Processing error: {error_message}",
                "DP Statistics Visualization": "",
                "Graph interpretation": "No visualization available due to processing error.",
                "Mean of feature (before noise)": "N/A",
                "Variance of feature (before noise)": "N/A",
                "Mean of feature (after noise)": "N/A",
                "Variance of feature (after noise)": "N/A",
                "Noisy file saved": "Failed - Processing error",
            }
        final_dict["DP Statistics"] = noisy_stat

    current_app.TEMP_RESULTS_CACHE[cache_key] = {
        "data": final_dict["DP Statistics"],
        "timestamp": time.time(),
        "expires_at": time.time() + (30 * 60),
    }


def _run_cached_async_task(cache_key, task_fn, final_dict, result_key, *task_args):
    """Run an async Celery task with cache check/store pattern."""
    cached_entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)
    if cached_entry and is_metric_cache_valid(cached_entry):
        final_dict[result_key] = cached_entry["data"]
        current_app.TEMP_RESULTS_CACHE[cache_key] = {
            "data": cached_entry["data"],
            "timestamp": time.time(),
            "expires_at": time.time() + (30 * 60),
        }
        return

    if cached_entry:
        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)

    try:
        task = task_fn.delay(*task_args)
        result_data = {
            "task_id": task.id,
            "status": "processing",
            "message": f"{result_key} is being processed asynchronously. Please check back later.",
            "is_async": True,
            "cache_key": cache_key,
        }
        final_dict[result_key] = result_data
        current_app.TEMP_RESULTS_CACHE[cache_key] = {
            "data": result_data,
            "timestamp": time.time(),
            "expires_at": time.time() + (30 * 60),
            "task_id": task.id,
        }
    except Exception as e:
        final_dict[result_key] = {
            "Error": f"Processing error: {str(e)}",
            f"{result_key} Visualization": "",
            "Graph interpretation": "No visualization available due to processing error.",
            "ErrorType": "Processing Error",
        }


def _run_cached_sync_task(cache_key, task_fn, final_dict, result_key, *task_args):
    """Run a synchronous metric function with cache check/store pattern."""
    cached_entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)
    if cached_entry and is_metric_cache_valid(cached_entry):
        final_dict[result_key] = cached_entry["data"]
        current_app.TEMP_RESULTS_CACHE[cache_key] = {
            "data": cached_entry["data"],
            "timestamp": time.time(),
            "expires_at": time.time() + (30 * 60),
        }
        return

    if cached_entry:
        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)

    try:
        result = task_fn(*task_args)
        final_dict[result_key] = result
        current_app.TEMP_RESULTS_CACHE[cache_key] = {
            "data": result,
            "timestamp": time.time(),
            "expires_at": time.time() + (30 * 60),
        }
    except Exception as e:
        final_dict[result_key] = {
            "Error": f"Processing error: {str(e)}",
            f"{result_key} Visualization": "",
            "Graph interpretation": "No visualization available due to processing error.",
        }
