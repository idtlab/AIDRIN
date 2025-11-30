from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
import numpy as np

from aidrin.file_handling.file_parser import read_file


def iterate_chunks(df, chunksize=50000):
    """Yield DataFrame chunks for any file type."""
    for start in range(0, len(df), chunksize):
        yield df.iloc[start:start + chunksize]


def row_to_key(row):
    """
    Convert a pandas Series row into a hashable, NaN-normalized tuple.

    - NaNs are mapped to a sentinel so that rows with NaNs in the same positions
      compare equal (matching pandas.duplicated behavior).
    """
    sentinel = "__NAN__"
    values = []
    for v in row:
        # Treats all NaN-like values as the same
        if isinstance(v, float) and np.isnan(v):
            values.append(sentinel)
        else:
            values.append(v)
    return tuple(values)


@shared_task(bind=True, ignore_result=False)
def duplicity(self: Task, file_info):
    try:
        df = read_file(file_info)

        if df is None:
            return {"Error": "File could not be read."}

        # Ensure column names are strings
        if hasattr(df, "columns"):
            df.columns = [str(col) for col in df.columns]

        total_duplicates = 0
        total_rows = 0

        # Global set to track unique row signatures across all chunks
        global_seen = set()

        for chunk in iterate_chunks(df):
            chunk_size = len(chunk)
            if chunk_size == 0:
                continue

            total_rows += chunk_size

            # Compute a normalized, hashable key for each row
            # This mirrors pandas.duplicated's "NA values are equal" behavior.
            for _, row in chunk.iterrows():
                key = row_to_key(row)
                if key in global_seen:
                    total_duplicates += 1
                else:
                    global_seen.add(key)

        # Avoid division by zero
        dup_score = total_duplicates / total_rows if total_rows > 0 else 0.0

        return {
            "Duplicity scores": {
                "Overall duplicity of the dataset": dup_score
            }
        }

    except SoftTimeLimitExceeded:
        raise Exception("Duplicity task timed out.")
    except Exception as e:
        return {"Error": f"Duplicity detection failed: {str(e)}"}
