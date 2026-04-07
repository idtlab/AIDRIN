import base64
import io
import logging

import matplotlib.pyplot as plt
import numpy as np
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=False)
def outliers(self: Task, file_info):
    """Detect outliers in numerical columns using the IQR method.

    For each numerical column, computes the inter-quartile range (IQR) and
    flags values below ``Q1 - 1.5*IQR`` or above ``Q3 + 1.5*IQR`` as
    outliers.  Columns with zero IQR (no variability) receive a score of 0.
    An overall outlier score is the mean across all column scores.  A bar-chart
    visualisation of per-column scores is included.

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.

    Returns
    -------
    dict
        ``{"Outlier scores": {col: float, "Overall outlier score": float},
        "Outliers Visualization": base64_str}``
        where each per-column score is the proportion of outliers in ``[0, 1]``.
        Returns ``{"Error": str}`` if no numerical columns are found.
    """
    try:
        logger.info("Outliers task started")
        file = read_file(file_info)

        # Ensure DataFrame columns are strings to avoid numpy array issues
        if hasattr(file, 'columns'):
            file.columns = [str(col) for col in file.columns]

        try:
            out_dict = {}
            # Select numerical columns for outlier detection
            numerical_columns = file.select_dtypes(include=[np.number])

            if numerical_columns.empty:
                return {"Error": "No numerical features found in the dataset."}

            proportions_dict = {}

            # Process each column separately
            for col in numerical_columns.columns:
                series = numerical_columns[col].dropna()

                if series.empty:
                    proportions_dict[col] = np.nan
                    continue

                q1 = series.quantile(0.25)
                q3 = series.quantile(0.75)
                IQR = q3 - q1

                if IQR == 0:
                    proportions_dict[col] = 0.0  # no variability, no outliers
                    continue

                # Identify outliers using IQR
                mask = (series < (q1 - 1.5 * IQR)) | (series > (q3 + 1.5 * IQR))
                proportions_dict[col] = mask.mean()  # proportion of outliers

            # Calculate overall outlier score
            valid_values = [v for v in proportions_dict.values() if not np.isnan(v)]
            overall_score = np.mean(valid_values) if valid_values else 0.0
            proportions_dict["Overall outlier score"] = overall_score

            # Ensure all column names are strings to avoid numpy array issues
            proportions_dict = {str(k): v for k, v in proportions_dict.items()}

            # Calculate the average of dictionary values
            average_value = sum(proportions_dict.values()) / len(proportions_dict)
            proportions_dict["Overall outlier score"] = average_value
            # add the average to dictionary
            out_dict["Outlier scores"] = proportions_dict

            # Create bar chart for feature-level outlier proportions only
            feature_scores = {
                k: v for k, v in proportions_dict.items() if k != "Overall outlier score"
            }

            if feature_scores:  # only plot if there are valid features
                plt.figure(figsize=(8, 8))
                plt.bar(feature_scores.keys(), feature_scores.values(), color="red")
                plt.title("Proportion of Outliers for Numerical Columns", fontsize=14)
                plt.xlabel("Columns", fontsize=14)
                plt.ylabel("Proportion of Outliers", fontsize=14)
                plt.ylim(0, 1)

                plt.xticks(rotation=45, ha="right", fontsize=12)
                plt.subplots_adjust(bottom=0.5)
                plt.tight_layout()

                # Save the chart to BytesIO and encode as base64
                img_buf = io.BytesIO()
                plt.savefig(img_buf, format="png")
                img_buf.seek(0)
                img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")

                out_dict["Outliers Visualization"] = img_base64
                plt.close()

            logger.info("Outliers task completed: %d numerical columns processed", len(numerical_columns.columns))
            return out_dict

        except Exception as e:
            logger.error("Outlier detection failed: %s", e)
            return {"Error": f"Outlier detection failed: {str(e)}"}

    except SoftTimeLimitExceeded:
        logger.error("Outliers task timed out")
        raise Exception("Outliers task timed out.")
