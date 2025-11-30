import base64
import io

import matplotlib.pyplot as plt
import numpy as np
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


def iterate_chunks(df, chunksize=50000):
    """Yield DataFrame chunks for any file type."""
    for start in range(0, len(df), chunksize):
        yield df.iloc[start:start + chunksize]


@shared_task(bind=True, ignore_result=False)
def outliers(self: Task, file_info):
    try:
        # Reads the file
        df = read_file(file_info)

        if df is None:
            return {"Error": "File could not be read."}

        # Ensures column names are strings
        df.columns = [str(col) for col in df.columns]

        # Selects only numeric columns
        numeric_df = df.select_dtypes(include=[np.number])

        if numeric_df.empty:
            return {"Error": "No numerical features found in the dataset."}

        numeric_cols = list(numeric_df.columns)

        # Collects values for global quantile computation
        collected = {col: [] for col in numeric_cols}

        for chunk in iterate_chunks(numeric_df):
            for col in numeric_cols:
                collected[col].extend(chunk[col].dropna().tolist())

        # Handles fully empty columns
        for col in numeric_cols:
            if len(collected[col]) == 0:
                collected[col] = [np.nan]

        # Computes Q1, Q3, and IQR for each column
        stats = {}
        for col in numeric_cols:
            series = np.array(collected[col])
            if np.all(np.isnan(series)):
                stats[col] = (np.nan, np.nan, np.nan)
                continue

            q1 = np.nanpercentile(series, 25)
            q3 = np.nanpercentile(series, 75)
            IQR = q3 - q1
            stats[col] = (q1, q3, IQR)

        # Counts outliers across all chunks
        total_counts = {col: 0 for col in numeric_cols}
        outlier_counts = {col: 0 for col in numeric_cols}

        for chunk in iterate_chunks(numeric_df):
            for col in numeric_cols:
                col_data = chunk[col].dropna()
                total_counts[col] += len(col_data)

                q1, q3, IQR = stats[col]

                if np.isnan(IQR) or IQR == 0:
                    continue

                lower = q1 - 1.5 * IQR
                upper = q3 + 1.5 * IQR
                mask = (col_data < lower) | (col_data > upper)
                outlier_counts[col] += mask.sum()

        # Computes final outlier proportions
        proportions = {}
        for col in numeric_cols:
            if total_counts[col] == 0:
                proportions[col] = 0.0
            else:
                proportions[col] = outlier_counts[col] / total_counts[col]

        # Computes overall outlier score
        valid_scores = [v for v in proportions.values() if not np.isnan(v)]
        overall_score = float(np.mean(valid_scores)) if valid_scores else 0.0

        proportions["Overall outlier score"] = overall_score

        # Builds response dictionary
        out_dict = {"Outlier scores": proportions}

        # Creates visualization for feature-level outlier proportions
        feature_scores = {
            k: v for k, v in proportions.items()
            if k != "Overall outlier score"
        }

        if feature_scores:
            plt.figure(figsize=(8, 8))
            plt.bar(feature_scores.keys(), feature_scores.values(), color="red")
            plt.title("Proportion of Outliers for Numerical Columns", fontsize=14)
            plt.xlabel("Columns", fontsize=14)
            plt.ylabel("Proportion of Outliers", fontsize=14)
            plt.ylim(0, 1)
            plt.xticks(rotation=45, ha="right", fontsize=12)
            plt.tight_layout()

            # Converts chart to base64
            img_buf = io.BytesIO()
            plt.savefig(img_buf, format="png")
            img_buf.seek(0)
            img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")
            plt.close()

            out_dict["Outliers Visualization"] = img_base64

        return out_dict

    except SoftTimeLimitExceeded:
        raise Exception("Outliers task timed out.")
    except Exception as e:
        return {"Error": f"Outlier detection failed: {str(e)}"}

