import logging

from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=False)
def row_level_completeness(self: Task, required_columns, file_info):
    """% of rows whose required columns are *all* non-null.

    Parameters
    ----------
    required_columns : list of str
        Rows missing any of these columns are counted as incomplete.
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.
    """
    try:
        logger.info("Row-Level Completeness task started")
        df = read_file(file_info)
        if not required_columns:
            return {"Error": "required_columns must not be empty"}
        missing = [c for c in required_columns if c not in df.columns]
        if missing:
            return {"Error": f"Columns not found in dataset: {missing}"}
        if len(df) == 0:
            return {"Error": "Dataset is empty"}
        complete = df[required_columns].dropna().shape[0]
        pct = (complete / len(df)) * 100
        logger.info("Row-Level Completeness task completed: %.4f%%", pct)
        return {
            "Row-Level Completeness (%)": float(pct),
            "Complete rows": int(complete),
            "Total rows": int(len(df)),
            "Description": "Percentage of rows where every required column is non-null.",
        }

    except SoftTimeLimitExceeded:
        logger.error("Row-Level Completeness task timed out")
        raise Exception("Row-Level Completeness task timed out.")
