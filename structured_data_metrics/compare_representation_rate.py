import matplotlib.pyplot as plt
import os
import numpy as np

def compare_rep_rates(rep_dict,rrr_dict):
    final_dict = {}
    
    real_values = []
    dataset_values = []
    categories = []
    common_keys = set(rep_dict.keys()) & set(rrr_dict.keys())
    # Compare values of common keys
    for key in common_keys:
        value1 = rep_dict[key]
        value2 = rrr_dict[key]

        feature_from = key.split("'")[3]
        feature_to = key.split("'")[5]
        difference_key = f"Real vs Dataset Representation rate difference in '{feature_from}' to '{feature_to}'"
        final_dict[difference_key] = abs(value2 - value1)

        categories.append(key)
        real_values.append(value2)
        dataset_values.append(value1)

    # Calculate the total for each category
    totals = [v1 + v2 for v1, v2 in zip(real_values, dataset_values)]

    # Calculate the percentages for each stack
    percentages1 = [(v1 / total) * 100 for v1, total in zip(real_values, totals)]
    percentages2 = [(v2 / total) * 100 for v2, total in zip(dataset_values, totals)]

    
    # Create figure and axes
    fig, ax = plt.subplots()

    # Create an array for the y-axis positions
    y = np.arange(len(categories))

    # Plot the first stacked bars and annotate with percentages
    bars1 = ax.barh(y, real_values, label='Real World', color='blue')
    for i, bar, percentage in zip(y, bars1, percentages1):
        width = bar.get_width()
        ax.annotate(f'{percentage:.1f}%', (width / 2, i),
                    ha='center', va='center', fontsize=7.5, color='black')

    # Plot the second stacked bars on top of the first ones and annotate with percentages
    bars2 = ax.barh(y, dataset_values, label="Dataset", color='red', left=real_values)
    for i, bar, percentage in zip(y, bars2, percentages2):
        width = bar.get_width()
        ax.annotate(f'{percentage:.1f}%', (width / 2 + real_values[i], i),
                    ha='center', va='center', fontsize=7.5, color='black')

    # Customize the y-axis labels
    ax.set_yticks(y)
    ax.set_yticklabels(categories,fontsize=5)

    # Add labels and legend
    ax.set_xlabel('Values')
    ax.set_ylabel('Categories')
    ax.set_title('Real World vs Dataset Representation Rates')
    ax.legend()
    # Specify the folder name
    folder_name = "Visualizations"

    # Ensure that the folder exists, or create it if it doesn't
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    name = "Real vs Dataset Representation Rates"
    # Save the chart inside the "Visualizations" folder
    plt.savefig(os.path.join(folder_name, f"{name}_chart.png"))
    return {"Comparisons":final_dict}