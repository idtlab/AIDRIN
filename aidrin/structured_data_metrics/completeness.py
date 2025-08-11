import base64
import io

import matplotlib.pyplot as plt
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def calculate_completeness(self: Task, file_info, return_base64: bool = False):
    """
    Calculate completeness metrics for each column and optionally return
    the plot as a Base64-encoded PNG.

    Args:
        file_info: File info object to read the dataframe.
        return_base64: If True, return the chart as a Base64 string (Flask/prod).
                       If False, return the raw matplotlib Figure object (PyPI/local).

    Returns:
        dict: Completeness scores, visualization (Base64 or Figure), and overall completeness.
    """
    try:
        file = read_file(file_info)
        completeness_scores = (1 - file.isnull().mean()).to_dict()
        overall_completeness = 1 - file.isnull().any(axis=1).mean()

        result_dict = {}

        if overall_completeness != 0 and overall_completeness != 1:
            incomplete_columns = {k: v for k, v in completeness_scores.items() if v < 1}

            if incomplete_columns:
                result_dict["Completeness scores"] = incomplete_columns

                fig, ax = plt.subplots(figsize=(8, 8))
                ax.bar(incomplete_columns.keys(), incomplete_columns.values(), color="blue")
                ax.set_title("Completeness Scores", fontsize=16)
                ax.set_xlabel("Columns", fontsize=14)
                ax.set_ylabel("Completeness Score", fontsize=14)
                ax.set_ylim(0, 1)
                plt.xticks(rotation=45, ha="right", fontsize=12)
                plt.subplots_adjust(bottom=0.5)
                plt.tight_layout()

                if return_base64:
                    buf = io.BytesIO()
                    fig.savefig(buf, format="png")
                    buf.seek(0)
                    img_base64 = base64.b64encode(buf.read()).decode("utf-8")
                    buf.close()
                    result_dict["Completeness Visualization"] = img_base64
                else:
                    result_dict["Completeness Visualization"] = fig

                plt.close(fig)

            result_dict["Overall Completeness"] = overall_completeness

        elif overall_completeness == 1:
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.bar(["Overall Missingness"], [0], color="red")
            ax.set_title("Missingness of the Dataset")
            ax.set_xlabel("Dataset")
            ax.set_ylabel("Missingness Score")
            ax.set_ylim(0, 1)
            plt.tight_layout()

            if return_base64:
                buf = io.BytesIO()
                fig.savefig(buf, format="png")
                buf.seek(0)
                img_base64 = base64.b64encode(buf.read()).decode("utf-8")
                buf.close()
                result_dict["Completeness Visualization"] = img_base64
            else:
                plt.show()

            plt.close(fig)
            result_dict["Overall Completeness"] = 1

        else:
            result_dict["Overall Completeness of Dataset"] = "Error"

        return result_dict

    except SoftTimeLimitExceeded:
        raise Exception("Completeness task timed out.")
