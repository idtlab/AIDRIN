import base64
import io
import logging

import matplotlib.pyplot as plt
import pandas as pd
from pandas.tseries.frequencies import to_offset
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)

PRIMARY = "#4485F4"
NEGATIVE = "#D86470"
TEXT = "#6b7280"


@shared_task(bind=True, ignore_result=False)
def temporal_completeness(self: Task, timestamp_column, frequency, file_info):
    """% of expected time intervals (between min and max timestamps) present.

    Parameters
    ----------
    timestamp_column : str
        Column holding datetime values.
    frequency : str
        Pandas frequency string, e.g. "D" daily, "h" hourly, "W" weekly.
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.
    """
    try:
        logger.info("Temporal Completeness task started")
        df = read_file(file_info)
        if timestamp_column not in df.columns:
            return {"Error": f"Column not found: {timestamp_column!r}"}
        series = df[timestamp_column].dropna()
        if series.empty:
            return {"Error": "No non-null timestamps in column"}

        # Sanity check: don't let pd.to_datetime silently misinterpret a numeric
        # column as nanoseconds-since-epoch.  If the column was already parsed as
        # datetime, accept it; otherwise require an object / string column that
        # we can attempt to parse.
        if pd.api.types.is_datetime64_any_dtype(series):
            timestamps = series
        elif pd.api.types.is_numeric_dtype(series):
            return {"Error": (
                f"Column {timestamp_column!r} is numeric (dtype {series.dtype}). "
                f"This metric expects datetime values (e.g. '2024-01-15'). "
                f"If the column holds Unix epoch timestamps, convert it to datetime "
                f"first (e.g. pd.to_datetime(col, unit='s'))."
            )}
        else:
            try:
                timestamps = pd.to_datetime(series, errors="raise")
            except Exception as exc:
                return {"Error": f"Could not parse {timestamp_column!r} as datetime: {exc}"}
        # Compute completeness arithmetically instead of materializing the full
        # set of expected intervals — that explodes for fine frequencies over
        # long spans (microseconds over an hour = billions of points) and hangs.
        #
        # Every observed timestamp is snapped onto the frequency grid (floored
        # for fixed offsets, bucketed into periods for variable ones), so every
        # present timestamp is by construction an expected grid point:
        #   present  = distinct grid buckets that contain data
        #   expected = total grid buckets between the min and max bucket
        try:
            offset = to_offset(frequency)
        except (ValueError, TypeError) as exc:
            return {"Error": f"Invalid frequency {frequency!r}: {exc}"}
        if offset is None:
            return {"Error": f"Invalid frequency {frequency!r}."}

        try:
            step_ns = offset.nanos          # fixed-length offset (s, min, h, D, ms, …)
            is_fixed = True
        except ValueError:
            is_fixed = False                # variable-length offset (W, ME, QE, YE)

        if is_fixed:
            floored = timestamps.dt.floor(frequency)
            tmin, tmax = floored.min(), floored.max()
            expected_count = int((tmax - tmin).value // step_ns) + 1
            present_buckets = set(floored)
            present = len(present_buckets)
            stride = max(1, expected_count // 365)
            sampled = [tmin + pd.Timedelta(int(i) * step_ns, unit="ns")
                       for i in range(0, expected_count, stride)]
            colors = [PRIMARY if t in present_buckets else NEGATIVE for t in sampled]
        else:
            PERIOD_ALIAS = {"W": "W", "ME": "M", "M": "M",
                            "QE": "Q", "Q": "Q", "YE": "Y", "Y": "Y"}
            palias = PERIOD_ALIAS.get(str(frequency).upper().split("-")[0], frequency)
            try:
                periods = timestamps.dt.to_period(palias)
            except (ValueError, TypeError) as exc:
                return {"Error": f"Invalid frequency {frequency!r}: {exc}"}
            grid = pd.period_range(periods.min(), periods.max(), freq=palias)
            expected_count = len(grid)
            present_buckets = set(periods)
            present = len(present_buckets)
            stride = max(1, expected_count // 365)
            sampled_periods = grid[::stride]
            colors = [PRIMARY if p in present_buckets else NEGATIVE for p in sampled_periods]
            sampled = sampled_periods.to_timestamp()

        if expected_count <= 0:
            return {"Error": "No expected intervals for the given frequency."}
        pct = (present / expected_count) * 100

        # Timeline strip — one vertical tick per sampled interval, blue if
        # present, red if missing (down-sampled to <=365 ticks above).
        fig_height = 1.6
        fig, ax = plt.subplots(figsize=(10, fig_height))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")
        ax.scatter(sampled, [0] * len(sampled), c=colors, marker="|", s=300, linewidths=1.5)
        ax.set_yticks([])
        ax.set_ylim(-0.5, 0.5)
        ax.set_xlabel(f"Expected {frequency}-frequency intervals "
                      f"({len(sampled)} of {expected_count} shown)",
                      fontsize=10, color=TEXT)
        ax.tick_params(axis="x", colors=TEXT, labelsize=8)
        for spine in ("top", "left", "right"):
            ax.spines[spine].set_visible(False)
        ax.spines["bottom"].set_color(TEXT)
        fig.autofmt_xdate()
        fig.tight_layout(pad=0.5)

        img_buf = io.BytesIO()
        fig.savefig(img_buf, format="png", dpi=150, transparent=True)
        img_buf.seek(0)
        img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")
        plt.close(fig)

        logger.info("Temporal Completeness task completed: %.4f%%", pct)
        return {
            "Temporal Completeness (%)": float(pct),
            "Frequency": frequency,
            "Expected intervals": int(expected_count),
            "Present intervals": int(present),
            "Range start": str(timestamps.min()),
            "Range end": str(timestamps.max()),
            "Temporal Completeness Visualization": img_base64,
            "Description": (
                f"Percentage of expected {frequency}-frequency intervals present "
                f"between {timestamps.min()} and {timestamps.max()}."
            ),
        }

    except SoftTimeLimitExceeded:
        logger.error("Temporal Completeness task timed out")
        raise Exception("Temporal Completeness task timed out.")
