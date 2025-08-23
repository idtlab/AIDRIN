import base64
import io

import matplotlib.pyplot as plt
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def completeness(self: Task, file_info):
    try:
        file = read_file(file_info)
        # Calculate completeness metric for each column
        completeness_scores = (1 - file.isnull().mean()).to_dict()
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

        return result_dict

    except SoftTimeLimitExceeded:
        raise Exception("Completeness task timed out.")
