import base64
import io

import matplotlib.pyplot as plt
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def calculate_representation_rate(self: Task, columns, file_info):
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

        return representation_rate_info
    except SoftTimeLimitExceeded:
        raise Exception("Representation Rate task timed out.")
    except Exception as e:
        return {"Error": f"Error calculating representation rate: {str(e)}"}


@shared_task(bind=True, ignore_result=False)
def create_representation_rate_vis(self: Task, columns, file_info):
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

            return img_base64
    except SoftTimeLimitExceeded:
        raise Exception("Representation Rate Vis task timed out.")
    except Exception as e:
        return {"Error": f"Error calculating representation rate: {str(e)}"}
