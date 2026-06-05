"""Shared utilities used across web route blueprints."""

import io
import base64
import json
import logging
import os
import time
import uuid

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from flask import current_app, jsonify, redirect, request, session, url_for

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session / user helpers
# ---------------------------------------------------------------------------

def get_current_user_id():
    """Get current user ID from session or generate one."""
    if "user_id" not in session:
        session["user_id"] = str(uuid.uuid4())
    return session["user_id"]


# ---------------------------------------------------------------------------
# Multi-file store + active-file shim
# ---------------------------------------------------------------------------

def _files_store_path():
    """Path of the current user's persisted file-list JSON.

    Stored on disk (not in the in-memory cache or the session cookie) so the
    batch survives app restarts — e.g. the Flask dev-server auto-reload that
    fires when a custom metric writes a .py into the package — and is shared
    across worker processes. Lives outside UPLOAD_FOLDER so the upload cleanup
    doesn't remove it.
    """
    base = os.path.dirname(current_app.config["UPLOAD_FOLDER"])
    store_dir = os.path.join(base, "filelists")
    os.makedirs(store_dir, exist_ok=True)
    return os.path.join(store_dir, f"{get_current_user_id()}.json")


def get_uploaded_files():
    """Return the persisted list of uploaded files for the current user."""
    try:
        with open(_files_store_path()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def save_uploaded_files(files):
    """Persist the file list to disk (survives restarts; not in the cookie)."""
    try:
        with open(_files_store_path(), "w") as fh:
            json.dump(files, fh)
    except OSError:
        logger.warning("Could not persist uploaded file list", exc_info=True)


def get_active_file():
    """Return the active file entry dict, or None."""
    active_id = session.get("active_file_id")
    for f in get_uploaded_files():
        if f["id"] == active_id:
            return f
    return None


def set_active_file(file_id):
    """Make file_id active and mirror its identity into the legacy session keys.

    Returns True if the file exists, else False. For a Globus entry, also
    repopulates the globus_* keys that the remote path + cache still read.
    """
    entry = next((f for f in get_uploaded_files() if f["id"] == file_id), None)
    if entry is None:
        return False
    session["active_file_id"] = file_id
    session["uploaded_file_path"] = entry["path"]
    session["uploaded_file_name"] = entry["name"]
    session["uploaded_file_type"] = entry["type"]
    if entry.get("source") == "globus":
        session["globus_file_path"] = entry["path"]
        session["globus_file_name"] = entry["name"]
        session["globus_file_type"] = entry["type"]
        session["globus_endpoint_id"] = entry.get("endpoint_id")
    else:
        for k in ("globus_file_path", "globus_file_name",
                  "globus_file_type", "globus_endpoint_id"):
            session.pop(k, None)
    return True


def clear_uploaded_files():
    """Remove the file list and all active/legacy file pointers."""
    try:
        os.remove(_files_store_path())
    except OSError:
        pass
    for k in ("active_file_id", "uploaded_file_path", "uploaded_file_name",
              "uploaded_file_type", "globus_file_path", "globus_file_name",
              "globus_file_type", "globus_endpoint_id"):
        session.pop(k, None)


def generate_metric_cache_key(file_name, metric_type, **params):
    """Generate a user-specific cache key for metrics."""
    user_id = get_current_user_id()
    file_token = session.get("active_file_id") or file_name
    cache_parts = [f"user:{user_id}", f"file:{file_token}"]

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
    file_token = session.get("active_file_id") or (
        session.get("uploaded_file_name") or session.get("globus_file_name") or "unknown"
    )
    user_key = f"user:{user_id}:file:{file_token}:{metric_short}"
    current_app.TEMP_RESULTS_CACHE[user_key] = {
        "data": formatted_final_dict,
        "timestamp": time.time(),
    }

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


def summary_histograms(df):
    """Generate base64-encoded KDE distribution plots for all numeric columns."""
    text_color = "#6b7280"
    curve_color = "#4485F4"

    line_graphs = {}
    for column in df.select_dtypes(include="number").columns:
        fig, ax = plt.subplots(figsize=(4, 3))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")

        sns.kdeplot(df[column], bw_adjust=0.5, ax=ax, color=curve_color)

        ax.set_xlabel("Values", fontsize=10, color=text_color)
        ax.set_ylabel("Density", fontsize=10, color=text_color)
        ax.tick_params(colors=text_color, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(text_color)
        fig.tight_layout(pad=0.5)

        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format="png", dpi=150, transparent=True)
        img_buffer.seek(0)
        encoded_img = base64.b64encode(img_buffer.read()).decode("utf-8")

        # Store as _light for backward compat with JS picker
        line_graphs[f"{column}_light"] = encoded_img
        plt.close(fig)
        img_buffer.close()

    return line_graphs
