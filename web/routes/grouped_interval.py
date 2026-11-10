"""Bounded local samples for the Grouped Time Series form."""

import hashlib
import math
import time

import pandas as pd
from flask import current_app

from aidrin.file_handling.file_parser import read_file
from aidrin.structured_data_metrics.grouped_time_series import suggest_sample_interval
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
    if entry and is_metric_cache_valid(entry) and all(column in entry["data"] for column in columns):
        return entry["data"][columns]
    return read_file(file_info, columns=columns, sample_rows=_SAMPLE_ROWS)


def suggest_interval(file_infos, group_columns, timestamp_column, time_kind):
    """Estimate a common interval from a few files, without comparing across file boundaries."""
    if not timestamp_column:
        raise ValueError("Choose a time column to suggest an interval.")
    group_columns = group_columns or []
    if timestamp_column in group_columns or len(set(group_columns)) != len(group_columns):
        raise ValueError("Choose distinct series identifiers separately from the time column.")
    columns = [timestamp_column, *group_columns]
    deadline = time.monotonic() + _TIME_BUDGET
    total = len(file_infos)
    sampled = min(total, _SAMPLE_FILES)
    if total > sampled:
        file_infos = [file_infos[round(i * (total - 1) / (sampled - 1))] for i in range(sampled)]

    suggestion = None
    for file_info in file_infos:
        if time.monotonic() >= deadline:
            raise ValueError(_TIMED_OUT)
        frame = _read_interval_sample(file_info, columns)
        if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique or any(column not in frame for column in columns):
            raise ValueError("A quick sample of the selected columns is unavailable. Enter the expected interval manually.")
        interval, kind = suggest_sample_interval(frame, group_columns, timestamp_column, time_kind)
        if time.monotonic() >= deadline:
            raise ValueError(_TIMED_OUT)
        if suggestion is not None and (kind != suggestion[1] or not math.isclose(interval, suggestion[0], rel_tol=1e-9)):
            raise ValueError("The sampled files have different intervals or time formats. Enter the expected interval manually.")
        suggestion = suggestion or (interval, kind)
    return {"interval": float(f"{suggestion[0]:.12g}"), "time_kind": suggestion[1], "sampled_files": sampled, "total_files": total}
