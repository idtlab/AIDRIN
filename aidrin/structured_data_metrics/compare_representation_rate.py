import base64
import io
import matplotlib.pyplot as plt
import numpy as np

def compare_rep_rates(rep_dict, rrr_dict):
    final_dict = {}

    real_values = []
    dataset_values = []
    categories = []
    processed_pairs = set()

    common_keys = set(rep_dict.keys()) & set(rrr_dict.keys())

    # Compare values of common keys
    for key in common_keys:
        feature_from = key.split("'")[3]
        feature_to = key.split("'")[5]

        # Check if the pair has been processed before
        pair = (feature_from, feature_to)
        if pair in processed_pairs or (feature_to, feature_from) in processed_pairs:
            continue

        # Mark the pair as processed
        processed_pairs.add(pair)

        value1 = rep_dict[key]
        value2 = rrr_dict[key]

        difference_key = f"Real vs Dataset Representation rate difference in '{feature_from}' to '{feature_to}'"
        final_dict[difference_key] = abs(value2 - value1)

        categories.append(f"{feature_from} / {feature_to}")
        real_values.append(value2)
        dataset_values.append(value1)



    # Calculate the total for each category
    totals = [v1 + v2 for v1, v2 in zip(real_values, dataset_values)]

    # Calculate the percentages for each stack
    percentages1 = [(v1 / total) * 100 for v1, total in zip(real_values, totals)]
    percentages2 = [(v2 / total) * 100 for v2, total in zip(dataset_values, totals)]

    fig, ax = plt.subplots(figsize=(8, 8))
    plt.subplots_adjust(left=0.2)

    # Create an array for the y-axis positions
    y = np.arange(len(categories))

    # Plot the first stacked bars and annotate with percentages
    bars1 = ax.barh(y, real_values, label='Real World', color='blue')
    for i, bar, percentage in zip(y, bars1, percentages1):
        width = bar.get_width()
        

    # Plot the second stacked bars on top of the first ones and annotate with percentages
    bars2 = ax.barh(y, dataset_values, label="Dataset", color='red', left=real_values)
    for i, bar, percentage in zip(y, bars2, percentages2):
        width = bar.get_width()
        

    # Customize the y-axis labels
    ax.set_yticks(y)
    ax.set_yticklabels(categories, fontsize=10, rotation=45, ha="right")

    # Add labels and legend
    ax.set_xlabel('Values')
    ax.set_ylabel('Categories')
    ax.set_title('Real World vs Dataset Representation Rates')
    ax.legend()
    plt.tight_layout()


    # Save the chart to BytesIO and encode as base64
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png')
    img_buf.seek(0)
    img_base64 = base64.b64encode(img_buf.read()).decode('utf-8')

    # Add the base64-encoded image to the dictionary under a separate key
    final_dict["Comparison Visualization"] = img_base64

    plt.close()  # Close the plot to free up resources

    return {"Comparisons": final_dict}
