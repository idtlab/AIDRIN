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

            # Proportions as percentages
            proportions = value_counts.sort_values(ascending=True)
            labels = [str(v) for v in proportions.index]
            values = [p * 100 for p in proportions.values]

            # Horizontal bar chart
            n = len(labels)
            fig_height = max(2, n * 0.3)
            fig, ax = plt.subplots(figsize=(8, fig_height))
            fig.patch.set_alpha(0)
            ax.set_facecolor("none")

            text_color = "#6b7280"
            bars = ax.barh(range(n), values, color="#4485F4", height=0.8)

            ax.set_xlabel("Proportion (%)", fontsize=10, color=text_color)
            ax.set_yticks(range(n))
            ax.set_yticklabels(labels, fontsize=9, color=text_color)
            ax.tick_params(axis="x", colors=text_color, labelsize=8)
            ax.set_xlim(0, max(values) * 1.12)
            ax.set_ylim(-0.5, n - 0.5)

            for spine in ax.spines.values():
                spine.set_color(text_color)

            # Value labels inside bars
            for bar, val in zip(bars, values):
                # Place label inside bar if wide enough, otherwise just outside
                if val > max(values) * 0.15:
                    ax.text(
                        val - 0.5, bar.get_y() + bar.get_height() / 2,
                        f'{val:.1f}%',
                        ha='right', va='center', fontsize=8, color='white', fontweight='bold',
                    )
                else:
                    ax.text(
                        val + 0.5, bar.get_y() + bar.get_height() / 2,
                        f'{val:.1f}%',
                        ha='left', va='center', fontsize=8, color=text_color,
                    )

            fig.tight_layout(pad=0.5)

            # Save the chart to a BytesIO object
            img_buf = io.BytesIO()
            fig.savefig(img_buf, format="png", dpi=150, transparent=True)
            img_buf.seek(0)

            # Encode the image as base64
            img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")
            img_buf.close()

            plt.close(fig)

            logger.info("Representation Rate visualization task completed")
            return img_base64
    except SoftTimeLimitExceeded:
        logger.error("Representation Rate visualization task timed out")
        raise Exception("Representation Rate Vis task timed out.")
    except Exception as e:
        logger.error("Representation Rate visualization task failed: %s", e)
        return {"Error": f"Error calculating representation rate: {str(e)}"}
