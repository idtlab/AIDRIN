import base64
import io

import matplotlib.pyplot as plt
import numpy as np
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def outliers(self: Task, file_info):
    try:
        file = read_file(file_info)
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

            return out_dict

        except Exception as e:
            return {"Error": f"Outlier detection failed: {str(e)}"}

    except SoftTimeLimitExceeded:
        raise Exception("Outliers task timed out.")
