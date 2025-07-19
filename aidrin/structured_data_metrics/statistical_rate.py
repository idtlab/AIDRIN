import base64
import io

import matplotlib.pyplot as plt
import numpy as np
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def calculate_statistical_rates(
    self: Task, y_true_column, sensitive_attribute_column, file_info
):
    try:
        dataframe = read_file(file_info)
        # Drop rows with NaN values in the specified columns
        dataframe_cleaned = dataframe.dropna(
            subset=[y_true_column, sensitive_attribute_column]
        )

        # Extract unique sensitive attribute values and class labels
        unique_sensitive_values = dataframe_cleaned[sensitive_attribute_column].unique()
        unique_class_labels = dataframe_cleaned[y_true_column].unique()

        # Calculate proportions for each class within each unique sensitive attribute value
        class_proportions = {}
        for sensitive_value in unique_sensitive_values:
            mask_sensitive = (
                dataframe_cleaned[sensitive_attribute_column] == sensitive_value
            )

            class_proportions[sensitive_value] = {}

            total_samples_sensitive = np.sum(mask_sensitive)

            for class_label in unique_class_labels:
                mask_class = dataframe_cleaned[y_true_column] == class_label
                mask_combined = mask_sensitive & mask_class

                # Calculate proportion within class
                proportion = np.sum(mask_combined) / total_samples_sensitive
                class_proportions[sensitive_value][class_label] = proportion

        # Extract unique class labels
        unique_class_labels = sorted(dataframe_cleaned[y_true_column].unique())

        # TSD calculation

        # Initialize a dictionary to store proportions for each class
        tsd = {}

        # Extract proportions for each class across all groups
        for group in class_proportions:
            for class_label, proportion in class_proportions[group].items():
                if class_label not in tsd:
                    tsd[class_label] = []
                tsd[class_label].append(proportion)

        for class_label, proportion in tsd.items():
            tsd[class_label] = np.std(proportion)

        # Set up the plot
        fig, ax = plt.subplots(figsize=(8, 8))

        # Calculate the total number of classes and sensitive attribute values
        num_classes = len(unique_class_labels)
        num_sensitive_values = len(unique_sensitive_values)

        # Calculate the width of each bar and the total width of each group
        bar_width = 0.1
        group_width = bar_width * num_classes

        # Calculate the offset for each bar within a group
        bar_offset = np.arange(num_sensitive_values) * group_width - (
            group_width * (num_classes - 1) / 2
        )

        # Iterate through each unique class label
        for i, class_label in enumerate(unique_class_labels):
            # Extract proportions for the current class label
            proportions = [
                class_proportions[sensitive_value].get(class_label, 0)
                for sensitive_value in unique_sensitive_values
            ]

            # Plot the bars for each sensitive attribute value with the adjusted position
            bar_positions = bar_offset + i * bar_width
            ax.bar(
                bar_positions,
                proportions,
                width=bar_width,
                label=f"Class: {class_label}",
            )

        # Set up labels and title
        ax.set_xticks(bar_offset + (num_classes - 1) * bar_width / 2)
        # Adjust fontsize and rotation
        ax.set_xticklabels(unique_sensitive_values, rotation=30, ha="right", fontsize=8)
        ax.set_xlabel("Sensitive Attribute")
        ax.set_ylabel("Proportion")
        ax.set_title("Class Proportions for Each Sensitive Attribute")
        ax.legend()

        # Adjust the bottom margin to avoid xticks being cropped
        plt.subplots_adjust(bottom=0.25)

        # Save the plot as a base64 string
        buffer = io.BytesIO()
        plt.savefig(buffer, format="png")
        buffer.seek(0)
        base64_plot = base64.b64encode(buffer.read()).decode("utf-8")
        # Close the BytesIO stream
        buffer.close()

        # Full disclosure: This workaround is from stackoverflow.
        # Recasts all numpy types to their native Python types so Celery can pass the data correctly.
        def to_serializable(obj):
            if isinstance(obj, dict):
                return {str(k): to_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple, np.ndarray)):
                return [to_serializable(i) for i in obj]
            elif isinstance(obj, (np.integer, np.int64)):
                return int(obj)
            else:
                return obj

        cleaned_payload = to_serializable(
            {
                "Statistical Rates": class_proportions,
                "TSD scores": tsd,
                "Description": "The TSD values are calculated by getting the standard deviation of the "
                "proportions of each group across the different classes...",
                "Statistical Rate Visualization": base64_plot,
            }
        )
        return {
            "Statistical Rates": cleaned_payload["Statistical Rates"],
            "TSD scores": cleaned_payload["TSD scores"],
            "Description": cleaned_payload["Description"],
            "Statistical Rate Visualization": cleaned_payload[
                "Statistical Rate Visualization"
            ],
        }
    except SoftTimeLimitExceeded:
        raise Exception("Statistical Rate task timed out.")
    except Exception as e:
        return {"Error": str(e)}
