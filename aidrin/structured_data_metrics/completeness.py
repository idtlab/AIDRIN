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
def completeness(self: Task, file_info):
    try:
        # Reads the file
        df = read_file(file_info)

        if df is None:
            return {"Error": "File could not be read."}

        # Ensure column names are strings
        if hasattr(df, 'columns'):
            df.columns = [str(col) for col in df.columns]

        # Processes each chunk of rows
        chunk_stats = []
        total_rows = 0

        for idx, chunk in enumerate(iterate_chunks(df)):
            chunk_size = len(chunk)
            total_rows += chunk_size

            # Missing values per column for this chunk
            chunk_missing = {col: chunk[col].isnull().sum() for col in df.columns}

            # Missing in any column for this chunk
            chunk_missing_rows = chunk.isnull().any(axis=1).sum()

            # Column-wise completeness for this chunk
            chunk_completeness = {
                col: 1 - (chunk_missing[col] / chunk_size)
                for col in df.columns
            }

            # Overall completeness for this chunk
            chunk_overall = 1 - (chunk_missing_rows / chunk_size)

            chunk_stats.append({
                "chunk": idx,
                "size": chunk_size,
                "completeness": chunk_completeness,
                "overall": chunk_overall
            })

        # Aggregates completeness across all chunks
        final_feature_scores = {}

        for col in df.columns:
            weighted_sum = sum(
                cs["completeness"][col] * cs["size"] for cs in chunk_stats
            )
            final_feature_scores[col] = weighted_sum / total_rows

        final_overall = sum(
            cs["overall"] * cs["size"] for cs in chunk_stats
        ) / total_rows

        # Creates the completeness chart
        plt.figure(figsize=(8, 6))
        plt.bar(final_feature_scores.keys(), final_feature_scores.values())
        plt.title("Final Feature-wise Completeness Scores", fontsize=16)
        plt.xlabel("Features", fontsize=14)
        plt.ylabel("Completeness Score", fontsize=14)
        plt.ylim(0, 1)
        plt.xticks(rotation=45, ha="right", fontsize=12)
        plt.tight_layout()

        # Converts chart to base64
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png")
        img_buf.seek(0)
        final_img = base64.b64encode(img_buf.read()).decode("utf-8")
        plt.close()

        # Returns all results
        return {
            "Chunk Completeness": chunk_stats,
            "Final Completeness": {
                "feature_wise": final_feature_scores,
                "overall": final_overall,
            },
            "Completeness Visualization": final_img
        }

    except SoftTimeLimitExceeded:
        raise Exception("Completeness task timed out.")

    except Exception as e:
        return {"Error": f"Completeness calculation failed: {str(e)}"}
