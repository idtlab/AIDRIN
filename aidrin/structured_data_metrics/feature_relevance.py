import base64
import io

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sklearn.preprocessing import LabelEncoder

from aidrin.file_handling.file_parser import read_file

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


@shared_task(bind=True, ignore_result=False)
def data_cleaning(self: Task, cat_cols, num_cols, target_col, file_info):
    try:
        try:
            df = read_file(file_info)
        except Exception as e:
            print(f"Error reading file: {e}")
            return {
                "Error": "Failed to read the file. Please check the file path and type."
            }
        # Filter DataFrame to include only the specified columns
        # Make a copy to avoid SettingWithCopyWarning
        df_filtered = df[[target_col] + cat_cols + num_cols].copy()
        # Fill missing values
        df_filtered.loc[:, cat_cols] = df_filtered[cat_cols].fillna(
            "Missing"
        )  # Use .loc to set values
        df_filtered.loc[:, num_cols] = df_filtered[num_cols].fillna(
            df_filtered[num_cols].mean()
        )  # Use .loc to set values

        # One-hot encode categorical columns
        df_filtered = pd.get_dummies(df_filtered, columns=cat_cols)

        # Encode target variable if categorical
        if df_filtered[target_col].dtype == "object":
            le_target = LabelEncoder()
            df_filtered[target_col] = le_target.fit_transform(df_filtered[target_col])
        # need to make json serializable to be passed by celery
        return df_filtered.to_dict(orient="list")
    except SoftTimeLimitExceeded:
        raise Exception("Data Cleaning task timed out.")
    except Exception as e:
        print(f"Error occurred during data cleaning: {e}")


@shared_task(bind=True, ignore_result=False)
def pearson_correlation(self: Task, df_json, target_col) -> dict:
    try:
        df = pd.DataFrame.from_dict(df_json)
        cols = df.columns.difference([target_col])
        correlations = {}
        for col in cols:
            if col != target_col:
                try:
                    # Calculate covariance
                    cov = np.cov(df[col], df[target_col], ddof=0)[0, 1]
                    # Calculate standard deviations
                    std_dev_col = np.std(df[col], ddof=0)
                    std_dev_target = np.std(df[target_col], ddof=0)
                    # Calculate Pearson correlation coefficient
                    corr = cov / (std_dev_col * std_dev_target)
                    correlations[col] = corr
                except TypeError:
                    print(
                        f"Warning: Skipping correlation calculation for column '{col}' due to non-numeric values."
                    )
        return correlations
    except SoftTimeLimitExceeded:
        raise Exception("Pearson Correlation task timed out.")


@shared_task(bind=True, ignore_result=False)
def plot_features(self: Task, correlations, target_col):
    try:
        # Extract features and correlation values
        features = list(correlations.keys())
        corr_values = list(correlations.values())

        plt.figure(figsize=(8, 8))
        plt.bar(features, corr_values, color="skyblue")  # Vertical bar plot
        # Add a horizontal line at y=0
        plt.axhline(y=0, color="black", linewidth=0.5)
        plt.title(f"Correlation of Features with {target_col}")
        plt.xlabel("Features")
        plt.ylabel("Correlation")

        # Angle the xticks
        plt.xticks(rotation=45, ha="right")

        # Add leading dots to xticks longer than 8 characters
        formatted_features = [
            feat if len(feat) <= 8 else feat[:5] + "..." for feat in features
        ]
        plt.xticks(range(len(features)), formatted_features)

        # Save the plot to a BytesIO object and encode it as base64
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close()
        buf.seek(0)
        image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return image_base64
    except SoftTimeLimitExceeded:
        raise Exception("Plot Features task timed out.")
    except Exception as e:
        print(f"Error occurred during plotting: {e}")
        return None


# import io
# import base64
# from scipy.stats import chi2_contingency
# import matplotlib.pyplot as plt
# import seaborn as sns
# import pandas as pd

# def plot_to_base64(plt):
#     buffer = io.BytesIO()
#     plt.savefig(buffer, format='png')
#     buffer.seek(0)
#     image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
#     plt.close()
#     return image_base64

# def plot_features(df, cat_cols, num_cols, target_col):

#     # print(calc_shapley(df,cat_cols=cat_cols,num_cols=num_cols,target_col=target_col))
#     try:
#         # Check if the DataFrame is empty
#         if df.empty:
#             raise ValueError("Input DataFrame is empty.")

#         # Check if the target column is present in the DataFrame
#         if target_col not in df.columns:
#             raise ValueError(f"Target column '{target_col}' not found in the DataFrame.")

#         if cat_cols == [""]:
#             cat_cols = []
#         if num_cols == [""]:
#             num_cols = []

#         plt.figure(figsize=(10, 10))
#         plt.rcParams.update({'font.size': 16})  # Set the font size to 12

#         # Check if the target column is categorical or numerical
#         if df[target_col].dtype == 'O':  # 'O' stands for Object (categorical)
#             # Generate box plots for numerical columns vs target column
#             for i, num_col in enumerate(num_cols, start=1):
#                 plt.subplot(2, len(num_cols), i)
#                 sns.boxplot(x=df[target_col], y=df[num_col])
#                 plt.title(f'{num_col} vs {target_col}')
#                 plt.xticks(rotation=45)
#                 plt.legend().remove()  # Remove legend

#             # Generate appropriate plots for categorical columns vs target column
#             for i, cat_col in enumerate(cat_cols, start=len(num_cols) + 1):
#                 plt.subplot(2, len(cat_cols), i)
#                 sns.countplot(x=df[cat_col], hue=df[target_col])
#                 plt.title(f'{cat_col} vs {target_col}')
#                 plt.xticks(rotation=45)
#                 plt.legend().remove()  # Remove legend

#             # Perform chi-squared test for independence
#             chi2_scores = {}
#             for cat_col in cat_cols:
#                 contingency_table = pd.crosstab(df[cat_col], df[target_col])
#                 _, p_value, _, _ = chi2_contingency(contingency_table)
#                 chi2_scores[cat_col] = p_value


#         else:  # Target column is numerical
#             # Generate scatter plots for numerical columns vs target column
#             for i, num_col in enumerate(num_cols, start=1):
#                 plt.subplot(2, len(num_cols), i)
#                 sns.scatterplot(x=df[num_col], y=df[target_col])
#                 plt.title(f'{num_col} vs {target_col}')
#                 plt.xticks(rotation=45)
#                 plt.legend().remove()  # Remove legend

#             # Generate appropriate plots for categorical columns vs target column
#             for i, cat_col in enumerate(cat_cols, start=len(num_cols) + 1):
#                 plt.subplot(2, len(cat_cols), i)
#                 sns.boxplot(x=df[cat_col], y=df[target_col])
#                 plt.title(f'{cat_col} vs {target_col}')
#                 plt.xticks(rotation=45)
#                 plt.legend().remove()  # Remove legend

#             # Perform chi-squared test for independence
#             chi2_scores = {}

#             for cat_col in cat_cols:
#                 contingency_table = pd.crosstab(df[cat_col], df[target_col])
#                 _, p_value, _, _ = chi2_contingency(contingency_table)
#                 chi2_scores[cat_col] = p_value

#         # Adjust layout parameters to avoid overlaps
#         plt.tight_layout()

#         combined_plot_base64 = plot_to_base64(plt)
#         return combined_plot_base64
#     except Exception as e:
#         return {"Error": f"An error occurred: {str(e)}"}

# Example usage:
# combined_plot = generate_combined_plot_to_base64(your_dataframe, ['cat_col1', 'cat_col2'], ['num_col1', 'num_col2'], 'target_col')
# print(combined_plot)

def calculate_feature_relevance(file_info: dict, target_col: str):
    """
    Reads data, cleans it, calculates Pearson correlations of features with the target,
    and returns a matplotlib Figure with a bar plot of feature relevance.

    Args:
        file_info (dict): Information to load the dataset.
        target_col (str): Target column name.

    Returns:
        matplotlib.figure.Figure: Bar plot figure of feature correlations with target.
    """
    # Read file
    df = read_file(file_info)

    # Separate categorical and numerical columns (excluding target)
    cat_cols = df.select_dtypes(include="object").columns.tolist()
    num_cols = df.select_dtypes(exclude="object").columns.tolist()

    # Remove target column from cat_cols and num_cols if present
    if target_col in cat_cols:
        cat_cols.remove(target_col)
    if target_col in num_cols:
        num_cols.remove(target_col)

    # Filter dataframe to relevant columns + target
    df_filtered = df[[target_col] + cat_cols + num_cols].copy()

    # Fill missing values
    df_filtered.loc[:, cat_cols] = df_filtered[cat_cols].fillna("Missing")
    df_filtered.loc[:, num_cols] = df_filtered[num_cols].fillna(df_filtered[num_cols].mean())

    # One-hot encode categorical columns
    df_filtered = pd.get_dummies(df_filtered, columns=cat_cols)

    # Encode target if categorical
    if df_filtered[target_col].dtype == "object":
        le_target = LabelEncoder()
        df_filtered[target_col] = le_target.fit_transform(df_filtered[target_col])

    # Calculate Pearson correlation of each feature with target
    correlations = {}
    features = df_filtered.columns.difference([target_col])
    for feature in features:
        try:
            cov = np.cov(df_filtered[feature], df_filtered[target_col], ddof=0)[0, 1]
            std_feature = np.std(df_filtered[feature], ddof=0)
            std_target = np.std(df_filtered[target_col], ddof=0)
            corr = cov / (std_feature * std_target)
            correlations[feature] = corr
        except Exception:
            # Skip non-numeric or invalid correlations
            continue

    # Plot correlations
    fig, ax = plt.subplots(figsize=(8, 8))
    features_list = list(correlations.keys())
    corr_values = list(correlations.values())

    # Shorten long feature names
    formatted_features = [f if len(f) <= 8 else f[:5] + "..." for f in features_list]

    ax.bar(formatted_features, corr_values, color="skyblue")
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_title(f"Feature Correlation with {target_col}")
    ax.set_xlabel("Features")
    ax.set_ylabel("Pearson Correlation")
    plt.xticks(rotation=45, ha="right")

    plt.tight_layout()
    plt.show()
