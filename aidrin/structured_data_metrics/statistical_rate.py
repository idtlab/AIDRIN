import base64
import io

import matplotlib.pyplot as plt
import numpy as np
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def calculate_statistical_rates(
    self: Task, y_true_column, sensitive_attribute_column, file_info, return_base64: bool = False
):
    try:
        dataframe = read_file(file_info)
        # Drop rows with NaN values in the specified columns
        dataframe_cleaned = dataframe.dropna(
            subset=[y_true_column, sensitive_attribute_column]
        )

        # Extract unique sensitive attribute values and class labels
        unique_sensitive_values = dataframe_cleaned[sensitive_attribute_column].unique()
        unique_class_labels = sorted(dataframe_cleaned[y_true_column].unique())

        # Calculate proportions for each class within each unique sensitive attribute value
        class_proportions = {}
        for sensitive_value in unique_sensitive_values:
            mask_sensitive = dataframe_cleaned[sensitive_attribute_column] == sensitive_value
            total_samples_sensitive = np.sum(mask_sensitive)
            class_proportions[sensitive_value] = {}

            for class_label in unique_class_labels:
                mask_class = dataframe_cleaned[y_true_column] == class_label
                mask_combined = mask_sensitive & mask_class
                proportion = np.sum(mask_combined) / total_samples_sensitive
                class_proportions[sensitive_value][class_label] = proportion

        # Calculate TSD (Total Standard Deviation) for each class label
        tsd = {}
        for class_label in unique_class_labels:
            proportions = [class_proportions[s][class_label] for s in unique_sensitive_values]
            tsd[class_label] = np.std(proportions)

        # Plotting
        fig, ax = plt.subplots(figsize=(8, 8))
        num_classes = len(unique_class_labels)
        num_sensitive_values = len(unique_sensitive_values)
        bar_width = 0.1
        group_width = bar_width * num_classes
        bar_offset = np.arange(num_sensitive_values) * group_width - (group_width * (num_classes - 1) / 2)

        for i, class_label in enumerate(unique_class_labels):
            proportions = [class_proportions[s].get(class_label, 0) for s in unique_sensitive_values]
            bar_positions = bar_offset + i * bar_width
            ax.bar(bar_positions, proportions, width=bar_width, label=f"Class: {class_label}")

        ax.set_xticks(bar_offset + (num_classes - 1) * bar_width / 2)
        ax.set_xticklabels(unique_sensitive_values, rotation=30, ha="right", fontsize=8)
        ax.set_xlabel("Sensitive Attribute")
        ax.set_ylabel("Proportion")
        ax.set_title("Class Proportions for Each Sensitive Attribute")
        ax.legend()
        plt.subplots_adjust(bottom=0.25)

        if return_base64:
            buffer = io.BytesIO()
            plt.savefig(buffer, format="png")
            buffer.seek(0)
            base64_plot = base64.b64encode(buffer.read()).decode("utf-8")
            buffer.close()
            plt.close(fig)
            plot_result = base64_plot
        else:
            plt.tight_layout()
            plt.show()
            plt.close(fig)
            return {"Statistical Rates": class_proportions, "TSD scores": tsd,
                    "Description": (
                        "The TSD values are calculated by getting the standard deviation of the "
                        "proportions of each group across the different classes."
                    ),
                    }

        # Utility function to make numpy types JSON serializable
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
                "Description": (
                    "The TSD values are calculated by getting the standard deviation of the "
                    "proportions of each group across the different classes."
                ),
                "Statistical Rate Visualization": plot_result,
            }
        )

        return {
            "Statistical Rates": cleaned_payload["Statistical Rates"],
            "TSD scores": cleaned_payload["TSD scores"],
            "Description": cleaned_payload["Description"],
            "Statistical Rate Visualization": cleaned_payload["Statistical Rate Visualization"],
        }

    except SoftTimeLimitExceeded:
        raise Exception("Statistical Rate task timed out.")
    except Exception as e:
        return {"Error": str(e)}
