"""Shared utilities used across web route blueprints."""

import logging
import math
import os
import re
import time
import uuid

import pandas as pd
from flask import current_app, jsonify, redirect, request, session, url_for

from aidrin.file_handling.custom_loader import CustomLoaderError
from aidrin.file_handling.file_parser import (
    _SELECTION_FILE_TYPES,
    ReaderReturnedNone,
    read_file,
)
from aidrin.report.charts import (  # noqa: F401 — re-export for existing web/tests imports
    MATPLOTLIB_PLOT_LOCK,
    _bin_count,
    _reflected_kde,
    categorical_distribution_charts,
    continuous_bars,
    summary_histograms,
)

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
# File loading
# ---------------------------------------------------------------------------

def build_file_info(file_path, file_name, file_type, selected_keys=None):
    """Build a file_info tuple, embedding HDF5 keys / custom loader when needed.

    Celery workers do not have Flask session context, so multi-dataset HDF5
    files, ROOT trees, and multi-array Zarr sources must carry ``selected_keys``
    in the tuple for background tasks, and an active upload custom loader must
    carry ``custom_loader_spec`` the same way.

    Tuple shapes:
      ``(path, name, type)``
      ``(path, name, type, selected_keys)``
      ``(path, name, type, loader_spec)``
      ``(path, name, type, selected_keys, loader_spec)``

    The path is confined to the upload folder here so every ``read_file`` fed
    from a session value passes through the path-traversal barrier.
    """
    file_path = confine_to_upload_folder(file_path)
    parts = [file_path, file_name, file_type]

    if file_type in _SELECTION_FILE_TYPES:
        if selected_keys is None:
            # HDF5 and ROOT pickers persist selections in the session.
            try:
                selected_keys = session.get("selected_keys") or [] if file_type in {".h5", ".root"} else []
            except RuntimeError:
                selected_keys = []
        if isinstance(selected_keys, str):
            selected_keys = [key.strip() for key in selected_keys.split(",") if key.strip()]
        elif not isinstance(selected_keys, list):
            selected_keys = []
        if selected_keys:
            parts.append(list(selected_keys))

    loader = None
    try:
        loader = session.get("custom_loader_spec")
    except RuntimeError:
        loader = None
    if isinstance(loader, str):
        loader = loader.strip() or None
    else:
        loader = None
    if loader:
        parts.append(loader)

    return tuple(parts)


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
    try:
        result = read_file(file_info)
    except ReaderReturnedNone as exc:
        # Formats that refuse an ambiguous input raise instead of returning
        # None (a multi-array Zarr store, and HDF5 once it joins that set).
        # Collapse it into the same failure shape as the rest of this wrapper,
        # which route handlers rely on, rather than letting it reach Flask.
        result = str(exc)
    except CustomLoaderError as exc:
        # The loader's message names the user's own error and holds no server
        # paths, so it is more useful than the generic read error.
        logger.error("Custom loader read failed: %s", exc)
        return None, describe_loader_error(exc, file_info[0], file_info[1])
    if isinstance(result, pd.DataFrame):
        return result, None
    raw = result if isinstance(result, str) else None
    if raw:
        # Keep the full, verbose detail in the logs; show the user a short message.
        logger.error("File read failed: %s", raw)
    return None, _friendly_read_error(raw, file_info)


def describe_loader_error(exc, file_path, display_name):
    """Show a custom loader error with the names the user uploaded, not the stored ones."""
    message = str(exc)
    if file_path:
        message = message.replace(os.path.basename(file_path), display_name or "the file")
    message = re.sub(r"Custom loader 'custom_loader_[0-9a-f]{32}\.py:load'", "Your custom loader", message)
    message = re.sub(r"custom_loader_[0-9a-f]{32}\.py", "loader.py", message)
    # The loader's own error stays in the server log (logged with its traceback).
    return message.split(" Original error: ")[0]


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
    if "selected keys" in text or "selection" in text or "multi_dataset" in text:
        # The file is readable; it just holds several datasets that cannot be
        # merged into one table. Saying "corrupted" here would be wrong.
        return (
            f"This {label} holds multiple datasets that cannot be combined into "
            "one table. Select one or more compatible datasets (same length) to "
            "analyze."
        )
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
    """Recursively round numeric values in a dict to 3 decimal places.

    Metric charts label their bars at three decimals, and this is what the
    table beside them renders, so the two must agree. Two decimals collapsed
    small-but-real scores to ``0.0`` in the table while the chart showed
    ``0.004`` (issue #211).
    """
    formatted_dict = {}
    for key, value in d.items():
        if isinstance(value, dict):
            formatted_dict[key] = format_dict_values(value)
        elif isinstance(value, (int, float)):
            formatted_dict[key] = round(value, 3)
        else:
            formatted_dict[key] = value
    return formatted_dict


def ensure_json_serializable(obj):
    """Recursively convert non-native types (NumPy/Pandas) to JSON-safe Python types.

    Non-finite floats (NaN, ±Inf) become ``None`` so ``json.dumps(..., allow_nan=False)``
    succeeds. Returning bare ``NaN`` breaks strict parsers (including ``response.json()``).
    """
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
    elif isinstance(obj, (np.floating, float)):
        value = float(obj)
        return value if math.isfinite(value) else None
    elif isinstance(obj, np.ndarray):
        return ensure_json_serializable(obj.tolist())
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    elif pd.isna(obj):
        return None
    return obj
