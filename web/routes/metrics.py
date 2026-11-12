import hashlib
import io
import json
import logging
import time

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
from aidrin.file_handling.file_parser import read_file
from aidrin.file_handling.file_reference_policy import (
    allowed_roots,
    discovery_configuration,
    resolve_base_dir,
    scan_limit,
)
from aidrin.report.fairness import (
    compute_class_imbalance as _compute_class_imbalance,
)
from aidrin.report.overview import (
    build_dataset_overview_section as _build_dataset_overview_section_impl,
)
from aidrin.report.registry import (
    SECTION_BUILDERS as _AIDRIN_SECTION_BUILDERS,
    SECTION_RESPONSE_KEYS as _READINESS_SECTION_RESPONSE_KEYS,
    make_viz_builders,
)
from aidrin.file_handling.value_iterators import iter_targets
from aidrin.structured_data_metrics.add_noise import return_noisy_stats
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
from aidrin.structured_data_metrics.variable_unit_validation import (
    calculate_variable_unit_validation,
    unit_suggestion_catalog,
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
    continuous_bars,
    summary_histograms,
    categorical_distribution_charts,
)

metrics_bp = Blueprint("metrics", __name__)

metric_time_log = logging.getLogger("metric")
METRIC_CELERY_TIMEOUT = 120


def _file_reference_allowed_roots():
    return allowed_roots(current_app.config.get("FILE_REFERENCE_ALLOWED_ROOTS"))


def _file_reference_web_scan_limit():
    return scan_limit(current_app.config.get("FILE_REFERENCE_WEB_SCAN_LIMIT"))


def _file_reference_base_dir(roots, root_id, subdirectory):
    return resolve_base_dir(roots, root_id, subdirectory)


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
        file_info = (file_path, file_name, file_type)
        targets = iter_targets(file_info)
        unit_metadata = calculate_variable_unit_validation(file_info)
        file_reference = discovery_configuration(
            current_app.config.get("FILE_REFERENCE_ALLOWED_ROOTS"),
            current_app.config.get("FILE_REFERENCE_WEB_SCAN_LIMIT"),
        )
        return jsonify({
            "success": True,
            "targets": ensure_json_serializable(targets),
            "unit_metadata": ensure_json_serializable(unit_metadata),
            "unit_catalog": unit_suggestion_catalog(),
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
                                    "or regex rules on selected columns or native HDF5 datasets, or same-row column comparisons."
                                ),
                            }
                        else:
                            custom_dict["Description"] = (
                                "Custom criteria outliers are values that violate user-defined range "
                                "or regex rules on selected columns or native HDF5 datasets, or same-row column comparisons."
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
# Section/viz builders live in aidrin.report.*; web injects overview chart
# rendering (matplotlib helpers in web.routes.utils).


def _render_overview_charts(chart_df):
    """Attach overview chart images using Flask-side matplotlib helpers."""
    return {
        "categorical_charts": categorical_distribution_charts(chart_df),
        "histograms": summary_histograms(chart_df, figsize=(7, 4.5)),
        "histogram_bars": continuous_bars(chart_df, figsize=(7, 4.5)),
    }


def _build_dataset_overview_section(file_info, include_visualizations=False):
    """Web wrapper: inject chart renderer so aidrin stays free of web imports."""
    return _build_dataset_overview_section_impl(
        file_info,
        include_visualizations=include_visualizations,
        render_overview_charts=(
            _render_overview_charts if include_visualizations else None
        ),
    )


_READINESS_SECTION_BUILDERS = {
    **_AIDRIN_SECTION_BUILDERS,
    # Inject overview chart renderer when visualizations are requested inline.
    "dataset-overview": _build_dataset_overview_section,
}

_READINESS_VIZ_BUILDERS = make_viz_builders(
    render_overview_charts=_render_overview_charts
)

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
    """Stable fingerprint for readiness FAIR cache invalidation.

    Uses the canonical standard name so legacy form values (``DCAT``,
    ``Datacite``) share a cache entry with CLI-style names.
    """
    from aidrin.structured_data_metrics.fair_metadata import normalize_fair_standard

    canonical = normalize_fair_standard(metadata_type or "auto")
    digest = hashlib.sha256()
    digest.update(json_bytes)
    digest.update(b"|")
    digest.update(canonical.encode("utf-8"))
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
    """Score metadata with the same engine as ``aidrin fair`` / CLI readiness.

    Thin web adapter around ``calculate_fair_compliance`` (Croissant, RO-Crate,
    DCAT-US 3.0/1.1, DataCite; ``auto`` detects). Legacy form values ``DCAT``
    and ``Datacite`` remain accepted. Numeric rounding matches other web
    metric tables; the underlying checks are identical to the headless path.
    """
    import aidrin

    from aidrin.structured_data_metrics.fair_metadata import normalize_fair_standard

    standard = normalize_fair_standard(metadata_type or "auto")
    return format_dict_values(aidrin.calculate_fair_compliance(data_dict, standard))


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
    """Return ``(file_path, file_name, file_type)`` from session, or *None*.

    Uses ``build_file_info`` so session paths pass the upload-folder
    path-traversal barrier (same control as other metric routes).
    """
    file_path = session.get("uploaded_file_path")
    if not file_path:
        return None
    info = build_file_info(
        file_path,
        session.get("uploaded_file_name"),
        session.get("uploaded_file_type"),
    )
    if not info[0]:
        return None
    return info[:3]


def _build_readiness_section(section, file_info, include_visualizations=False):
    """Build one readiness-report section; return error dict on failure."""
    from aidrin.report.builder import build_readiness_section

    # Exception text stays in the server log, not the response or PDF.
    return build_readiness_section(
        section,
        file_info,
        include_visualizations=include_visualizations,
        builders=_READINESS_SECTION_BUILDERS,
        error_message=(
            "This section could not be computed. Details are in the server log."
        ),
    )


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
            "message": "Could not build the visualizations for this section.",
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
    from aidrin.report.builder import build_readiness_report

    file_info = _readiness_file_info()
    if file_info is None:
        return jsonify({"success": False, "message": "No file uploaded"}), 200

    start_time = time.time()
    try:
        # Prefer cache hits; only compute missing sections via the shared builder.
        file_name = file_info[1]
        sections_cached = {}
        preloaded = {}
        missing_slugs = []
        for slug in _READINESS_SECTION_BUILDERS:
            cached, build_time = _get_cached_readiness_payload(file_name, slug)
            if cached is not None:
                sections_cached[slug] = True
                preloaded[slug] = {**cached, "build_time_seconds": build_time}
            else:
                sections_cached[slug] = False
                missing_slugs.append(slug)

        if missing_slugs:
            computed = build_readiness_report(
                file_info,
                sections=missing_slugs,
                section_builders=_READINESS_SECTION_BUILDERS,
                section_error_message=(
                    "This section could not be computed. Details are in the server log."
                ),
            )
            for slug in missing_slugs:
                key = _READINESS_SECTION_RESPONSE_KEYS[slug]
                section_data = computed.get(key)
                if isinstance(section_data, dict):
                    build_time = section_data.get("build_time_seconds", 0)
                    metric_time_log.info(
                        "Readiness report section %s built in %.2f seconds",
                        slug,
                        build_time,
                    )
                    if not section_data.get("error"):
                        to_cache = {
                            k: v for k, v in section_data.items()
                            if k != "build_time_seconds"
                        }
                        _cache_readiness_payload(
                            file_name, slug, to_cache, build_time
                        )
                preloaded[slug] = section_data

        response = {"success": True, "sections_cached": sections_cached}
        for slug in _READINESS_SECTION_BUILDERS:
            response[_READINESS_SECTION_RESPONSE_KEYS[slug]] = preloaded[slug]

        metric_time_log.info("Readiness report built in %.2f seconds", time.time() - start_time)
        return jsonify(ensure_json_serializable(response))
    except Exception as e:
        metric_time_log.error("Readiness report error: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "Could not build the readiness report."}), 200


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
    section_errors: dict[str, str] = {}
    visualizations: dict[str, dict] = {}
    start_time = time.time()
    try:
        for slug in _READINESS_SECTION_BUILDERS:
            data, section_elapsed, from_cache = _get_or_build_readiness_section(
                slug, file_info
            )
            if isinstance(data, dict) and data.get("error"):
                # A section that cannot be computed is a normal outcome for
                # small or unusual datasets. Record it and keep going so the
                # export still carries the sections that did compute.
                section_errors[slug] = data["error"]
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
            section_errors=section_errors,
        )
        pdf_bytes = render_readiness_report_pdf(context)
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
        # Raised by web.readiness.pdf when WeasyPrint or the logo asset is missing.
        metric_time_log.error("Readiness report PDF error: %s", e, exc_info=True)
        return jsonify({
            "success": False,
            "message": "PDF export is not available on this server. Check that WeasyPrint and its "
                       "native dependencies (pango, cairo, gdk-pixbuf) are installed; details are in the server log.",
        }), 500
    except Exception as e:
        metric_time_log.error("Readiness report PDF error: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "Could not generate the PDF report."}), 500


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
                return jsonify({"error": "Error computing the data structure metrics."}), 200

            duration_ms = (time.time() - start_time) * 1000
            span.set_attribute("metric.duration_ms", duration_ms)
            metric_time_log.info("Data Structure completed in %.2f seconds", time.time() - start_time)
            return store_result("metrics.data_structure", final_dict)

    return get_result_or_default("metrics.data_structure", file_path, file_name)


# ---------------------------------------------------------------------------
# Understandability
# ---------------------------------------------------------------------------

@metrics_bp.route("/variable-unit-validation", methods=["GET", "POST"])
def variable_unit_validation():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = build_file_info(file_path, file_name, file_type)

    if request.method == "POST":
        start_time = time.time()
        metric_time_log.info("Variable Unit Validation request started")
        with trace_metric(
            "variable_unit_validation",
            "understandability",
            file_name=file_name,
            file_type=file_type,
        ):
            try:
                raw_metadata = request.form.get("variable_unit_metadata")
                metadata = json.loads(raw_metadata) if raw_metadata else None
                unit_result = calculate_variable_unit_validation(file_info, metadata)
            except Exception as e:
                metric_time_log.error("Variable Unit Validation error: %s", e, exc_info=True)
                final_dict["Variable Unit Validation"] = {
                    "Error": f"{type(e).__name__}: {e}",
                    "Description": (
                        "Verifies that every logical variable has a recognized unit, "
                        "is dimensionless, or is marked not applicable."
                    ),
                }
            else:
                final_dict["Variable Unit Validation"] = unit_result

        metric_time_log.info(
            "Variable Unit Validation completed in %.2f seconds",
            time.time() - start_time,
        )
        return store_result("metrics.variable_unit_validation", final_dict)

    return get_result_or_default(
        "metrics.variable_unit_validation",
        file_path,
        file_name,
    )


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
        with trace_metric("fairness", "fairness_bias", file_name=file_name, file_type=file_type) as span:
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
                with trace_metric("correlation_analysis", "impact_on_ai", file_name=file_name, file_type=file_type) as span:
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
                        return jsonify({"trigger": "correlationError", "error": corr_dict["Message"]}), 200
                    final_dict["Correlations Analysis Categorical"] = corr_dict[
                        "Correlations Analysis Categorical"
                    ]
                    final_dict["Correlations Analysis Numerical"] = corr_dict[
                        "Correlations Analysis Numerical"
                    ]
                    metric_time_log.info("Correlations took %.2f seconds", time.time() - t0)
                    duration = time.time() - start_time
                    metric_time_log.info("Correlation Analysis completed in %.2f seconds", duration)
                    span.set_attribute("metric.duration_ms", duration * 1000)
                return store_result("metrics.correlation_analysis", final_dict)
            else:
                return jsonify({"message": "No correlation analysis selected"}), 200
        except Exception as e:
            metric_time_log.error("Correlation Analysis error: %s", e, exc_info=True)
            return jsonify(
                {
                    "trigger": "correlationError",
                    "error": "An internal error occurred while running correlation analysis.",
                }
            ), 200

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
            with trace_metric("feature_relevance", "impact_on_ai", file_name=file_name, file_type=file_type) as span:
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
                    return jsonify({
                        "trigger": "correlationError",
                        "error": "An internal error occurred while cleaning data.",
                    }), 200

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
                    return jsonify({
                        "trigger": "correlationError",
                        "error": "Pearson correlation calculation failed. Please try again.",
                    }), 200

                try:
                    t0 = time.time()
                    plot_features_result = plot_features.delay(correlations, target)
                    f_plot = plot_features_result.get(timeout=METRIC_CELERY_TIMEOUT)
                    metric_time_log.info("Feature Relevance — plot generation took %.2f seconds", time.time() - t0)
                    if f_plot is None:
                        return jsonify({"trigger": "correlationError", "error": "Visualization generation failed"}), 200
                except Exception as e:
                    metric_time_log.error("Feature Relevance — plot generation error: %s", e, exc_info=True)
                    return jsonify(
                        {"trigger": "correlationError", "error": "Visualization generation failed"}
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
        with trace_metric("class_imbalance", "fairness_bias", file_name=file_name, file_type=file_type) as span:
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
            span.set_attribute("metric.duration_ms", duration * 1000)
        return store_result("metrics.class_imbalance", final_dict)

    return get_result_or_default("metrics.class_imbalance", file_path, file_name)


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
        with trace_metric("privacy_preservation", "data_governance", file_name=file_name, file_type=file_type) as span:
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
                        file_info,
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
                        file_info,
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
        with trace_metric("hipaa_compliance", "data_governance", file_name=data_file_name, file_type=data_file_type) as span:
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
                return jsonify({"error": "An internal error has occurred."}), 500

            duration = time.time() - start_time
            metric_time_log.info("HIPAA Compliance Evaluation completed in %.2f seconds", duration)
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
            if not file.filename.endswith((".json", ".jsonld")):
                return jsonify({"error": "Invalid file format. Please upload a JSON or JSON-LD file."}), 400

            json_data = file.read()
            from aidrin.structured_data_metrics.fair_metadata import (
                normalize_fair_standard,
            )

            # Canonicalize so readiness cache/fingerprint match CLI standard names.
            metadata_type = normalize_fair_standard(
                request.form.get("metadata type", "") or "auto"
            )
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
            except json.JSONDecodeError:
                metric_time_log.warning("Invalid metadata JSON payload", exc_info=True)
                return jsonify({"error": "Invalid JSON payload"}), 400

            with trace_metric("fair_assessment", "understandability") as span:
                try:
                    result = _run_fair_assessment(data_dict, metadata_type)
                except ValueError:
                    if metadata_type == "auto":
                        return jsonify({"error": "Could not detect the metadata standard. Choose it in the Metadata type list."}), 400
                    return jsonify({"error": "Unknown metadata type"}), 400
                except json.JSONDecodeError:
                    metric_time_log.warning(
                        "Invalid JSON structure during FAIR assessment",
                        exc_info=True,
                    )
                    return jsonify({"error": "Invalid JSON payload"}), 400

                duration = time.time() - start_time
                metric_time_log.info("FAIR Assessment completed in %.2f seconds", duration)
                span.set_attribute("metric.duration_ms", duration * 1000)
                span.set_attribute("metadata.type", metadata_type)
                span.set_attribute("metadata.detected", result["Standard"]["Name"])

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
