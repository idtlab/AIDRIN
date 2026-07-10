import logging

from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)


def _make_hashable(val):
    """Convert unhashable types (lists, dicts) to hashable equivalents."""
    if isinstance(val, list):
        return tuple(_make_hashable(v) for v in val)
    elif isinstance(val, dict):
        return tuple(sorted((k, _make_hashable(v)) for k, v in val.items()))
    return val


@shared_task(bind=True, ignore_result=False)
def duplicity(self: Task, file_info):
    """Measure the proportion of duplicate rows in a dataset.

    Reads the file and calculates what fraction of rows are exact duplicates
    of a preceding row (using :func:`pandas.DataFrame.duplicated`).

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.

    Returns
    -------
    dict
        ``{"Duplicity scores": {"Overall duplicity of the dataset": float}}``
        where the score is in ``[0, 1]`` (0 = no duplicates).
    """
    try:
        logger.info("Duplicity task started")
        file = read_file(file_info)
        dup_dict = {}

        # Check if any columns contain unhashable types (lists, dicts)
        # and convert them to hashable equivalents for duplicate detection
        hashable_file = file.copy()
        for col in hashable_file.columns:
            if hashable_file[col].dtype == object:
                # Check first non-null value to see if it's unhashable
                first_val = hashable_file[col].dropna().iloc[0] if not hashable_file[col].dropna().empty else None
                if isinstance(first_val, (list, dict)):
                    hashable_file[col] = hashable_file[col].apply(_make_hashable)

        # Calculate the proportion of duplicate values
        duplicate_proportions = hashable_file.duplicated().sum() / len(hashable_file)

        dup_dict["Duplicity scores"] = {
            "Overall duplicity of the dataset": duplicate_proportions
        }

        logger.info("Duplicity task completed: overall score=%.4f", duplicate_proportions)
        return dup_dict
    except SoftTimeLimitExceeded:
        logger.error("Duplicity task timed out")
        raise Exception("Duplicity task timed out.")
