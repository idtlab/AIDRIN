import base64
import logging
from io import BytesIO
from typing import List

import pandas as pd
import seaborn as sns
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from dython.nominal import associations

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)

# Configure matplotlib before importing pyplot to ensure non-interactive Agg backend
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

NOMINAL_NOMINAL_ASSOC = "theil"
_NORMALITY_MIN_SAMPLES = 8
_NORMALITY_MAX_SAMPLE_SIZE = 5000
_NORMALITY_ALPHA = 0.05


def _is_column_normal(series: pd.Series) -> bool:
    """
    Return True when the series appears approximately normally distributed.

    The primary check uses the Shapiro–Wilk test (scipy.stats.shapiro)
    with significance level alpha = _NORMALITY_ALPHA, run on a sample
    capped at _NORMALITY_MAX_SAMPLE_SIZE observations to keep runtime
    reasonable on very large datasets. If SciPy is unavailable, a
    simple skewness/kurtosis heuristic is used as a fallback.
    """
    cleaned = pd.to_numeric(series, errors="coerce").dropna()
    if cleaned.shape[0] < _NORMALITY_MIN_SAMPLES:
        return False

    try:
        from scipy.stats import shapiro

        sample = cleaned
        if cleaned.shape[0] > _NORMALITY_MAX_SAMPLE_SIZE:
            sample = cleaned.sample(
                n=_NORMALITY_MAX_SAMPLE_SIZE,
                random_state=42,
            )
        _, p_value = shapiro(sample)
        return bool(p_value > _NORMALITY_ALPHA)
    except Exception:
        skewness = cleaned.skew()
        kurtosis = cleaned.kurtosis()
        return abs(skewness) < 1 and abs(kurtosis) < 1


@shared_task(bind=True, ignore_result=False)
def calc_correlations(self: Task, columns: List[str], file_info):
    df = read_file(file_info)
    try:
        # Separate categorical and numerical columns
        categorical_columns = df[columns].select_dtypes(include=["object", "string", "category"]).columns
        numerical_columns = df[columns].select_dtypes(exclude=["object", "string", "category"]).columns

        result_dict = {
            "Correlations Analysis Categorical": {},
            "Correlations Analysis Numerical": {},
            "Correlation Scores": {},
        }

        # Check if there are categorical features
        if not categorical_columns.empty:
            # Categorical-categorical correlations are computed using theil
            categorical_correlation = associations(
                df[categorical_columns], nom_nom_assoc=NOMINAL_NOMINAL_ASSOC, plot=False
            )
            logger.debug("Categorical correlation matrix computed:\n%s", categorical_correlation["corr"])

            corr_matrix = categorical_correlation["corr"]
            n = len(corr_matrix.columns)
            fig_size = max(6, n * 0.7)
            text_color = "#6b7280"

            fig, ax = plt.subplots(figsize=(fig_size, fig_size))
            fig.patch.set_alpha(0)
            ax.set_facecolor("none")

            annot_size = max(7, min(10, 80 // max(n, 1)))
            _ = sns.heatmap(
                corr_matrix, annot=True, cmap="coolwarm", fmt=".2f", ax=ax,
                annot_kws={"size": annot_size},
                linewidths=0.5, linecolor="#e5e7eb",
                cbar=False,
            )

            # Truncate long labels
            x_labels = [t.get_text()[:12] + "..." if len(t.get_text()) > 12 else t.get_text() for t in ax.get_xticklabels()]
            y_labels = [t.get_text()[:12] + "..." if len(t.get_text()) > 12 else t.get_text() for t in ax.get_yticklabels()]
            ax.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=9, color=text_color)
            ax.set_yticklabels(y_labels, rotation=0, fontsize=9, color=text_color)

            fig.tight_layout(pad=0.5)

            # Save the plot to a BytesIO object
            image_stream_cat = BytesIO()
            fig.savefig(image_stream_cat, format="png", dpi=150, transparent=True)
            plt.close(fig)

            # Convert the plot to base64
            base64_image_cat = base64.b64encode(image_stream_cat.getvalue()).decode(
                "utf-8"
            )

            # Close the BytesIO stream
            image_stream_cat.close()

            result_dict["Correlations Analysis Categorical"][
                "Correlations Analysis Categorical Visualization"
            ] = base64_image_cat
            result_dict["Correlations Analysis Categorical"]["Description"] = (
                "Categorical correlations are calculated using Theil's U, with values ranging from 0 to 1. "
                "A value of 1 indicates a perfect correlation, while a value of 0 indicates no correlation"
            )

        # Check if there are numerical features
        if not numerical_columns.empty:
            numerical_df = df[numerical_columns].apply(pd.to_numeric, errors="coerce")
            normal_columns = [
                col for col in numerical_df.columns if _is_column_normal(numerical_df[col])
            ]
            all_normal = len(normal_columns) == len(numerical_df.columns)
            corr_method = "pearson" if all_normal else "spearman"

            # Numerical-numerical correlations are computed dynamically based on normality.
            numerical_correlation = numerical_df.corr(method=corr_method)

            n = len(numerical_correlation.columns)
            fig_size = max(6, n * 0.7)
            text_color = "#6b7280"

            fig, ax = plt.subplots(figsize=(fig_size, fig_size))
            fig.patch.set_alpha(0)
            ax.set_facecolor("none")

            annot_size = max(7, min(10, 80 // max(n, 1)))
            _ = sns.heatmap(
                numerical_correlation, annot=True, cmap="coolwarm", fmt=".2f", ax=ax,
                annot_kws={"size": annot_size},
                linewidths=0.5, linecolor="#e5e7eb",
                cbar=False,
            )

            x_labels = [t.get_text()[:12] + "..." if len(t.get_text()) > 12 else t.get_text() for t in ax.get_xticklabels()]
            y_labels = [t.get_text()[:12] + "..." if len(t.get_text()) > 12 else t.get_text() for t in ax.get_yticklabels()]
            ax.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=9, color=text_color)
            ax.set_yticklabels(y_labels, rotation=0, fontsize=9, color=text_color)

            fig.tight_layout(pad=0.5)

            # Save the plot to a BytesIO object
            image_stream_num = BytesIO()
            fig.savefig(image_stream_num, format="png", dpi=150, transparent=True)
            plt.close(fig)

            # Convert the plot to base64
            base64_image_num = base64.b64encode(image_stream_num.getvalue()).decode(
                "utf-8"
            )

            # Close the BytesIO stream
            image_stream_num.close()

            result_dict["Correlations Analysis Numerical"][
                "Correlations Analysis Numerical Visualization"
            ] = base64_image_num
            result_dict["Correlations Analysis Numerical"]["Description"] = (
                f"Numerical correlations are calculated using {corr_method.title()}'s correlation coefficient, with values "
                "ranging from -1 to 1. A value of 1 indicates a perfect positive correlation, -1 indicates a perfect "
                "negative correlation, and 0 indicates no correlation"
            )
            result_dict["Correlations Analysis Numerical"]["Method"] = (
                corr_method.title()
            )

        # Create and return a dictionary with correlation scores and plots
        correlation_dict = {}
        if not categorical_columns.empty:
            for col1 in categorical_correlation["corr"].columns:
                for col2 in categorical_correlation["corr"].columns:
                    if col1 != col2:
                        key = f"{col1} vs {col2}"
                        correlation_dict[key] = categorical_correlation["corr"].loc[
                            col1, col2
                        ]

        if not numerical_columns.empty:
            for col1 in numerical_correlation.columns:
                for col2 in numerical_correlation.columns:
                    if col1 != col2:
                        key = f"{col1} vs {col2}"
                        correlation_dict[key] = numerical_correlation.loc[col1, col2]

        result_dict["Correlation Scores"] = correlation_dict

        return result_dict
    except SoftTimeLimitExceeded:
        raise Exception("Correlations task timed out.")
    except Exception as e:
        return {"Message": f"Error: {str(e)}"}
