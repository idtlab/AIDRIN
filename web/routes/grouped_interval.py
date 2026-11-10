"""Bounded local samples for the Grouped Time Series form."""

import hashlib
import math
import time

import pandas as pd
from flask import current_app

from aidrin.file_handling.file_parser import read_file
from aidrin.structured_data_metrics.grouped_time_series import detect_time_kind, suggest_sample_interval, suggest_time_column
from web.routes.utils import get_current_user_id, is_metric_cache_valid, manage_cache_size


_SAMPLE_ROWS = 256
_SAMPLE_FILES = 6
_TIME_BUDGET = 1.0
_TIMED_OUT = "A quick suggestion timed out. Enter the expected interval manually."


def _sample_key(file_info):
    identity = hashlib.sha256(repr(file_info).encode("utf-8")).hexdigest()
    return f"user:{get_current_user_id()}:grouped_interval_sample:{identity}"


def remember_interval_sample(file_info, frame):
    """Keep a small sample of an already parsed table for readers without a fast preview."""
    if file_info[2] == ".csv" and len(file_info) == 3:
        return
    sample = frame.iloc[:_SAMPLE_ROWS, :64]
    if not sample.columns.is_unique or sample.memory_usage(index=False, deep=True).sum() > 256 * 1024:
        return
    # Copy individual scalar values so a slice of an Arrow-backed column does
    # not retain the buffers for the whole uploaded table.
    values = {}
    for name, series in sample.items():
        column = series.tolist()
        if all(pd.api.types.is_scalar(value) for value in column):
            values[name] = column
    preview = pd.DataFrame(values, dtype=object)
    cache = current_app.TEMP_RESULTS_CACHE
    now = time.time()
    cache[_sample_key(file_info)] = {"data": preview, "timestamp": now, "expires_at": now + 1800}
    manage_cache_size()


def _read_interval_sample(file_info, columns):
    entry = current_app.TEMP_RESULTS_CACHE.get(_sample_key(file_info))
    if entry and is_metric_cache_valid(entry):
        if columns is None:
            return entry["data"]
        if all(column in entry["data"] for column in columns):
            return entry["data"][columns]
    return read_file(file_info, columns=columns, sample_rows=_SAMPLE_ROWS)


def _sample_files(file_infos):
    total = len(file_infos)
    if total > _SAMPLE_FILES:
        return [file_infos[round(i * (total - 1) / (_SAMPLE_FILES - 1))] for i in range(_SAMPLE_FILES)]
    return file_infos


def preview_grouped_columns(file_infos):
    """Offer common columns from bounded previews of the selected tables."""
    deadline = time.monotonic() + _TIME_BUDGET
    common = None
    suggestions = []
    for file_info in _sample_files(file_infos):
        if time.monotonic() >= deadline:
            break
        frame = _read_interval_sample(file_info, None)
        if frame is None or not frame.columns.is_unique:
            continue
        columns = [name for name in frame.columns if isinstance(name, str)]
        common = columns if common is None else [name for name in common if name in columns]
        dates = [name for name in columns if pd.api.types.is_datetime64_any_dtype(frame[name].dtype)]
        text = [name for name in columns if pd.api.types.is_string_dtype(frame[name].dtype)]
        suggestions.append(suggest_time_column(frame, columns, dates, text))
    suggestion = suggestions[0] if suggestions and len(set(suggestions)) == 1 else None
    complete = len(suggestions) == len(file_infos)
    return {"columns": common, "suggested_time_column": suggestion if complete else None, "complete": complete}


def detect_grouped_timing(file_infos, group_columns, timestamp_column, time_kind, *, estimate_interval=True):
    """Detect format and cadence independently on bounded samples within files."""
    if not timestamp_column:
        raise ValueError("Choose a time column to suggest an interval.")
    if time_kind not in {"auto", "numeric", "datetime"}:
        raise ValueError("Choose a valid time format.")
    group_columns = group_columns or []
    if timestamp_column in group_columns or len(set(group_columns)) != len(group_columns):
        raise ValueError("Choose distinct series identifiers separately from the time column.")
    columns = [timestamp_column, *group_columns]
    deadline = time.monotonic() + _TIME_BUDGET
    total = len(file_infos)
    file_infos = _sample_files(file_infos)
    sampled = len(file_infos)

    format_used = interval = interval_error = None
    for file_info in file_infos:
        if time.monotonic() >= deadline:
            raise ValueError(_TIMED_OUT)
        frame = _read_interval_sample(file_info, columns)
        if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique or any(column not in frame for column in columns):
            raise ValueError("A quick sample of the selected columns is unavailable. Enter the expected interval manually.")
        kind = detect_time_kind(frame[timestamp_column]) if time_kind == "auto" else time_kind
        if format_used is not None and kind != format_used:
            raise ValueError("The sampled files use different time formats. Enter the expected interval manually.")
        format_used = kind
        if estimate_interval and interval_error is None:
            try:
                candidate = suggest_sample_interval(frame, group_columns, timestamp_column, kind, iso_dates_only=time_kind == "auto")
                if interval is not None and not math.isclose(candidate, interval, rel_tol=1e-9):
                    raise ValueError("The sampled files have different intervals. Enter the expected interval manually.")
                interval = interval or candidate
            except ValueError as exc:
                interval_error = str(exc)
        if time.monotonic() >= deadline:
            raise ValueError(_TIMED_OUT)
    result = {"time_kind": format_used, "sampled_files": sampled, "total_files": total}
    if interval_error:
        result["interval_error"] = interval_error
    elif interval is not None:
        result["interval"] = float(f"{interval:.12g}")
    return result
