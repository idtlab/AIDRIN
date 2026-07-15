import base64
import io
import logging

import matplotlib.pyplot as plt
import pandas as pd
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)

PRIMARY = "#4485F4"
NEGATIVE = "#D86470"
TEXT = "#6b7280"


@shared_task(bind=True, ignore_result=False)
def null_count_trend(self: Task, batch_column, target_columns, file_info):
    """Null counts for *target_columns* grouped by *batch_column*.

    Useful for spotting batches where data quality degraded.  When
    *target_columns* is empty, sums nulls across **all** other columns.

    Parameters
    ----------
    batch_column : str
        Column that groups rows into batches (e.g., ingest date, source ID).
    target_columns : list of str
        Columns to count nulls in. Leave empty to count across all other columns.
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.
    """
    try:
        logger.info("Null Count Trend task started")
        df = read_file(file_info)
        if batch_column not in df.columns:
            return {"Error": f"Column not found: {batch_column!r}"}

        # Guard: a per-batch chart only makes sense when there are a manageable
        # number of distinct batch values.  Picking a continuous column (e.g.
        # `age` or a high-resolution timestamp) would produce hundreds of
        # one-row "batches" that aren't useful to anyone.
        n_batches = df[batch_column].nunique(dropna=True)
        if n_batches > 50:
            return {"Error": (
                f"Column {batch_column!r} has {n_batches} distinct values — "
                f"too many for a per-batch view. Pick a column with fewer groups "
                f"(e.g. ingest date, source ID, batch label), or pre-bucket the "
                f"values."
            )}

        if target_columns:
            missing = [c for c in target_columns if c not in df.columns]
            if missing:
                return {"Error": f"target_columns not in dataset: {missing}"}
            cols = list(target_columns)
        else:
            cols = [c for c in df.columns if c != batch_column]

        if not cols:
            return {"Error": "No target columns to analyse"}

        # dropna=False so rows whose batch is itself null show up as a "<NaN>"
        # group instead of being silently excluded.
        grouped = df.groupby(batch_column, dropna=False)[cols].apply(
            lambda chunk: chunk.isnull().sum().sum()
        )
        trend = {("<NaN>" if pd.isna(k) else str(k)): int(v) for k, v in grouped.items()}

        # Bar chart of null counts per batch. Color the worst batch red so spikes
        # are obvious even at a glance.
        labels = list(trend.keys())
        counts = list(trend.values())
        n = len(labels)
        fig_height = max(3, n * 0.35)
        fig, ax = plt.subplots(figsize=(8, fig_height))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")
        max_count = max(counts) if counts else 0
        bar_colors = [
            NEGATIVE if max_count > 0 and v == max_count else PRIMARY
            for v in counts
        ]
        ax.barh(range(n), counts, color=bar_colors, height=0.7)
        ax.set_yticks(range(n))
        ax.set_yticklabels(labels, fontsize=9, color=TEXT)
        ax.set_xlabel("Total null cells", fontsize=10, color=TEXT)
        ax.tick_params(axis="x", colors=TEXT, labelsize=8)
        ax.invert_yaxis()
        for spine in ax.spines.values():
            spine.set_color(TEXT)
        for i, v in enumerate(counts):
            if v > 0:
                ax.text(v + max_count * 0.01, i, str(v),
                        va="center", fontsize=8, color=TEXT)
        fig.tight_layout(pad=0.5)

        img_buf = io.BytesIO()
        fig.savefig(img_buf, format="png", dpi=150, transparent=True)
        img_buf.seek(0)
        img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")
        plt.close(fig)

        logger.info("Null Count Trend task completed: %d batches", n)
        return {
            "Null counts by batch": trend,
            "Batch column": batch_column,
            "Target columns": cols,
            "Null Count Trend Visualization": img_base64,
            "Description": (
                "Total null cells per batch across the target columns. "
                "Spikes indicate batches with degraded data quality."
            ),
        }

    except SoftTimeLimitExceeded:
        logger.error("Null Count Trend task timed out")
        raise Exception("Null Count Trend task timed out.")
