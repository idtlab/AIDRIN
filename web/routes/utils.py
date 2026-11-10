"""Shared utilities used across web route blueprints."""

import io
import base64
import logging
import math
import os
import re
import threading
import time
import uuid

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import gaussian_kde
from flask import current_app, jsonify, redirect, request, session, url_for

from aidrin.file_handling.custom_loader import CustomLoaderError
from aidrin.file_handling.file_parser import (
    _SELECTION_FILE_TYPES,
    ReaderReturnedNone,
    read_file,
)

logger = logging.getLogger(__name__)

# Matplotlib's pyplot API is process-global and not thread-safe. Serialize chart
# builders that share this process so concurrent requests cannot cross-contaminate figures.
MATPLOTLIB_PLOT_LOCK = threading.Lock()


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
    files must carry ``selected_keys`` in the tuple for background tasks, and
    an active upload custom loader must carry ``custom_loader_spec`` the same way.

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
            # Only HDF5 has a key picker writing session["selected_keys"];
            # reading it for another format would apply a stale HDF5
            # selection to this source.
            try:
                selected_keys = session.get("selected_keys") or [] if file_type == ".h5" else []
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


def _finite_values(series):
    """Numeric values with NaN *and* infinities removed.

    ``dropna()`` keeps infinities and they reach matplotlib as an infinite axis
    range, so a single ``inf`` in a column raised ``ValueError`` out of
    ``ax.hist`` and took the whole Data Overview down with it. seaborn used to
    filter them before this module began drawing its own charts.
    """
    values = pd.to_numeric(pd.Series(series), errors="coerce").to_numpy(dtype=float)
    return values[np.isfinite(values)]


# Beyond this nothing is distinguishable on a chart, and the caller clamps far
# below it; the ceiling only stops a pathological rule result from overflowing.
_MAX_RULE_BINS = 10_000


def _auto_bin_count(values):
    """numpy's "auto" rule as a count, without materializing the bin edges.

    ``np.histogram_bin_edges(bins="auto")`` builds the complete edge array
    before any cap can be applied to it. One far outlier makes the rule ask for
    billions of edges: 1000 values in [0, 1] plus a single 1e9 wants about 1e10
    of them, roughly 80 GB, which the web process would try to allocate on
    every uncached overview request. The count is only arithmetic, so derive it
    and let the caller clamp before anything is allocated.
    """
    n = values.size
    sturges = int(np.ceil(np.log2(n))) + 1 if n > 1 else 1
    span = float(values.max() - values.min())
    if span <= 0:
        return sturges

    first, third = np.percentile(values, [25, 75])
    iqr = float(third - first)
    if iqr <= 0:
        return sturges

    # Freedman-Diaconis; numpy's "auto" takes whichever of the two is finer.
    fd_width = 2.0 * iqr / n ** (1.0 / 3.0)
    if fd_width <= 0:
        return sturges
    return max(sturges, int(min(span / fd_width, _MAX_RULE_BINS)))


def _reflected_kde(values, bw_adjust=0.5, grid_size=256):
    """Estimate a density that keeps all of its mass inside ``[min, max]``.

    A Gaussian kernel centred near an edge spills roughly half its weight past
    the end of the data. ``cut=0`` clips that weight away rather than putting it
    back, so the curve sags at both ends and claims the extreme values are
    rarer than they are: on a column sampled on an even grid the end density
    reads about half the middle, and the curve integrates to ~0.91 instead of 1
    (issue #253). Mirroring every point about both bounds folds the lost weight
    back inward, which restores both the shape and the total mass.

    Returns ``(grid, density)``, or ``None`` when the column cannot support an
    estimate (fewer than two values, or no spread).
    """
    x = _finite_values(values)
    if x.size < 2:
        return None
    low, high = x.min(), x.max()
    spread = x.std(ddof=1)
    if high <= low or not np.isfinite(spread) or spread <= 0:
        return None

    # Scott's rule, matching the bandwidth seaborn used, so smoothing is
    # unchanged and only the boundary behaviour differs.
    bandwidth = bw_adjust * x.size ** (-1.0 / 5.0) * spread
    if bandwidth <= 0:
        return None

    augmented = np.concatenate([x, 2 * low - x, 2 * high - x])
    kde = gaussian_kde(augmented, bw_method=bandwidth / augmented.std(ddof=1))
    grid = np.linspace(low, high, grid_size)
    # The sample was tripled; undo that so the result is a density again.
    return grid, kde(grid) * 3.0


def _bin_count(values, floor=30, cap=50):
    """Choose a histogram bin count that does not alias against the data.

    Values recorded on a regular grid (a depth profile sampled every 200 m, a
    daily counter) alias against an arbitrary bin width: unless the width is a
    whole multiple of the grid step, neighbouring bins take four points and then
    five, and a perfectly uniform column renders as a comb while its curve
    renders flat. Two views of one column must not support different
    conclusions, so a regular grid picks a count it divides evenly.
    """
    values = _finite_values(values)
    if values.size == 0:
        return 1

    unique = np.unique(values)  # np.unique returns them sorted
    nunique = unique.size
    if nunique <= 1:
        return 1
    if nunique <= cap:
        # Fewer distinct values than bins: one bar each, so a coded column
        # (a 1-5 rating) gets five bars rather than fifty slivers.
        return int(nunique)

    step = np.diff(unique)
    if step.size and np.allclose(step, step[0], rtol=1e-6):
        divisors = [b for b in range(floor, cap + 1) if nunique % b == 0]
        if divisors:
            return max(divisors)

    return int(min(max(_auto_bin_count(values), floor), cap, nunique))


def _style_distribution_axes(ax, ylabel, text_color="#6b7280"):
    """Apply the shared axis styling for both distribution renderings."""
    ax.set_xlabel("Values", fontsize=10, color=text_color)
    ax.set_ylabel(ylabel, fontsize=10, color=text_color)
    ax.tick_params(colors=text_color, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(text_color)


def _encode_figure(fig, dpi):
    """Render *fig* to a transparent base64 PNG and close it."""
    img_buffer = io.BytesIO()
    fig.savefig(img_buffer, format="png", dpi=dpi, transparent=True)
    img_buffer.seek(0)
    encoded_img = base64.b64encode(img_buffer.read()).decode("utf-8")
    plt.close(fig)
    img_buffer.close()
    return encoded_img


def summary_histograms(df, figsize=(4, 3), dpi=150):
    """Generate base64-encoded KDE distribution plots for all numeric columns.

    Paired with :func:`continuous_bars`, which draws the same columns as a
    histogram; both emit a key per numeric column so the per-chart switch in the
    Data Overview never dead-ends on a card.
    """
    curve_color = "#4485F4"

    line_graphs = {}
    with MATPLOTLIB_PLOT_LOCK:
        for column in df.select_dtypes(include="number").columns:
            fig, ax = plt.subplots(figsize=figsize)
            fig.patch.set_alpha(0)
            ax.set_facecolor("none")

            estimate = _reflected_kde(pd.to_numeric(df[column], errors="coerce"))
            if estimate is not None:
                grid, density = estimate
                ax.plot(grid, density, color=curve_color, linewidth=1.5)
                # A density axis that does not start at zero magnifies a flat
                # curve into a feature: on an evenly sampled column matplotlib
                # would scale a 5% ripple to fill the panel, so the curve
                # disagreed with its own histogram (issue #253).
                ax.set_ylim(bottom=0)

            _style_distribution_axes(ax, "Density")
            fig.tight_layout(pad=0.5)

            # Store as _light for backward compat with JS picker
            line_graphs[f"{column}_light"] = _encode_figure(fig, dpi)

    return line_graphs


def continuous_bars(df, figsize=(4, 3), dpi=150):
    """Generate base64-encoded histograms for all numeric columns.

    The bar twin of :func:`summary_histograms`: same columns, same keys, so the
    Data Overview can offer both and let the reader switch per chart (issue
    #212). A KDE smooths over gaps in data that is continuous by dtype but
    effectively discrete, which a histogram shows plainly.
    """
    bar_color = "#4485F4"

    bar_graphs = {}
    with MATPLOTLIB_PLOT_LOCK:
        for column in df.select_dtypes(include="number").columns:
            fig, ax = plt.subplots(figsize=figsize)
            fig.patch.set_alpha(0)
            ax.set_facecolor("none")

            values = _finite_values(df[column])
            if values.size:
                ax.hist(
                    values,
                    bins=_bin_count(values),
                    color=bar_color,
                    edgecolor="white",
                    linewidth=0.5,
                )

            _style_distribution_axes(ax, "Count")
            fig.tight_layout(pad=0.5)

            bar_graphs[f"{column}_light"] = _encode_figure(fig, dpi)

    return bar_graphs


def categorical_distribution_charts(df, top_n=10):
    """Generate base64-encoded pie charts for categorical columns.

    Shows the top *top_n* values per column; remaining values are grouped
    into an "Other" slice when applicable.
    """
    text_color = "#6b7280"
    palette = [
        "#4485F4", "#34A853", "#FBBC05", "#EA4335", "#9C27B0",
        "#00ACC1", "#FF7043", "#8D6E63", "#78909C", "#AB47BC",
    ]
    charts = {}

    cat_cols = df.select_dtypes(include=["object", "string", "category"]).columns
    with MATPLOTLIB_PLOT_LOCK:
        for column in cat_cols:
            series = df[column].dropna()
            if len(series) == 0:
                continue

            vc = series.value_counts()
            if len(vc) > top_n:
                top = vc.head(top_n)
                other_count = int(vc.iloc[top_n:].sum())
                labels = [str(v) for v in top.index]
                sizes = [int(v) for v in top.values]
                if other_count > 0:
                    labels.append("Other")
                    sizes.append(other_count)
            else:
                labels = [str(v) for v in vc.index]
                sizes = [int(v) for v in vc.values]

            n_slices = len(labels)
            colors = [palette[i % len(palette)] for i in range(n_slices)]

            fig, ax = plt.subplots(figsize=(5, 5))
            fig.patch.set_alpha(0)

            wedges, _, autotexts = ax.pie(
                sizes,
                labels=None,
                autopct=lambda pct: f"{pct:.1f}%" if pct >= 4 else "",
                colors=colors,
                startangle=90,
                pctdistance=0.75,
                textprops={"color": text_color, "fontsize": 8},
            )
            for t in autotexts:
                t.set_fontsize(7)

            ax.legend(
                wedges,
                labels,
                loc="center left",
                bbox_to_anchor=(1, 0.5),
                fontsize=8,
                frameon=False,
                labelcolor=text_color,
            )
            ax.set_title(str(column), fontsize=10, color=text_color, pad=8)
            fig.tight_layout()

            img_buffer = io.BytesIO()
            fig.savefig(img_buffer, format="png", dpi=150, transparent=True, bbox_inches="tight")
            img_buffer.seek(0)
            charts[str(column)] = base64.b64encode(img_buffer.read()).decode("utf-8")
            plt.close(fig)
            img_buffer.close()

    return charts
