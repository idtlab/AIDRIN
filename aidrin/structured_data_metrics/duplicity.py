from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def calculate_duplicates(self: Task, file_info):
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
