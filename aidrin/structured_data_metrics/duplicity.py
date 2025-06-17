from celery import shared_task, Task
from aidrin.read_file import read_file
@shared_task(bind=True, ignore_result=False)
def duplicity(self: Task, file_info):
    file,_,_= read_file(file_info)
    dup_dict = {}
    # Calculate the proportion of duplicate values
    duplicate_proportions = (file.duplicated().sum() / len(file)) 
    
    dup_dict["Duplicity scores"]={'Overall duplicity of the dataset': duplicate_proportions}
    
    return dup_dict