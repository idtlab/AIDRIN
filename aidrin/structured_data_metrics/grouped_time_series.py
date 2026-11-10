"""Audit independent sequences in input order; never sort or repair source data."""

import math
import re
from collections import Counter
from datetime import date, datetime
from statistics import median_low

import numpy as np
import pandas as pd
from celery import shared_task

from aidrin.file_handling.file_parser import read_file


DESCRIPTION = (
    "Checks each group's timestamps in input order. Numeric time uses the declared "
    "input unit; datetime cadence and duration use seconds. Relative times do not "
    "establish synchronization. No sorting, interpolation, or repair is applied."
)
_ISO_DATE_PREFIX = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[Tt ]|$)")
_TIME_UNIT_SUFFIX = re.compile(r"_(?:s|secs?|seconds?|ms|milliseconds?|us|microseconds?|ns|nanoseconds?|minutes?|hours?|utc)$")
_TIME_COLUMN_NAMES = {
    "t", "time", "timestamp", "time_stamp", "datetime", "date", "elapsed", "elapsed_time", "sample_time", "event_time",
    "epoch", "unix_time", "recorded_at",
}
_FORMAT_SAMPLE_LIMIT = 256
_INTERVAL_ROUNDOFF = 1e-9


def _number(value, name, positive=False):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or (result <= 0 if positive else result < 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'non-negative'}")
    return result


def _integer(value, name, minimum):
    number = _number(value, name)
    if not number.is_integer() or number < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(number)


def _json_number(value):
    # JSON numbers above this bound cannot retain integer precision in browser
    # clients. Keep exact decimal representations for endpoints and intervals.
    if isinstance(value, int) and abs(value) > 2**53 - 1:
        return str(value)
    return value


def _finite(value):
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _scalar(value):
    if isinstance(value, np.generic):
        return _scalar(value.item())
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _time(value, time_kind, *, iso_dates_only=False):
    """Return comparable time, display time, timezone awareness, or diagnostic."""
    if not pd.api.types.is_scalar(value):
        return None, None, None, "invalid_time"
    if pd.isna(value):
        return None, None, None, "missing_time"
    if isinstance(value, (bool, np.bool_)):
        return None, None, None, "invalid_time"
    if time_kind == "numeric":
        if isinstance(value, (datetime, date, pd.Timestamp, np.datetime64)):
            return None, None, None, "invalid_time"
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            return None, None, None, "invalid_time"
        if not math.isfinite(parsed):
            return None, None, None, "nonfinite_time"
        # A reader can preserve integer tick units exactly, even beyond 2**53.
        # Mixed columns may expose those same ticks as decimal strings.
        if isinstance(value, (int, np.integer)):
            parsed = int(value)
        elif isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
            parsed = int(value)
        return parsed, _json_number(parsed), None, None
    # Numeric epoch values must not silently become nanoseconds since epoch.
    if not isinstance(value, (str, datetime, date, pd.Timestamp, np.datetime64)):
        return None, None, None, "invalid_time"
    if iso_dates_only and isinstance(value, str) and not _ISO_DATE_PREFIX.match(value.strip()):
        return None, None, None, "invalid_time"
    try:
        parsed = pd.Timestamp(value)
        if pd.isna(parsed):
            return None, None, None, "missing_time"
        return parsed.value, parsed.isoformat(), parsed.tzinfo is not None, None
    except (TypeError, ValueError, OverflowError):
        return None, None, None, "invalid_time"


def _detect_time_kind(series):
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "datetime"
    if series.empty or pd.api.types.is_any_real_numeric_dtype(series.dtype):
        return "numeric"

    detected = None
    stride = (len(series) + _FORMAT_SAMPLE_LIMIT - 1) // _FORMAT_SAMPLE_LIMIT
    for value in series.iloc[::stride]:
        if _time(value, "numeric")[3] is None:
            kind = "numeric"
        elif _time(value, "datetime", iso_dates_only=True)[3] is None:
            kind = "datetime"
        else:
            continue
        if detected is not None and detected != kind:
            raise ValueError("Time column contains both numbers and dates. Choose Numeric time or Date and time to continue.")
        detected = kind
    if detected is None:
        raise ValueError("Could not detect the time format. Choose Numeric time or Date and time to continue.")
    return detected


def suggest_time_column(frame, features, datetime_features, text_features):
    """Suggest an unambiguous time column using metadata and at most 16 sampled rows."""
    if frame.empty or not frame.columns.is_unique:
        return None
    sampled_rows = slice(None, None, max(1, (len(frame) + 15) // 16))
    candidates = {name for name in datetime_features if isinstance(name, str)}
    for name in features:
        if isinstance(name, str):
            base = _TIME_UNIT_SUFFIX.sub("", re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_"))
            if base in _TIME_COLUMN_NAMES or base.endswith(("_timestamp", "_datetime")):
                candidates.add(name)
    if len(candidates) == 1:
        name = next(iter(candidates))
        sample = frame[name].iloc[sampled_rows]
        try:
            kind = _detect_time_kind(sample)
        except ValueError:
            return None
        if any(_time(value, kind, iso_dates_only=True)[3] is None for value in sample):
            return name
    if candidates or len(text_features) > 16:
        return None

    # Without a name or dtype hint, require distinct, fully dated text values.
    for name in text_features:
        if not isinstance(name, str):
            continue
        times = [_time(value, "datetime", iso_dates_only=True) for value in frame[name].iloc[sampled_rows]]
        valid = {value for value, _, _, error in times if error is None}
        if len(valid) >= 2 and all(error in {None, "missing_time"} for _, _, _, error in times):
            candidates.add(name)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _group_positions(frame, group_columns):
    if not group_columns:
        return [], () if frame.empty else (range(len(frame)),)
    # Positions refer to input order and do not depend on index labels.
    work = frame[group_columns].reset_index(drop=True)
    assigned = work.notna().all(axis=1)
    unassigned = [int(i) for i in work.index[~assigned]]
    return unassigned, work[assigned].groupby(group_columns, sort=False, observed=True).groups.values()


def suggest_sample_interval(frame, group_columns, timestamp_column, time_kind):
    """Find a common interval from a bounded, in-order sample of one file."""
    if time_kind not in {"auto", "numeric", "datetime"}:
        raise ValueError("Choose a valid time format.")
    times = frame[timestamp_column]
    auto_detect = time_kind == "auto"
    if auto_detect:
        time_kind = _detect_time_kind(times)
    _, groups = _group_positions(frame, group_columns)
    candidates = []
    matching_intervals = 0
    for positions in groups:
        previous = awareness = None
        deltas = []
        for position in positions:
            value, _, aware, error = _time(times.iloc[position], time_kind, iso_dates_only=auto_detect)
            if error or (awareness is not None and awareness != aware):
                previous = None
                continue
            awareness = aware
            if previous is not None:
                delta = _interval_delta(value, previous, time_kind)
                if delta > 0 and _finite(delta):
                    deltas.append(delta)
            previous = value
        if not deltas:
            continue
        candidate = median_low(deltas)
        matching = sum(math.isclose(delta, candidate, rel_tol=_INTERVAL_ROUNDOFF) for delta in deltas)
        if matching * 3 < len(deltas) * 2:
            raise ValueError("The sampled timestamps have uneven spacing. Enter the expected interval manually.")
        candidates.append(candidate)
        matching_intervals += matching
    if matching_intervals < 2:
        raise ValueError("There are too few usable intervals in the sample. Enter the expected interval manually.")
    candidate = median_low(candidates)
    if any(not math.isclose(interval, candidate, rel_tol=_INTERVAL_ROUNDOFF) for interval in candidates):
        raise ValueError("The sampled series have different intervals. Enter the expected interval manually.")
    return candidate, time_kind


def _interval_delta(value, previous, time_kind):
    delta = value - previous
    return delta / 1e9 if time_kind == "datetime" else delta


def calculate_grouped_time_series(
    file_info, group_columns, timestamp_column, expected_cadence,
    time_kind="numeric", tolerance=0.0, max_findings=100,
    expected_count=None, expected_duration=None,
):
    """Return exact findings and full counts per group, with capped detail lists.

    Row positions are zero-based positions in the parsed input, excluding the
    header. Checks compare adjacent rows within each group without sorting.
    Invalid time rows break adjacency; checks never bridge them. Duplicate
    detection also finds non-adjacent repeats. Pass ``group_columns=None`` to
    check the entire table as one sequence. ``time_kind='auto'`` detects numeric
    or ISO-style date and time values. ``max_findings=0`` is unlimited.
    """
    if isinstance(group_columns, str):
        group_columns = [c.strip() for c in group_columns.split(",") if c.strip()]
    if group_columns is None:
        group_columns = []
    elif not isinstance(group_columns, (list, tuple)) or not group_columns:
        raise ValueError("group_columns must contain at least one column")
    group_columns = list(group_columns)
    if any(not isinstance(c, str) or not c for c in group_columns) or len(set(group_columns)) != len(group_columns):
        raise ValueError("group_columns must contain distinct non-empty column names")
    if not isinstance(timestamp_column, str) or not timestamp_column or timestamp_column in group_columns:
        raise ValueError("timestamp_column must be a column separate from group_columns")
    if time_kind not in {"numeric", "datetime", "auto"}:
        raise ValueError("time_kind must be numeric, datetime, or auto")
    cadence = _number(expected_cadence, "expected_cadence", positive=True)
    tolerance = _number(tolerance, "tolerance")
    if tolerance >= cadence / 2:
        raise ValueError("tolerance must be less than half expected_cadence")
    max_findings = _integer(max_findings, "max_findings", 0)
    if expected_count is not None:
        expected_count = _integer(expected_count, "expected_count", 1)
    if expected_duration is not None:
        expected_duration = _number(expected_duration, "expected_duration")

    frame = read_file(file_info)
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique:
        raise ValueError("Input must be a table with unique column names")
    missing = [c for c in group_columns + [timestamp_column] if c not in frame.columns]
    if missing:
        raise ValueError(f"Columns not found: {missing}")
    for column in group_columns:
        if not frame[column].map(pd.api.types.is_scalar).all():
            raise ValueError(f"Group column must contain scalar keys: {column}")

    times = frame[timestamp_column]
    auto_detect = time_kind == "auto"
    if auto_detect:
        time_kind = _detect_time_kind(times)

    groups = []
    unassigned, positions_by_group = _group_positions(frame, group_columns)
    total_counts = Counter({"missing_group_key": len(unassigned)} if unassigned else {})
    for positions in positions_by_group:
        keys = {c: _scalar(frame[c].iloc[positions[0]]) for c in group_columns}
        group = _audit_group(times, positions, keys, time_kind, cadence, tolerance, max_findings,
                             expected_count, expected_duration, iso_dates_only=auto_detect)
        groups.append(group)
        total_counts.update(group["finding_counts"])
    return {
        "format": "aidrin.grouped-time-series",
        "version": 1,
        "Description": DESCRIPTION,
        "parameters": {
            "group_columns": group_columns, "timestamp_column": timestamp_column,
            "time_kind": time_kind, "expected_cadence": cadence, "tolerance": tolerance,
            "max_findings": max_findings, "expected_count": expected_count,
            "expected_duration": expected_duration, "row_position_base": 0,
            "comparison_relative_tolerance": _INTERVAL_ROUNDOFF,
        },
        "summary": {
            "total_rows": len(frame), "group_count": len(groups),
            "groups_with_findings": sum(bool(g["finding_counts"]) for g in groups),
            "unassigned_rows": len(unassigned), "finding_counts": dict(total_counts),
        },
        "unassigned_row_positions": unassigned[:max_findings] if max_findings else unassigned,
        "unassigned_rows_truncated": bool(max_findings and len(unassigned) > max_findings),
        "groups": groups,
    }


def _audit_group(series, positions, keys, time_kind, cadence, tolerance, cap, expected_count, expected_duration, *, iso_dates_only):
    counts = Counter()
    findings = []

    def record(kind, **detail):
        counts[kind] += 1
        if not cap or len(findings) < cap:
            findings.append({"kind": kind, **detail})

    seen = {}
    previous = None
    valid = []
    awareness = None
    evaluated = 0
    for position in positions:
        value, display, aware, error = _time(series.iloc[position], time_kind, iso_dates_only=iso_dates_only)
        if error:
            record(error, row_position=int(position))
            previous = None
            continue
        if time_kind == "datetime":
            if awareness is None:
                awareness = aware
            elif aware != awareness:
                record("mixed_timezone_awareness", row_position=int(position), time=display)
                previous = None
                continue
        valid.append((value, display))
        if value in seen:
            record("duplicate_time", row_position=int(position), first_row_position=seen[value], time=display)
        else:
            seen[value] = int(position)
        if previous is not None:
            left, left_display, left_position = previous
            delta = _interval_delta(value, left, time_kind)
            interval = {"from_row_position": left_position, "to_row_position": int(position),
                        "from_time": left_display, "to_time": display, "delta": _json_number(delta)}
            evaluated += 1
            if not _finite(delta):
                record("nonfinite_interval", **{k: v for k, v in interval.items() if k != "delta"})
            elif delta < 0:
                record("out_of_order", **interval)
            elif delta > 0 and not math.isclose(delta, cadence, rel_tol=1e-9, abs_tol=tolerance):
                if delta > cadence:
                    # Only infer a missing-sample count when endpoints lie on
                    # the declared cadence grid within tolerance.
                    missing_count = None
                    if isinstance(delta, int) and cadence.is_integer():
                        # Avoid float division rounding a large integer tick
                        # interval before deriving the missing-sample count.
                        integer_cadence = int(cadence)
                        steps, remainder = divmod(delta, integer_cadence)
                        if remainder * 2 > integer_cadence:
                            steps += 1
                        grid_interval = steps * integer_cadence
                        matches = remainder == 0 or (
                            _finite(grid_interval) and
                            math.isclose(delta, grid_interval, rel_tol=1e-9, abs_tol=tolerance)
                        )
                        if steps >= 2 and matches:
                            missing_count = steps - 1
                    else:
                        ratio = delta / cadence
                        if math.isfinite(ratio):
                            steps = round(ratio)
                            if steps >= 2 and math.isclose(delta, steps * cadence, rel_tol=1e-9, abs_tol=tolerance):
                                missing_count = steps - 1
                    record("cadence_gap", estimated_missing_samples=_json_number(missing_count), **interval)
                else:
                    record("cadence_short", **interval)
        previous = (value, display, int(position))

    if len(valid) < 2:
        record("insufficient_valid_times", valid_time_count=len(valid))
    observed_duration = None
    if valid:
        span = max(t[0] for t in valid) - min(t[0] for t in valid)
        observed_duration = span / 1e9 if time_kind == "datetime" else span
        if not _finite(observed_duration):
            record("nonfinite_duration")
            observed_duration = None
    if expected_count is not None and len(positions) != expected_count:
        record("count_mismatch", expected=expected_count, observed=len(positions))
    if expected_duration is not None and (
        observed_duration is None or not math.isclose(observed_duration, expected_duration, rel_tol=1e-9, abs_tol=tolerance)
    ):
        record("duration_mismatch", expected=expected_duration, observed=_json_number(observed_duration))
    return {
        "group": keys, "row_count": len(positions), "valid_time_count": len(valid),
        "unique_time_count": len(seen), "evaluated_adjacent_intervals": evaluated,
        "first_time": valid[0][1] if valid else None, "last_time": valid[-1][1] if valid else None,
        "observed_duration": _json_number(observed_duration),
        "time_reference": ("relative_or_unspecified" if time_kind == "numeric" else
                           "timezone_aware" if awareness else "timezone_unspecified"),
        "finding_counts": dict(counts), "findings": findings,
        "findings_truncated": sum(counts.values()) > len(findings),
    }


@shared_task(ignore_result=False)
def grouped_time_series(file_info, group_columns, timestamp_column, expected_cadence,
                        time_kind="numeric", tolerance=0.0, max_findings=100, expected_count=None, expected_duration=None):
    return calculate_grouped_time_series(file_info, group_columns, timestamp_column, expected_cadence,
                                         time_kind, tolerance, max_findings, expected_count, expected_duration)
