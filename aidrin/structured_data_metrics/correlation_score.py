import base64
from io import BytesIO
from typing import List

import matplotlib.pyplot as plt
import seaborn as sns
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from dython.nominal import associations

from aidrin.file_handling.file_parser import read_file

NOMINAL_NOMINAL_ASSOC = "theil"


@shared_task(bind=True, ignore_result=False)
def calculate_correlations(
    self: Task, columns: List[str], file_info, base_64: bool = False
) -> dict:
    """
    Calculates categorical and numerical correlations.

    Args:
        columns: Columns to include.
        file_info: File information for reading the dataframe.
        base_64: If True, return plots as base64 strings (Flask/prod).
                 If False, return raw matplotlib figure objects (PyPI/local).

    Returns:
        dict: Contains correlation descriptions, plots (base64 or figure), and scores.
    """

    df = read_file(file_info)
    try:
        categorical_columns = df[columns].select_dtypes(include="object").columns
        numerical_columns = df[columns].select_dtypes(exclude="object").columns

        result_dict = {
            "Correlations Analysis Categorical": {},
            "Correlations Analysis Numerical": {},
            "Correlation Scores": {},
        }

        # ----- Categorical correlations -----
        if not categorical_columns.empty:
            categorical_correlation = associations(
                df[categorical_columns], nom_nom_assoc=NOMINAL_NOMINAL_ASSOC, plot=False
            )

            fig_cat, ax_cat = plt.subplots(1, 1, figsize=(8, 8))
            sns.heatmap(
                categorical_correlation["corr"],
                annot=True,
                cmap="coolwarm",
                fmt=".2f",
                ax=ax_cat,
            )
            ax_cat.set_title("Categorical-Categorical Correlation Matrix")
            ax_cat.tick_params(axis="x", rotation=0, labelsize=12)
            ax_cat.tick_params(axis="y", rotation=90, labelsize=12)

            # Shorten long tick labels
            for label in ax_cat.get_xticklabels():
                if len(label.get_text()) > 9:
                    label.set_text(label.get_text()[:9] + "...")
            for label in ax_cat.get_yticklabels():
                if len(label.get_text()) > 9:
                    label.set_text(label.get_text()[:9] + "...")

            if base_64:
                image_stream_cat = BytesIO()
                fig_cat.savefig(image_stream_cat, format="png")
                base64_image_cat = base64.b64encode(image_stream_cat.getvalue()).decode("utf-8")
                image_stream_cat.close()

                result_dict["Correlations Analysis Categorical"][
                    "Correlations Analysis Categorical Visualization"
                ] = base64_image_cat
            else:
                plt.tight_layout()
                plt.show()

            plt.close(fig_cat)

            result_dict["Correlations Analysis Categorical"]["Description"] = (
                "Categorical correlations are calculated using Theil's U, with values ranging from 0 to 1. "
                "A value of 1 indicates a perfect correlation, while a value of 0 indicates no correlation."
            )

        # ----- Numerical correlations -----
        if not numerical_columns.empty:
            numerical_correlation = df[numerical_columns].corr()

            fig_num, ax_num = plt.subplots(1, 1, figsize=(8, 8))
            sns.heatmap(
                numerical_correlation, annot=True, cmap="coolwarm", fmt=".2f", ax=ax_num
            )
            ax_num.set_title("Numerical-Numerical Correlation Matrix")
            ax_num.tick_params(axis="x", rotation=0, labelsize=12)
            ax_num.tick_params(axis="y", rotation=90, labelsize=12)

            if base_64:
                image_stream_num = BytesIO()
                fig_num.savefig(image_stream_num, format="png")
                base64_image_num = base64.b64encode(image_stream_num.getvalue()).decode("utf-8")
                image_stream_num.close()

                result_dict["Correlations Analysis Numerical"][
                    "Correlations Analysis Numerical Visualization"
                ] = base64_image_num
            else:
                plt.tight_layout()
                plt.show()

            plt.close(fig_num)

            result_dict["Correlations Analysis Numerical"]["Description"] = (
                "Numerical correlations are calculated using Pearson's correlation coefficient, "
                "with values ranging from -1 to 1. A value of 1 indicates a perfect positive correlation, "
                "-1 indicates a perfect negative correlation, and 0 indicates no correlation."
            )

        # ----- Correlation scores -----
        correlation_dict = {}
        if not categorical_columns.empty:
            for col1 in categorical_correlation["corr"].columns:
                for col2 in categorical_correlation["corr"].columns:
                    if col1 != col2:
                        correlation_dict[f"{col1} vs {col2}"] = categorical_correlation["corr"].loc[col1, col2]

        if not numerical_columns.empty:
            for col1 in numerical_correlation.columns:
                for col2 in numerical_correlation.columns:
                    if col1 != col2:
                        correlation_dict[f"{col1} vs {col2}"] = numerical_correlation.loc[col1, col2]

        result_dict["Correlation Scores"] = correlation_dict

        return result_dict

    except SoftTimeLimitExceeded:
        raise Exception("Correlations task timed out.")
    except Exception as e:
        return {"Message": f"Error: {str(e)}"}
