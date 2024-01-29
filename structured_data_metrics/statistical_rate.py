import numpy as np
import matplotlib.pyplot as plt
import base64
import io



def calculate_statistical_rates(dataframe, y_true_column, sensitive_attribute_column):
    
    try:    
        # Drop rows with NaN values in the specified columns
        dataframe_cleaned = dataframe.dropna(subset=[y_true_column, sensitive_attribute_column])

        # Extract unique sensitive attribute values and class labels
        unique_sensitive_values = dataframe_cleaned[sensitive_attribute_column].unique()
        unique_class_labels = dataframe_cleaned[y_true_column].unique()

        # Calculate proportions for each class within each unique sensitive attribute value
        class_proportions = {}
        for sensitive_value in unique_sensitive_values:
            mask_sensitive = (dataframe_cleaned[sensitive_attribute_column] == sensitive_value)
            
            class_proportions[sensitive_value] = {}
            
            total_samples_sensitive = np.sum(mask_sensitive)
            
            for class_label in unique_class_labels:
                mask_class = (dataframe_cleaned[y_true_column] == class_label)
                mask_combined = mask_sensitive & mask_class
                
                # Calculate proportion within class
                proportion = np.sum(mask_combined) / total_samples_sensitive
                class_proportions[sensitive_value][class_label] = proportion

        # Extract unique class labels
        unique_class_labels = sorted(dataframe_cleaned[y_true_column].unique())

        # Set up the plot
        fig, ax = plt.subplots(figsize=(8, 8))

        # Iterate through each unique class label
        for i, class_label in enumerate(unique_class_labels):
            # Extract proportions for the current class label
            proportions = [class_proportions[sensitive_value].get(class_label, 0) for sensitive_value in unique_sensitive_values]
            
            # Plot the bars for each sensitive attribute value
            bar_width = 0.1
            bar_positions = np.arange(len(unique_sensitive_values)) + i * bar_width
            ax.bar(bar_positions, proportions, width=bar_width, label=f'Class: {class_label}')

        # Set up labels and title
        ax.set_xticks(np.arange(len(unique_sensitive_values)) + (len(unique_class_labels) - 1) * bar_width / 2)
        ax.set_xticklabels(unique_sensitive_values, rotation=30, ha="right", fontsize=8)  # Adjust fontsize and rotation
        ax.set_xlabel('Sensitive Attribute')
        ax.set_ylabel('Proportion')
        ax.set_title('Class Proportions for Each Sensitive Attribute')
        ax.legend()

        # Adjust the bottom margin to avoid xticks being cropped
        plt.subplots_adjust(bottom=0.25)

        # Save the plot as a base64 string
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        base64_plot = base64.b64encode(buffer.read()).decode('utf-8')
        # Close the BytesIO stream
        buffer.close()
                
        return {"Statistical Rates": class_proportions,"class_proportions_plot":base64_plot }
    
    except Exception as e:
        return {"Error": str(e)}

