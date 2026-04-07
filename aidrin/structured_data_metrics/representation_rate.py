import base64
import io
import logging

import matplotlib.pyplot as plt
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=False)
def calculate_representation_rate(self: Task, columns, file_info):
    """Calculate pairwise representation (probability) ratios for sensitive attribute columns.

    For each column in *columns*, computes the normalised value counts and then
    emits the ratio ``P(value_a) / P(value_b)`` for every unordered pair of
    distinct values.  A ratio greater than 1 indicates that ``value_a`` is
    over-represented relative to ``value_b``.

    Parameters
    ----------
    columns : list of str
        Names of the sensitive attribute columns to analyse.
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.

    Returns
    -------
    dict
        Keys of the form
        ``"Column: '<col>', Probability ratio for '<a>' to '<b>'"``
        mapped to their float ratio values, or ``{"Error": str}`` on failure.
    """
    logger.info("Representation Rate task started: %d columns", len(columns))
    dataframe = read_file(file_info)
    representation_rate_info = {}
    processed_keys = set()  # Using a set to track processed pairs
    x_tick_keys = []
    try:
        for column in columns:
            # Drop rows with NaN values
            column_series = dataframe[column].dropna()
            value_counts = column_series.value_counts(normalize=True)

            for attribute_value1 in value_counts.index:
                for attribute_value2 in value_counts.index:
                    if attribute_value1 != attribute_value2:
                        # Check if the pair has been processed or its reverse
                        pair = f"{attribute_value1} vs {attribute_value2}"
                        reverse_pair = f"{attribute_value2} vs {attribute_value1}"

                        if pair in processed_keys or reverse_pair in processed_keys:
                            continue

                        probability_ratio = (
                            value_counts[attribute_value1]
                            / value_counts[attribute_value2]
                        )
                        key = f"Column: '{column}', Probability ratio for '{attribute_value1}' to '{attribute_value2}'"
                        x_tick_keys.append(f"{attribute_value1} vs {attribute_value2}")
                        processed_keys.add(pair)  # Mark the pair as processed
                        representation_rate_info[key] = probability_ratio

        logger.info("Representation Rate task completed: %d ratios computed", len(representation_rate_info))
        return representation_rate_info
    except SoftTimeLimitExceeded:
        logger.error("Representation Rate task timed out")
        raise Exception("Representation Rate task timed out.")
    except Exception as e:
        logger.error("Representation Rate task failed: %s", e)
        return {"Error": f"Error calculating representation rate: {str(e)}"}


@shared_task(bind=True, ignore_result=False)
def create_representation_rate_vis(self: Task, columns, file_info):
    """Render a pie chart visualising the value distribution of a sensitive column.

    For the first column in *columns*, computes cumulative normalised value
    counts and renders a pie chart showing what percentage of the dataset each
    distinct value occupies.

    Parameters
    ----------
    columns : list of str
        Sensitive attribute column names; only the first column is visualised.
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.

    Returns
    -------
    str
        Base64-encoded PNG image, or ``{"Error": str}`` on failure.
    """
    logger.info("Representation Rate visualization task started")
    dataframe = read_file(file_info)
    try:
        for column in columns:
            # Drop rows with NaN values
            column_series = dataframe[column].dropna()
            len(column_series)
            value_counts = column_series.value_counts(normalize=True)

            # Calculate cumulative proportions
            cum_proportions = value_counts.sort_index().cumsum()

            # Create a pie chart for cumulative proportions
            plt.figure(figsize=(8, 8))
            values = [
                cum_proportions[attribute_value] * 100
                for attribute_value in cum_proportions.index
            ]

            # Plot the pie chart

            plt.title(
                "Percentage Distribution of Sensitive Attribute Values", fontsize=16
            )
            plt.pie(
                values,
                labels=cum_proportions.index,
                autopct="%1.1f%%",
                startangle=140,
                textprops={"fontsize": 14},
            )

            # plt.subplots_adjust(left=0.2)
            plt.tight_layout()

            # Save the chart to a BytesIO object
            img_buf = io.BytesIO()
            plt.savefig(img_buf, format="png")
            img_buf.seek(0)

            # Encode the image as base64
            img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")
            img_buf.close()

            plt.close()  # Close the plot to free up resources

            logger.info("Representation Rate visualization task completed")
            return img_base64
    except SoftTimeLimitExceeded:
        logger.error("Representation Rate visualization task timed out")
        raise Exception("Representation Rate Vis task timed out.")
    except Exception as e:
        logger.error("Representation Rate visualization task failed: %s", e)
        return {"Error": f"Error calculating representation rate: {str(e)}"}
