import numpy as np

def calculate_statistical_rates(dataframe, y_true_column, sensitive_attribute_column):
    
    try:    
        # Drop rows with NaN values in the specified columns
        dataframe_cleaned = dataframe.dropna(subset=[y_true_column, sensitive_attribute_column])
        
        unique_sensitive_values = dataframe_cleaned[sensitive_attribute_column].unique()
        num_sensitive_values = len(unique_sensitive_values)
        
        # Convert string labels to numeric labels
        label_to_numeric = {label: i for i, label in enumerate(dataframe_cleaned[y_true_column].unique())}
        dataframe_cleaned.loc[:, 'y_true_numeric'] = dataframe_cleaned[y_true_column].map(label_to_numeric)

        
        # Calculate conditional probabilities for each sensitive attribute value
        conditional_probs = {}
        for sensitive_value in unique_sensitive_values:
            mask = (dataframe_cleaned[sensitive_attribute_column] == sensitive_value)
            probs = [np.mean(dataframe_cleaned['y_true_numeric'][mask] == class_label) for class_label in range(len(label_to_numeric))]
            conditional_probs[sensitive_value] = probs
        
        # Calculate ratios and check if they meet the threshold
        statistical_rates = {}
        for i in range(num_sensitive_values):
            for j in range(i + 1, num_sensitive_values):
                ratio = max(conditional_probs[unique_sensitive_values[i]]) / max(conditional_probs[unique_sensitive_values[j]])
                key = f"Statistical Rate for '{unique_sensitive_values[i]}' to '{unique_sensitive_values[j]}'"
                statistical_rates[key] = ratio
        
        return {"Probability ratios":statistical_rates}
    except Exception as e:
        return{"Error":"Error calculating statistical rate, include proper column names for target and"}