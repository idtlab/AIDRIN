import base64
import io
import logging

import matplotlib.pyplot as plt
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=False)
def completeness(self: Task, file_info):
    """Compute per-column and overall completeness (non-missing rate) for a dataset.

    Reads the file, calculates the proportion of non-null values for every
    column, and also computes an overall completeness score — the fraction of
    rows that have *no* missing values in *any* column.  A bar-chart
    visualisation is included in the result.

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.

    Returns
    -------
    dict
        ``{"Completeness scores": {col: float}, "Overall Completeness": float,
        "Completeness Visualization": base64_str}``
        where each score is in ``[0, 1]`` (1 = fully complete).
    """
    try:
        logger.info("Completeness task started")
        file = read_file(file_info)

        # Ensure DataFrame columns are strings to avoid numpy array issues
        if hasattr(file, 'columns'):
            file.columns = [str(col) for col in file.columns]

        # Calculate completeness metric for each column
        try:
            completeness_scores = (1 - file.isnull().mean()).to_dict()
        except Exception:
            # If to_dict() fails, manually create the dictionary
            completeness_scores = {}
            for col in file.columns:
                try:
                    completeness_scores[str(col)] = float(1 - file[col].isnull().mean())
                except Exception:
                    completeness_scores[str(col)] = 0.0

        # Ensure all column names are strings to avoid numpy array issues
        completeness_scores = {str(k): v for k, v in completeness_scores.items()}

        # Calculate overall completeness metric for the dataset
        overall_completeness = 1 - file.isnull().any(axis=1).mean()

        result_dict = {}

        # Always include completeness scores for all features
        result_dict["Completeness scores"] = completeness_scores
        result_dict["Overall Completeness"] = overall_completeness

        # Create a bar chart for all features
        plt.figure(figsize=(8, 6))
        plt.bar(completeness_scores.keys(), completeness_scores.values(), color="blue")
        plt.title("Feature-wise Completeness Scores", fontsize=16)
        plt.xlabel("Features", fontsize=14)
        plt.ylabel("Completeness Score", fontsize=14)
        plt.ylim(0, 1)

        # Rotate x-axis tick labels for readability
        plt.xticks(rotation=45, ha="right", fontsize=12)
        plt.tight_layout()

        # Save the chart to a BytesIO object
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format="png")
        img_buf.seek(0)

        # Encode the image as base64
        img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")

        result_dict["Completeness Visualization"] = img_base64
        plt.close()

        logger.info("Completeness task completed: %d columns, overall=%.4f", len(completeness_scores), overall_completeness)
        return result_dict

    except SoftTimeLimitExceeded:
        logger.error("Completeness task timed out")
        raise Exception("Completeness task timed out.")
