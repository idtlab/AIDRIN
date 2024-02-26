# import pandas as pd
# import numpy as np
# import shap
# from sklearn.model_selection import train_test_split
# from sklearn.ensemble import RandomForestRegressor
# from sklearn.metrics import mean_squared_error
# import matplotlib.pyplot as plt
# import io
# import base64

# def calc_shapley(df, cat_cols, num_cols, target_col):
#     """
#     Calculate Shapley values and other metrics for a predictive model.

#     Parameters:
#         - df (pd.DataFrame): The input DataFrame.
#         - cat_cols (list): List of categorical column names.
#         - num_cols (list): List of numerical column names.
#         - target_col (str): The target column name.

#     Returns:
#         - dict: A dictionary containing RMSE and top 3 features based on Shapley values.
#     """
#     final_dict = {}

#     try:
#         # Drop rows with missing values
#         df = df.dropna()

#         if df.empty:
#             raise ValueError("After dropping missing values, the DataFrame is empty.")
#         # Check if cat_cols or num_cols is an empty list
#         if cat_cols == [""]:
#             cat_cols = []
#         if num_cols == [""]:
#             num_cols = []

#         # If cat_cols is an empty list, only use num_cols
#         if not cat_cols and num_cols:
#             selected_cols = num_cols
#         # If num_cols is an empty list, only use cat_cols
#         elif cat_cols and not num_cols:
#             selected_cols = cat_cols
#         # If both cat_cols and num_cols are provided, use all specified columns
#         else:
#             selected_cols = cat_cols + num_cols

#         # Check if specified columns are present in the DataFrame
#         if not set(selected_cols).issubset(df.columns):
#             raise ValueError("Specified columns not found in the DataFrame.")

#         # Convert categorical columns to dummy variables if cat_cols are present
#         if cat_cols:
#             data = pd.get_dummies(df[cat_cols], drop_first=False)
#         else:
#             data = pd.DataFrame()

#         # Include numerical columns if num_cols are present
#         if num_cols:
#             data = pd.concat([data, df[num_cols]], axis=1)

#         # Convert target column to numerical
#         target = pd.get_dummies(df[target_col]).astype(float)

#         data = data.astype(float)

#         # Split the dataset into train and test sets
#         X_train, X_test, y_train, y_test = train_test_split(data, target, test_size=0.2, random_state=0)

#         # Create a regressor model
#         model = RandomForestRegressor(n_estimators=100, random_state=0)
#         model.fit(X_train, y_train)

#         # Make predictions
#         y_pred = model.predict(X_test)

#         # Calculate RMSE
#         rmse = np.sqrt(mean_squared_error(y_test, y_pred))

#         # Create an explainer for the model
#         explainer = shap.Explainer(model, X_test)

#         # Convert DataFrame to NumPy array for indexing
#         X_test_np = X_test.values

#         # Calculate Shapley values for all instances in the test set
#         shap_values = explainer.shap_values(X_test_np)

#         class_names = y_test.columns

#         # Calculate the mean absolute Shapley values for each feature across instances
#         mean_shap_values = np.abs(shap_values).mean(axis=(0, 1))  # Assuming shap_values is a 3D array

#         # Get feature names
#         feature_names = X_test.columns

#         # Sort features by mean absolute Shapley values in descending order
#         sorted_indices = np.argsort(mean_shap_values)[::-1]

#         # Plot the bar chart
#         plt.figure(figsize=(8, 8))
#         plt.bar(range(len(mean_shap_values)), mean_shap_values[sorted_indices], align="center")
#         plt.xticks(range(len(mean_shap_values)), feature_names[sorted_indices], rotation=45, ha="right")
#         plt.xlabel("Feature")
#         plt.ylabel("Mean Absolute Shapley Value")
#         plt.title("Feature Importances")
#         plt.tight_layout()  # Adjust layout

#         # Save the plot to a file
#         image_stream = io.BytesIO()
#         plt.savefig(image_stream, format='png')
#         plt.close()

#         # Convert the image to a base64-encoded string
#         base64_image = base64.b64encode(image_stream.getvalue()).decode('utf-8')
#         # Close the BytesIO stream
#         image_stream.close()

#         # Convert shap_values to a numpy array
#         shap_values = np.array(shap_values)

#         # Get feature names
#         feature_names = X_test.columns.tolist()

#         # Create a summary dictionary
#         summary_dict = {}

#         # Loop through each class
#         for class_index, class_name in enumerate(class_names):
#             class_shap_values = shap_values[class_index]

#             # Compute the mean of the absolute values of SHAP values for each feature
#             class_summary = {feature: np.mean(np.abs(shap_values[:, feature_index]))
#                              for feature_index, feature in enumerate(feature_names)}

#             # Add the class dictionary to the summary dictionary
#             summary_dict["{} {}".format(target_col, class_name)] = class_summary

#         final_dict["RMSE"] = rmse
#         final_dict['Summary of Shapley Values'] = summary_dict
#         final_dict['summary plot'] = base64_image

#     except Exception as e:
#         final_dict["Error"] = f"An error occurred: {str(e)}"

#     return final_dict


import io
import base64
from scipy.stats import chi2_contingency
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd

def plot_to_base64(plt):
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close()
    return image_base64

def generate_combined_plot_to_base64(df, cat_cols, num_cols, target_col):

    try:
        # Check if the DataFrame is empty
        if df.empty:
            raise ValueError("Input DataFrame is empty.")

        # Check if the target column is present in the DataFrame
        if target_col not in df.columns:
            raise ValueError(f"Target column '{target_col}' not found in the DataFrame.")

        if cat_cols == [""]:
            cat_cols = []
        if num_cols == [""]:
            num_cols = []

        plt.figure(figsize=(10, 10))

        # Check if the target column is categorical or numerical
        if df[target_col].dtype == 'O':  # 'O' stands for Object (categorical)
            # Generate box plots for numerical columns vs target column
            for i, num_col in enumerate(num_cols, start=1):
                plt.subplot(2, len(num_cols), i)
                sns.boxplot(x=df[target_col], y=df[num_col])
                plt.title(f'{num_col} vs {target_col} (Box Plot)')
                plt.xticks(rotation=45)

            # Generate appropriate plots for categorical columns vs target column
            for i, cat_col in enumerate(cat_cols, start=len(num_cols) + 1):
                plt.subplot(2, len(cat_cols), i)
                sns.countplot(x=df[cat_col], hue=df[target_col])
                plt.title(f'{cat_col} vs {target_col} (Count Plot)')
                plt.xticks(rotation=45)
            
            # Perform chi-squared test for independence
            chi2_scores = {}
            for cat_col in cat_cols:
                contingency_table = pd.crosstab(df[cat_col], df[target_col])
                _, p_value, _, _ = chi2_contingency(contingency_table)
                chi2_scores[cat_col] = p_value


        else:  # Target column is numerical
            # Generate scatter plots for numerical columns vs target column
            for i, num_col in enumerate(num_cols, start=1):
                plt.subplot(2, len(num_cols), i)
                sns.scatterplot(x=df[num_col], y=df[target_col])
                plt.title(f'{num_col} vs {target_col} (Scatter Plot)')
                plt.xticks(rotation=45)

            # Generate appropriate plots for categorical columns vs target column
            for i, cat_col in enumerate(cat_cols, start=len(num_cols) + 1):
                plt.subplot(2, len(cat_cols), i)
                sns.boxplot(x=df[cat_col], y=df[target_col])
                plt.title(f'{cat_col} vs {target_col} (Box Plot)')
                plt.xticks(rotation=45)

            # Perform chi-squared test for independence
            chi2_scores = {}
            for cat_col in cat_cols:
                contingency_table = pd.crosstab(df[cat_col], df[target_col])
                _, p_value, _, _ = chi2_contingency(contingency_table)
                chi2_scores[cat_col] = p_value

        # Adjust layout parameters to avoid overlaps
        plt.tight_layout()

        combined_plot_base64 = plot_to_base64(plt)
        return {'summary plot': combined_plot_base64,'chi2_scores': chi2_scores}
    except Exception as e:
        return {"Error": f"An error occurred: {str(e)}"}

# Example usage:
# combined_plot = generate_combined_plot_to_base64(your_dataframe, ['cat_col1', 'cat_col2'], ['num_col1', 'num_col2'], 'target_col')
# print(combined_plot)

