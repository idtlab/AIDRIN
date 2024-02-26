import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import base64
from io import BytesIO
import os

# Function to add Laplace noise
def add_laplace_noise(data, epsilon):
    scale = 1 / epsilon
    noise = np.random.laplace(0, scale, len(data))
    return data + noise

def return_noisy_stats(df, add_noise_columns, epsilon):
    df_drop_na = df.dropna()
    df_drop_na = df_drop_na.reset_index(inplace=False)

    stat_dict = {}
    combined_image = None

    num_columns = len(add_noise_columns)

    # Set the maximum number of columns per row
    max_columns_per_row = 2
    num_rows = (num_columns + max_columns_per_row - 1) // max_columns_per_row
    num_cols = min(num_columns, max_columns_per_row)

    # Create subplots for the box plots
    fig, axes = plt.subplots(num_rows, num_cols, figsize=(8, 8))

    for i, column in enumerate(add_noise_columns):
        if num_rows == 1 and num_cols == 1:
            current_ax = axes
        elif num_rows == 1:
            current_ax = axes[i % num_cols]
        elif num_cols == 1:
            current_ax = axes[i % num_rows, 0]
        else:
            row, col = divmod(i, num_cols)
            current_ax = axes[row, col]

        noisy_feature = add_laplace_noise(df_drop_na[column], epsilon)

        # Calculate summary statistics
        mean_norm = np.mean(df_drop_na[column])
        variance_norm = np.var(df_drop_na[column])
        mean_noisy = np.mean(noisy_feature)
        variance_noisy = np.var(noisy_feature)

        stat_dict[f"Mean of feature {column}(before noise)"] = mean_norm
        stat_dict[f"Variance of feature {column}(before noise)"] = variance_norm
        stat_dict[f"Mean of feature {column}(after noise)"] = mean_noisy
        stat_dict[f"Variance of feature {column}(after noise)"] = variance_noisy
        stat_dict['Description'] = "The numerical features have been augmented with privacy-preserving measures through the addition of random Laplacian noise. This intentional introduction of noise ensures differential privacy guarantees. The accompanying box plots visually compare the distributions of the original and privacy-enhanced data"
        df_drop_na[f'noisy_{column}'] = noisy_feature

        # Box plot for the normal feature
        current_ax.boxplot(df_drop_na[column], positions=[0], widths=0.6, showfliers=False)
        current_ax.set_title(f'Normal vs Noisy representations: Feature {column}')
        current_ax.set_ylabel('Value')

        # Box plot for the noisy feature
        current_ax.boxplot(noisy_feature, positions=[1], widths=0.6, showfliers=False)
        current_ax.set_ylabel('Value')
    
    # Adjust the spacing between subplots
    plt.tight_layout()

    # Save the chart as BytesIO
    img_buf = BytesIO()
    plt.savefig(img_buf, format='png')
    img_buf.seek(0)

    # Encode the combined image as base64
    combined_image_base64 = base64.b64encode(img_buf.getvalue()).decode('utf-8')
    img_buf.close()

    try:
        # Create the new directory
        os.makedirs("noisy", exist_ok=True)
        df_drop_na.to_csv("noisy/noisy_data.csv", index=False)
        stat_dict['Noisy file saved'] = "Successful"
    except Exception as e:
        stat_dict['Noisy file saved'] = "Error"

    stat_dict['Combined Plots'] = combined_image_base64

    return stat_dict
