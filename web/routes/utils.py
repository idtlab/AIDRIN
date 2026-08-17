"""Shared utilities used across web route blueprints."""

import io
import base64
import logging
import os
import re
import time
import uuid

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from flask import current_app, jsonify, redirect, request, session, url_for

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path confinement
# ---------------------------------------------------------------------------

def confine_to_upload_folder(file_path):
    """Return ``file_path`` resolved, iff it lives inside ``UPLOAD_FOLDER``.

    Dataset paths supplied over the web (via the Flask session) flow into
    ``file_parser``'s ``os.stat``/``os.path.exists``/``tempfile``/``os.replace``
    calls. This is the path-traversal barrier (CWE-22) for those values: the
    path is canonicalised with ``os.path.realpath`` and rejected unless it stays
    within the configured upload directory, so a forged/tampered session cookie
    cannot steer file operations at arbitrary locations on disk.

    Returns the canonical path on success, or ``""`` for a missing or
    out-of-bounds path (callers treat an empty path as "no file").
    """
    if not file_path:
        return ""
    base = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    resolved = os.path.realpath(file_path)
    try:
        contained = resolved == base or os.path.commonpath([resolved, base]) == base
    except ValueError:
        # Different drives / mixed path kinds — not inside the upload folder.
        contained = False
    if not contained:
        logger.warning("Rejected dataset path outside upload folder: %s", file_path)
        return ""
    return resolved


# ---------------------------------------------------------------------------
# Semantic column-role inference
# ---------------------------------------------------------------------------
#
# Metrics historically keyed off the pandas dtype (``select_dtypes``), which
# mislabels numeric columns that are really categorical codes (e.g. a class
# label ``flavor`` with values -1/1/2/5/21) or identifiers (e.g. a near-unique
# ``jetIndex``). Those get meaningless means, KDE plots, and correlations.
#
# ``infer_column_roles`` assigns each column a *semantic role* — one of
# ``continuous``, ``categorical``, or ``identifier`` — from dtype + cardinality
# (+ a light column-name hint for ids). The result is a suggestion the user can
# override; ``overrides`` takes precedence over the heuristic.

VALID_ROLES = ("continuous", "categorical", "identifier")

# Cardinality thresholds (fractions are of the row count).
# A near-unique integer column reads as an identifier.
_ID_UNIQUE_RATIO = 0.98
# An id-like name needs at least this spread to be treated as an identifier.
_ID_NAME_MIN_RATIO = 0.10
# ... and enough distinct values that near-uniqueness is meaningful
# (tiny datasets are trivially unique).
_ID_MIN_UNIQUE = 50
# A column is categorical when it has at most this many distinct values ...
_CATEGORICAL_MAX_UNIQUE = 20
# ... AND distinct/rows is below this (guards tiny datasets where every value
# is trivially distinct).
_CATEGORICAL_MAX_RATIO = 0.50

_ID_NAME_TOKENS = {"id", "idx", "index", "key", "uid", "guid", "uuid", "pk"}


def _looks_like_id_name(name) -> bool:
    """True when a column name's leading/trailing token looks like an identifier."""
    # Split camelCase then snake/space/dash: "eventIndex" -> ["event", "index"].
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name))
    parts = [p.lower() for p in re.split(r"[_\s\-]+", spaced) if p]
    if not parts:
        return False
    return parts[-1] in _ID_NAME_TOKENS or parts[0] in _ID_NAME_TOKENS


def infer_column_roles(df, overrides=None):
    """Return ``{column: role}`` where role is continuous/categorical/identifier.

    ``overrides`` (``{column: role}``) wins over the heuristic; unknown columns
    or invalid role strings in ``overrides`` are ignored.
    """
    roles = {}
    n = len(df)
    for col in df.columns:
        series = df[col]
        dtype = series.dtype

        if not pd.api.types.is_numeric_dtype(dtype) or pd.api.types.is_bool_dtype(dtype):
            roles[col] = "categorical"
            continue

        nunique = int(series.nunique(dropna=True))
        ratio = nunique / n if n else 0.0
        is_int = pd.api.types.is_integer_dtype(dtype)

        if is_int and nunique >= _ID_MIN_UNIQUE and ratio >= _ID_UNIQUE_RATIO:
            roles[col] = "identifier"
        elif (
            is_int
            and nunique >= _ID_MIN_UNIQUE
            and _looks_like_id_name(col)
            and ratio >= _ID_NAME_MIN_RATIO
        ):
            roles[col] = "identifier"
        elif nunique <= _CATEGORICAL_MAX_UNIQUE and ratio <= _CATEGORICAL_MAX_RATIO:
            roles[col] = "categorical"
        else:
            roles[col] = "continuous"

    if overrides:
        for col, role in overrides.items():
            if col in roles and role in VALID_ROLES:
                roles[col] = role

    return roles


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def build_file_info(file_path, file_name, file_type, selected_keys=None):
    """Build a file_info tuple, embedding HDF5 dataset keys when needed.

    Celery workers do not have Flask session context, so multi-dataset HDF5
    files must carry ``selected_keys`` in the tuple for background tasks.

    The path is confined to the upload folder here so every ``read_file`` fed
    from a session value passes through the path-traversal barrier.
    """
    file_path = confine_to_upload_folder(file_path)
    if file_type == ".h5":
        if selected_keys is None:
            try:
                selected_keys = session.get("selected_keys") or []
            except RuntimeError:
                selected_keys = []
        if isinstance(selected_keys, str):
            selected_keys = [key.strip() for key in selected_keys.split(",") if key.strip()]
        elif not isinstance(selected_keys, list):
            selected_keys = []
        if selected_keys:
            return (file_path, file_name, file_type, list(selected_keys))
    return (file_path, file_name, file_type)


def load_dataframe(file_info):
    """Read a file into a DataFrame, normalizing failures.

    ``read_file`` returns a DataFrame on success, or ``None`` / an error-message
    string on failure. This wrapper collapses those failure modes into a single
    ``(df, message)`` shape so route handlers can surface a clean error instead
    of crashing when they call DataFrame methods on a non-DataFrame value.

    Returns
    -------
    tuple
        ``(DataFrame, None)`` on success, or ``(None, message)`` on failure.
    """
    result = read_file(file_info)
    if isinstance(result, pd.DataFrame):
        return result, None
    raw = result if isinstance(result, str) else None
    if raw:
        # Keep the full, verbose detail in the logs; show the user a short message.
        logger.error("File read failed: %s", raw)
    return None, _friendly_read_error(raw, file_info)


def _friendly_read_error(raw, file_info):
    """Translate read_file's raw failure into a short, user-facing message.

    The full technical detail is preserved in the server logs by the caller;
    only this concise message is shown in the UI.
    """
    file_type = ""
    if isinstance(file_info, (list, tuple)) and len(file_info) >= 3 and file_info[2]:
        file_type = str(file_info[2]).lstrip(".").upper()
    label = f"{file_type} file" if file_type else "file"

    text = (raw or "").lower()
    if "usable engine" in text or "pyarrow" in text or "fastparquet" in text:
        return (
            "Parquet files can't be read because the server is missing the "
            "'pyarrow' package."
        )
    if "file not found" in text:
        return "The uploaded file could not be found. Please upload it again."
    return (
        f"The {label} could not be read. It may be empty, corrupted, or in an "
        "unexpected format."
    )


# ---------------------------------------------------------------------------
# Session / user helpers
# ---------------------------------------------------------------------------

def get_current_user_id():
    """Get current user ID from session or generate one."""
    if "user_id" not in session:
        session["user_id"] = str(uuid.uuid4())
    return session["user_id"]


def generate_metric_cache_key(file_name, metric_type, **params):
    """Generate a user-specific cache key for metrics."""
    user_id = get_current_user_id()
    cache_parts = [f"user:{user_id}", f"file:{file_name}"]

    if metric_type == "dp":
        features = params.get("features", [])
        epsilon = params.get("epsilon", 0.1)
        cache_parts.append(f"dp:features:{', '.join(sorted(features))}:epsilon:{epsilon}")

    elif metric_type == "single":
        id_feature = params.get("id_feature", "")
        qis = params.get("qis", [])
        cache_parts.append(f"single:id:{id_feature}:qis:{', '.join(sorted(qis))}")

    elif metric_type == "multiple":
        id_feature = params.get("id_feature", "")
        qis = params.get("qis", [])
        cache_parts.append(f"multiple:id:{id_feature}:qis:{', '.join(sorted(qis))}")

    elif metric_type == "kanon":
        qis = params.get("qis", [])
        cache_parts.append(f"kanon:qis:{', '.join(sorted(qis))}")

    elif metric_type == "ldiv":
        qis = params.get("qis", [])
        sensitive = params.get("sensitive", "")
        cache_parts.append(f"ldiv:qis:{', '.join(sorted(qis))}:sensitive:{sensitive}")

    elif metric_type == "tclose":
        qis = params.get("qis", [])
        sensitive = params.get("sensitive", "")
        cache_parts.append(f"tclose:qis:{', '.join(sorted(qis))}:sensitive:{sensitive}")

    elif metric_type == "entropy":
        qis = params.get("qis", [])
        cache_parts.append(f"entropy:qis:{', '.join(sorted(qis))}")

    elif metric_type == "classimbalance":
        classes = params.get("classes", "")
        dist_metric = params.get("dist_metric", "EU")
        cache_parts.append(f"classimbalance:classes:{classes}:dist_metric:{dist_metric}")

    elif metric_type == "summarystats":
        selected_keys = params.get("selected_keys", [])
        cache_parts.append(f"summarystats:keys:{', '.join(sorted(selected_keys))}")

    return "|".join(cache_parts)


def is_metric_cache_valid(cache_entry):
    """Check if a metric cache entry is still valid based on expiry time."""
    current_time = time.time()
    expires_at = cache_entry.get("expires_at", 0)
    is_valid = current_time < expires_at
    logger.debug("Cache validation - Current time: %s, Expires at: %s, Is valid: %s", current_time, expires_at, is_valid)
    return is_valid


def clear_all_user_cache():
    """Clear ALL cache entries for the current user."""
    user_id = get_current_user_id()
    keys_to_remove = [
        key for key in current_app.TEMP_RESULTS_CACHE
        if key.startswith(f"user:{user_id}")
    ]
    for key in keys_to_remove:
        current_app.TEMP_RESULTS_CACHE.pop(key, None)
    logger.info("User %s ALL cache cleared: Removed %d entries", user_id, len(keys_to_remove))
    return len(keys_to_remove)


def manage_cache_size(max_cache_size=100):
    """Remove oldest entries if cache exceeds max_cache_size."""
    if len(current_app.TEMP_RESULTS_CACHE) > max_cache_size:
        items_to_remove = int(max_cache_size * 0.2)
        keys_to_remove = list(current_app.TEMP_RESULTS_CACHE.keys())[:items_to_remove]
        for key in keys_to_remove:
            current_app.TEMP_RESULTS_CACHE.pop(key, None)
        logger.info("Cache cleanup: Removed %d old entries", len(keys_to_remove))


# ---------------------------------------------------------------------------
# Result store / retrieve helpers
# ---------------------------------------------------------------------------

def store_result(metric, final_dict):
    """Store computed metric results in the cache and redirect to the metric page."""
    formatted_final_dict = ensure_json_serializable(format_dict_values(final_dict))
    results_id = uuid.uuid4().hex
    current_app.TEMP_RESULTS_CACHE[results_id] = {"data": formatted_final_dict}

    # Also store a persistent user-scoped copy for the cache info page
    user_id = get_current_user_id()
    metric_short = metric.rsplit(".", 1)[-1] if "." in metric else metric
    file_name = session.get("uploaded_file_name") or session.get("globus_file_name") or "unknown"
    user_key = f"user:{user_id}:file:{file_name}:{metric_short}"
    current_app.TEMP_RESULTS_CACHE[user_key] = {
        "data": formatted_final_dict,
        "timestamp": time.time(),
    }

    if request.args.get("return_type") == "json":
        return jsonify(formatted_final_dict)

    return redirect(
        url_for(metric, results_id=results_id, return_type=request.args.get("return_type"))
    )


def get_result_or_default(metric, uploaded_file_path, uploaded_file_name):
    """Load results from cache (if present) and render the metric template.

    ``metric`` is a Flask endpoint name (e.g. ``"metrics.data_quality"``).  The
    template is resolved from the final segment after the last ``"."``.
    """
    results_id = request.args.get("results_id")
    return_type = request.args.get("return_type")
    formatted_final_dict = None

    if results_id and results_id in current_app.TEMP_RESULTS_CACHE:
        entry = current_app.TEMP_RESULTS_CACHE.pop(results_id)
        formatted_final_dict = entry["data"]

    if return_type == "json":
        if formatted_final_dict is not None:
            return jsonify(formatted_final_dict)
        return jsonify({"message": "No results available"}), 200

    # All metric pages are now served by the inspector — redirect there
    return redirect(url_for("core.inspector"))


# ---------------------------------------------------------------------------
# Data formatting helpers
# ---------------------------------------------------------------------------

def format_dict_values(d):
    """Recursively round numeric values in a dict to 2 decimal places."""
    formatted_dict = {}
    for key, value in d.items():
        if isinstance(value, dict):
            formatted_dict[key] = format_dict_values(value)
        elif isinstance(value, (int, float)):
            formatted_dict[key] = round(value, 2)
        else:
            formatted_dict[key] = value
    return formatted_dict


def ensure_json_serializable(obj):
    """Recursively convert non-native types (NumPy/Pandas) to JSON-safe Python types."""
    import numpy as np

    if isinstance(obj, dict):
        return {str(k): ensure_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [ensure_json_serializable(item) for item in obj]
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    elif pd.isna(obj):
        return None
    return obj


def _fig_to_base64(fig):
    img_buffer = io.BytesIO()
    fig.savefig(img_buffer, format="png", dpi=150, transparent=True)
    img_buffer.seek(0)
    encoded = base64.b64encode(img_buffer.read()).decode("utf-8")
    plt.close(fig)
    img_buffer.close()
    return encoded


def summary_histograms(df, columns=None):
    """Generate base64-encoded KDE distribution plots.

    ``columns`` restricts the plots to the given columns (used to plot only
    columns whose semantic role is *continuous*); when ``None`` it falls back
    to every numeric column for backward compatibility.
    """
    text_color = "#6b7280"
    curve_color = "#4485F4"

    if columns is None:
        columns = list(df.select_dtypes(include="number").columns)

    line_graphs = {}
    for column in columns:
        fig, ax = plt.subplots(figsize=(4, 3))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")

        sns.kdeplot(df[column], bw_adjust=0.5, cut=0, ax=ax, color=curve_color)

        ax.set_xlabel("Values", fontsize=10, color=text_color)
        ax.set_ylabel("Density", fontsize=10, color=text_color)
        ax.tick_params(colors=text_color, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(text_color)
        fig.tight_layout(pad=0.5)

        # Store as _light for backward compat with JS picker
        line_graphs[f"{column}_light"] = _fig_to_base64(fig)

    return line_graphs


def categorical_bars(df, columns, max_categories=20):
    """Generate base64-encoded bar charts of value counts for categorical columns.

    KDE curves are meaningless for discrete/coded columns, so categorical
    columns (including numeric codes like ``flavor``) get a value-count bar
    chart instead. High-cardinality columns show only the top ``max_categories``.
    """
    text_color = "#6b7280"
    bar_color = "#4485F4"

    bars = {}
    for column in columns:
        counts = df[column].value_counts(dropna=True).head(max_categories)
        if counts.empty:
            continue

        fig, ax = plt.subplots(figsize=(4, 3))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")

        ax.bar([str(i) for i in counts.index], counts.values, color=bar_color)

        ax.set_xlabel("Category", fontsize=10, color=text_color)
        ax.set_ylabel("Count", fontsize=10, color=text_color)
        ax.tick_params(colors=text_color, labelsize=8)
        if len(counts) > 6:
            for label in ax.get_xticklabels():
                label.set_rotation(45)
                label.set_ha("right")
        for spine in ax.spines.values():
            spine.set_color(text_color)
        fig.tight_layout(pad=0.5)

        bars[f"{column}_light"] = _fig_to_base64(fig)

    return bars
