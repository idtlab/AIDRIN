from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
import numpy as np
import pandas as pd

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def duplicity(self: Task, file_info):
    try:
        file = read_file(file_info)

        if file is None or not hasattr(file, "empty") or file.empty:
            return {
                "Duplicity scores": {
                    "Overall duplicity of the dataset": 0.0
                }
            }

        n_rows = len(file)
        n_cols = len(file.columns)

        if n_rows >= 2:
            dup = float(file.duplicated().sum() / n_rows)
            return {
                "Duplicity scores": {
                    "Overall duplicity of the dataset": dup
                }
            }

        numeric = file.select_dtypes(include=[np.number])

        if numeric.empty:
            vals = file.to_numpy().ravel()
            vals = vals[~pd.isna(vals)]
            total = int(vals.size)
            if total <= 1:
                dup = 0.0
            else:
                uniq = int(pd.unique(vals).size)
                dup = float(1.0 - (uniq / total))
            return {
                "Duplicity scores": {
                    "Overall duplicity of the dataset": dup
                }
            }

        vals = numeric.to_numpy().ravel()
        vals = vals[np.isfinite(vals)]
        total = int(vals.size)

        if total <= 1:
            dup = 0.0
        else:
            vals = np.round(vals, 6)
            uniq = int(pd.unique(vals).size)
            dup = float(1.0 - (uniq / total))

        return {
            "Duplicity scores": {
                "Overall duplicity of the dataset": dup
            }
        }

    except SoftTimeLimitExceeded:
        raise Exception("Duplicity task timed out.")

