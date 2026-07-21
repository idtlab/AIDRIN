import logging

import numpy as np
import pandas as pd
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)


def _json_safe(value):
    """Normalize a single cell value for JSON output (NaN/NaT -> None, numpy -> native)."""
    if pd.isna(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


@shared_task(bind=True, ignore_result=False)
def constant_feature_count(self: Task, file_info):
    """Count columns that have a single distinct value.

    Null is treated as a value like any other: a column that is entirely
    null has one distinct value (null) and counts as constant, and a column
    with one real value plus some nulls has two distinct values (the value
    and null) and does not.

    Constant features carry no information and are candidates for removal.

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.

    Returns
    -------
    dict
        ``{"Constant feature count": int, "Total features": int,
        "Constant features": {column: value}}``
    """
    try:
        logger.info("Constant Feature Count task started")
        df = read_file(file_info)
        constant_features = {
            col: _json_safe(df[col].iloc[0])
            for col in df.columns
            if df[col].nunique(dropna=False) == 1
        }

        logger.info(
            "Constant Feature Count task completed: %d of %d features",
            len(constant_features), len(df.columns),
        )
        return {
            "Constant feature count": len(constant_features),
            "Total features": int(len(df.columns)),
            "Constant features": constant_features,
        }
    except SoftTimeLimitExceeded:
        logger.error("Constant Feature Count task timed out")
        raise Exception("Constant Feature Count task timed out.")
