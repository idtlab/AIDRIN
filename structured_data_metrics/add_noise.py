import numpy as np
import os
import pandas as pd
import matplotlib.pyplot as plt

# Function to add Laplace noise
def add_laplace_noise(data, epsilon):
    scale = 1 / epsilon
    noise = np.random.laplace(0, scale, len(data))
    return data + noise

def return_noisy_stats(df,add_noise_columns,epsilon):
    df_drop_na = df.dropna()
    df_drop_na = df_drop_na.reset_index(inplace=False)

    stat_dict = {}
    for i in range(len(add_noise_columns)):
        noisy_feature = add_laplace_noise(df_drop_na[add_noise_columns[i]], epsilon)

        # Calculate summary statistics
        mean_norm = np.mean(df_drop_na[add_noise_columns[i]])
        variance_norm = np.var(df_drop_na[add_noise_columns[i]])
        mean_noisy = np.mean(noisy_feature)
        variance_noisy = np.var(noisy_feature)

        stat_dict["Mean of feature {}(before noise)".format(add_noise_columns[i])] = mean_norm
        stat_dict["Variance of feature {}(before noise)".format(add_noise_columns[i])] = variance_norm
        stat_dict["Mean of feature {}(after noise)".format(add_noise_columns[i])] = mean_noisy
        stat_dict["Variance of feature {}(after noise)".format(add_noise_columns[i])] = variance_noisy
        stat_dict['Description'] = "Random Laplacian noise added to the provided numerical feature to generate privacy-preserving data with differential privacy guarantees."
        df_drop_na['noisy_{}'.format(add_noise_columns[i])] = noisy_feature

        
        # Create a figure with two subplots for the box plots
        plt.figure(figsize=(10, 5))

        # Box plot for the noisy feature
        plt.subplot(1, 2, 1)
        plt.boxplot(noisy_feature)
        plt.title('Box Plot for Noisy Feature')
        plt.ylabel('Value')

        # Box plot for the normal feature
        plt.subplot(1, 2, 2)
        plt.boxplot(df_drop_na[add_noise_columns[i]])
        plt.title('Box Plot for Normal Feature')
        plt.ylabel('Value')

        # Adjust the spacing between subplots
        plt.tight_layout()

        # Specify the folder name
        folder_name = "Visualizations"

        # Ensure that the folder exists, or create it if it doesn't
        if not os.path.exists(folder_name):
            os.makedirs(folder_name)

        name = "{} Normal vs Noisy Box Plot".format(add_noise_columns[i])
        # Save the chart inside the "Visualizations" folder
        plt.savefig(os.path.join(folder_name, f"{name}_chart.png"))


    
    try:
        # Create the new directory
        os.makedirs("noisy", exist_ok=True)
        df_drop_na.to_csv("noisy/noisy_data.csv",index=False)
        stat_dict['Noisy file saved']="Successfull"
    except Exception as e:
        stat_dict['Noisy file saved']="Error"
    
    

    return stat_dict