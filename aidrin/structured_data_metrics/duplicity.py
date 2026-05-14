import logging

from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)


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
        # Calculate the proportion of duplicate values
        duplicate_proportions = file.duplicated().sum() / len(file)

        dup_dict["Duplicity scores"] = {
            "Overall duplicity of the dataset": duplicate_proportions
        }

        logger.info("Duplicity task completed: overall score=%.4f", duplicate_proportions)
        return dup_dict
    except SoftTimeLimitExceeded:
        logger.error("Duplicity task timed out")
        raise Exception("Duplicity task timed out.")
