from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def duplicity(self: Task, file_info):
    """
    Calculate the duplicity metric for the dataset.

    Duplicity measures the proportion of duplicate rows in the dataset.
    A score of 0.0 means no duplicates, 1.0 means all rows are duplicates.

    Parameters
    ----------
    file_info : tuple
        (file_path, file_name, file_type) identifying the dataset file.

    Returns
    -------
    dict
        Dictionary containing the duplicity score and visualization.
    """

    try:
        file = read_file(file_info)
        dup_dict = {}
        # Calculate the proportion of duplicate values
        duplicate_proportions = file.duplicated().sum() / len(file)

        dup_dict["Duplicity scores"] = {
            "Overall duplicity of the dataset": duplicate_proportions
        }

        return dup_dict
    except SoftTimeLimitExceeded:
        raise Exception("Duplicity task timed out.")
