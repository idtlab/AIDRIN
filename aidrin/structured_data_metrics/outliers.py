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
                labels = list(feature_scores.keys())
                values = list(feature_scores.values())
                n = len(labels)
                text_color = "#6b7280"

                fig_height = max(3, n * 0.3)
                fig, ax = plt.subplots(figsize=(8, fig_height))
                fig.patch.set_alpha(0)
                ax.set_facecolor("none")

                bars = ax.barh(range(n), values, color="#D86470", height=0.7)
                ax.set_xlabel("Proportion of Outliers", fontsize=10, color=text_color)
                ax.set_yticks(range(n))
                ax.set_yticklabels(labels, fontsize=9, color=text_color)
                ax.tick_params(axis="x", colors=text_color, labelsize=8)
                ax.set_xlim(0, max(max(values) * 1.15, 0.1))
                ax.invert_yaxis()
                ax.set_ylim(n - 0.5, -0.5)

                for spine in ax.spines.values():
                    spine.set_color(text_color)

                for bar, val in zip(bars, values):
                    if val > max(values) * 0.15:
                        ax.text(val - 0.005, bar.get_y() + bar.get_height() / 2,
                                f'{val:.3f}', ha='right', va='center', fontsize=8, color='white', fontweight='bold')
                    else:
                        ax.text(val + 0.005, bar.get_y() + bar.get_height() / 2,
                                f'{val:.3f}', ha='left', va='center', fontsize=8, color=text_color)

                fig.tight_layout(pad=0.5)

                img_buf = io.BytesIO()
                fig.savefig(img_buf, format="png", dpi=150, transparent=True)
                img_buf.seek(0)
                img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")

                out_dict["Outliers Visualization"] = img_base64
                plt.close(fig)

            logger.info("Outliers task completed: %d numerical columns processed", len(numerical_columns.columns))
            return out_dict

        except Exception as e:
            logger.error("Outlier detection failed: %s", e)
            return {"Error": f"Outlier detection failed: {str(e)}"}

    except SoftTimeLimitExceeded:
        logger.error("Outliers task timed out")
        raise Exception("Outliers task timed out.")
