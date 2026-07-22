import logging

import pandas as pd
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file
from aidrin.file_handling.hashable_utils import hashable_frame

logger = logging.getLogger(__name__)


def _clean_value(value):
    """Normalize a group-key value for JSON output (NaN/NaT -> None)."""
    if isinstance(value, tuple):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


@shared_task(bind=True, ignore_result=False)
def duplicity_by_features(self: Task, features, file_info, top_n=10):
    """Measure duplicate rows considering only the selected feature columns.

    Parameters
    ----------
    features : list of str
        Columns to compare when detecting duplicate rows.
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.
    top_n : int
        Maximum number of duplicate groups to include in the detailed
        breakdown (largest groups first).
    """
    try:
        logger.info("Duplicity by Features task started")
        if not features:
            return {"Error": "features must not be empty"}

        df = read_file(file_info)
        missing = [c for c in features if c not in df.columns]
        if missing:
            return {"Error": f"Columns not found in dataset: {missing}"}
        if len(df) == 0:
            return {"Error": "Dataset is empty"}

        hashable_df = hashable_frame(df[features])

        duplicate_mask = hashable_df.duplicated(keep="first")
        duplicate_count = int(duplicate_mask.sum())
        total_rows = int(len(df))
        duplicate_percentage = (duplicate_count / total_rows) * 100

        group_sizes = (
            hashable_df.groupby(features, dropna=False)
            .size()
            .sort_values(ascending=False)
        )
        group_sizes = group_sizes[group_sizes > 1].head(top_n)

        duplicate_groups = []
        for key, count in group_sizes.items():
            key_tuple = key if isinstance(key, tuple) else (key,)
            feature_values = {
                feature: _clean_value(value)
                for feature, value in zip(features, key_tuple)
            }
            duplicate_groups.append(
                {"Feature values": feature_values, "Row count": int(count)}
            )

        logger.info(
            "Duplicity by Features task completed: count=%d, pct=%.2f%%",
            duplicate_count, duplicate_percentage,
        )
        return {
            "Duplicate count": duplicate_count,
            "Duplicate percentage": float(duplicate_percentage),
            "Total rows": total_rows,
            "Duplicate groups": duplicate_groups,
            "Description": (
                "Duplicate rows computed using only the selected feature columns. "
                f"The duplicate groups shown below are the top {top_n} largest "
                "groups, sorted by row count."
            ),
        }
    except SoftTimeLimitExceeded:
        logger.error("Duplicity by Features task timed out")
        raise Exception("Duplicity by Features task timed out.")
