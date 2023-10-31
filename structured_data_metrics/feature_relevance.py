import pandas as pd
import numpy as np
import shap
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
import matplotlib.pyplot as plt
import io
import base64

def calc_shapley(df, cat_cols, num_cols, target_col):
    """
    Calculate Shapley values and other metrics for a predictive model.

    Parameters:
        - df (pd.DataFrame): The input DataFrame.
        - cat_cols (list): List of categorical column names.
        - num_cols (list): List of numerical column names.
        - target_col (str): The target column name.

    Returns:
        - dict: A dictionary containing RMSE and top 3 features based on Shapley values.
    """
    final_dict = {}

    try:
        # Drop rows with missing values
        df = df.dropna()

        # Check if cat_cols and num_cols are not empty
        if not cat_cols or not num_cols:
            raise ValueError("cat_cols and num_cols must not be empty.")

        # Check if specified columns are present in the DataFrame
        if not set(cat_cols).issubset(df.columns) or not set(num_cols).issubset(df.columns):
            raise ValueError("Specified columns not found in the DataFrame.")


        # Convert categorical columns to dummy variables
        data = pd.get_dummies(df[cat_cols], drop_first=True)
        data = pd.concat([df[num_cols], data], axis=1)

        # Convert target column to numerical
        target = pd.get_dummies(df[target_col]).astype(float)

        data = data.astype(float)

        # Split the dataset into train and test sets
        X_train, X_test, y_train, y_test = train_test_split(data, target, test_size=0.2, random_state=0)

        # Create a regressor model
        model = RandomForestRegressor(n_estimators=100, random_state=0)
        model.fit(X_train, y_train)

        # Make predictions
        y_pred = model.predict(X_test)

        # Calculate RMSE
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))

        # Create an explainer for the model
        explainer = shap.Explainer(model, X_test)

        # Convert DataFrame to NumPy array for indexing
        X_test_np = X_test.values

        # Calculate Shapley values for all instances in the test set
        shap_values = explainer.shap_values(X_test_np)

        class_names = y_test.columns

       # Calculate the mean absolute Shapley values for each feature across instances
        mean_shap_values = np.abs(shap_values).mean(axis=(0, 1))  # Assuming shap_values is a 3D array

        # Get feature names
        feature_names = X_test.columns

        # Sort features by mean absolute Shapley values in descending order
        sorted_indices = np.argsort(mean_shap_values)[::-1]

        # Plot the bar chart
        plt.figure(figsize=(8, 8))
        plt.bar(range(len(mean_shap_values)), mean_shap_values[sorted_indices], align="center")
        plt.xticks(range(len(mean_shap_values)), feature_names[sorted_indices], rotation=45, ha="right")
        plt.xlabel("Feature")
        plt.ylabel("Mean Absolute Shapley Value")
        plt.title("Feature Importances")
        plt.tight_layout()  # Adjust layout
        
        
        # Save the plot to a file
        image_stream = io.BytesIO()
        plt.savefig(image_stream, format='png')
        plt.close()

        

        # Convert the image to a base64-encoded string
        base64_image = base64.b64encode(image_stream.getvalue()).decode('utf-8')
        # Close the BytesIO stream
        image_stream.close()

        # Convert shap_values to a numpy array
        shap_values = np.array(shap_values)

        # Get feature names
        feature_names = X_test.columns.tolist()

        # Create a summary dictionary
        summary_dict = {}

        # Loop through each class
        for class_index, class_name in enumerate(class_names):
            class_shap_values = shap_values[class_index]
            
            # Compute the mean of the absolute values of SHAP values for each feature
            class_summary = {feature: np.mean(np.abs(shap_values[:, feature_index]))
                            for feature_index, feature in enumerate(feature_names)}
            
            # Add the class dictionary to the summary dictionary
            summary_dict["{} {}".format(target_col,class_name)] = class_summary
            
        final_dict["RMSE"] = rmse
        final_dict['Summary of Shapley Values'] = summary_dict
        final_dict['summary plot'] = base64_image

 
    except Exception as e:
        final_dict["Error"] = f"An error occurred: {str(e)}"

    return final_dict
