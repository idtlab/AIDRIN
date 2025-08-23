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
        print(f"Starting data_cleaning with cat_cols: {cat_cols}, num_cols: {num_cols}, target_col: {target_col}")

        try:
            df = read_file(file_info)
            print(f"File read successfully. DataFrame shape: {df.shape}")
            print(f"DataFrame columns: {list(df.columns)}")
            print(f"DataFrame dtypes: {df.dtypes.to_dict()}")
        except Exception as e:
            print(f"Error reading file: {e}")
            return {
                "Error": "Failed to read the file. Please check the file path and type."
            }

        # Filter DataFrame to include only the specified columns
        selected_columns = [target_col] + cat_cols + num_cols
        print(f"Selected columns: {selected_columns}")

        # Check if all columns exist
        missing_columns = [col for col in selected_columns if col not in df.columns]
        if missing_columns:
            return {"Error": f"Columns not found in dataset: {missing_columns}"}

        # Validate that at least some features are selected
        if not cat_cols and not num_cols:
            return {
                "Error": "No features selected for analysis. Please select at least one categorical or numerical feature from the checkboxes above."
            }

        df_filtered = df[selected_columns].copy()
        print(f"Filtered DataFrame shape: {df_filtered.shape}")

        # Fill missing values more robustly
        if cat_cols:  # Only process if there are categorical columns
            for col in cat_cols:
                try:
                    print(f"Processing categorical column: {col}")
                    print(f"Column {col} unique values before fillna: {df_filtered[col].nunique()}")
                    df_filtered[col] = df_filtered[col].fillna("Missing")
                    print(f"Column {col} unique values after fillna: {df_filtered[col].nunique()}")
                except Exception as e:
                    print(f"Warning: Error filling missing values in categorical column {col}: {e}")
                    # Fallback: replace NaN with a default value
                    df_filtered[col] = df_filtered[col].astype(str).replace('nan', 'Missing')
        else:
            print("No categorical columns to process")

        if num_cols:  # Only process if there are numerical columns
            for col in num_cols:
                try:
                    print(f"Processing numerical column: {col}")
                    print(f"Column {col} data type: {df_filtered[col].dtype}")
                    # Calculate mean safely
                    col_mean = df_filtered[col].mean()
                    if pd.isna(col_mean):
                        col_mean = 0.0
                    print(f"Column {col} mean: {col_mean}")
                    df_filtered[col] = df_filtered[col].fillna(col_mean)
                except Exception as e:
                    print(f"Warning: Error filling missing values in numerical column {col}: {e}")
                    # Fallback: replace NaN with 0
                    df_filtered[col] = df_filtered[col].fillna(0.0)
        else:
            print("No numerical columns to process")

        # One-hot encode categorical columns only if they exist
        if cat_cols:
            try:
                print(f"Starting one-hot encoding for {len(cat_cols)} categorical columns...")
                df_filtered = pd.get_dummies(df_filtered, columns=cat_cols)
                print(f"One-hot encoding completed. DataFrame now has {df_filtered.shape[1]} columns.")
            except Exception as e:
                print(f"Error during one-hot encoding: {e}")
                return {"Error": f"One-hot encoding failed: {str(e)}"}
        else:
            print("No categorical columns to encode")

        # Encode target variable if categorical
        if df_filtered[target_col].dtype == "object":
            try:
                print(f"Encoding target column {target_col}...")
                le_target = LabelEncoder()
                df_filtered[target_col] = le_target.fit_transform(df_filtered[target_col])
                print(f"Target column {target_col} encoded successfully.")
            except Exception as e:
                print(f"Error encoding target column: {e}")
                return {"Error": f"Target column encoding failed: {str(e)}"}

        # Convert to JSON more safely
        try:
            print("Converting DataFrame to JSON format...")
            result = df_filtered.to_dict(orient="list")
            print(f"Data cleaning completed successfully. Final data shape: {df_filtered.shape}")
            return result
        except Exception as e:
            print(f"Error converting to JSON: {e}")
            return {"Error": f"JSON conversion failed: {str(e)}"}

    except SoftTimeLimitExceeded:
        print("Data Cleaning task timed out.")
        raise Exception("Data Cleaning task timed out.")
    except Exception as e:
        print(f"Error occurred during data cleaning: {e}")
        return {"Error": f"Data cleaning failed: {str(e)}"}


@shared_task(bind=True, ignore_result=False)
def pearson_correlation(self: Task, df_json, target_col) -> dict:
    try:
        print(f"Starting pearson_correlation with target_col: {target_col}")
        print(f"Input df_json type: {type(df_json)}")
        if isinstance(df_json, dict):
            print(f"Input df_json keys: {list(df_json.keys())}")

        # Convert JSON back to DataFrame with proper error handling
        try:
            df = pd.DataFrame.from_dict(df_json)
            print(f"DataFrame created successfully. Shape: {df.shape}")
            print(f"DataFrame columns: {list(df.columns)}")
            print(f"DataFrame dtypes: {df.dtypes.to_dict()}")
        except Exception as e:
            print(f"Error converting JSON to DataFrame: {e}")
            return {"Error": f"Failed to convert data: {str(e)}"}

        # Ensure target column exists
        if target_col not in df.columns:
            print(f"Target column '{target_col}' not found. Available columns: {list(df.columns)}")
            return {"Error": f"Target column '{target_col}' not found in the data"}

        # Get columns excluding target column
        cols = df.columns.difference([target_col])
        if len(cols) == 0:
            print("No feature columns found for correlation analysis")
            return {"Error": "No feature columns found for correlation analysis"}

        print(f"Processing {len(cols)} feature columns: {list(cols)}")

        correlations = {}
        for col in cols:
            if col != target_col:
                try:
                    print(f"Processing column: {col}")
                    print(f"Column {col} dtype: {df[col].dtype}")
                    print(f"Target column {target_col} dtype: {df[target_col].dtype}")

                    # Ensure both columns are numeric
                    if not pd.api.types.is_numeric_dtype(df[col]) or not pd.api.types.is_numeric_dtype(df[target_col]):
                        print(f"Warning: Skipping column '{col}' - non-numeric data types")
                        continue

                    # Remove any NaN values for this specific column pair
                    valid_data = df[[col, target_col]].dropna()
                    if len(valid_data) < 2:
                        print(f"Warning: Skipping column '{col}' - insufficient valid data after removing NaN values")
                        continue

                    print(f"Column {col} valid data points: {len(valid_data)}")

                    # Calculate covariance
                    cov = np.cov(valid_data[col], valid_data[target_col], ddof=0)[0, 1]
                    # Calculate standard deviations
                    std_dev_col = np.std(valid_data[col], ddof=0)
                    std_dev_target = np.std(valid_data[target_col], ddof=0)

                    # Check for division by zero
                    if std_dev_col == 0 or std_dev_target == 0:
                        print(f"Warning: Skipping column '{col}' - zero standard deviation")
                        continue

                    # Calculate Pearson correlation coefficient
                    corr = cov / (std_dev_col * std_dev_target)

                    # Ensure correlation is a valid number
                    if np.isfinite(corr):
                        correlations[col] = float(corr)  # Convert to Python float for JSON serialization
                        print(f"Column {col} correlation: {corr}")
                    else:
                        print(f"Warning: Skipping column '{col}' - invalid correlation value: {corr}")

                except Exception as e:
                    print(f"Warning: Error calculating correlation for column '{col}': {e}")
                    continue

        if not correlations:
            print("No valid correlations could be calculated")
            return {"Error": "No valid correlations could be calculated"}

        print(f"Successfully calculated correlations for {len(correlations)} features")
        return correlations

    except SoftTimeLimitExceeded:
        raise Exception("Pearson Correlation task timed out.")
    except Exception as e:
        print(f"Unexpected error in pearson_correlation: {e}")
        return {"Error": f"Correlation calculation failed: {str(e)}"}


@shared_task(bind=True, ignore_result=False)
def plot_features(self: Task, correlations, target_col):
    try:
        # Validate input data
        if not correlations or not isinstance(correlations, dict):
            raise ValueError("Invalid correlations data provided")

        # Extract features and correlation values
        features = list(correlations.keys())
        corr_values = list(correlations.values())

        if not features or not corr_values:
            raise ValueError("No features or correlation values found")

        if len(features) != len(correlations):
            raise ValueError("Mismatch between features and correlation values")

        # Clean feature names for plotting (remove any problematic characters)
        clean_features = []
        for feat in features:
            if feat is None:
                clean_features.append("Unknown")
            else:
                # Convert to string and clean any problematic characters
                clean_feat = str(feat).strip()
                if not clean_feat:
                    clean_feat = "Unknown"
                clean_features.append(clean_feat)

        # Ensure correlation values are valid numbers
        clean_corr_values = []
        for val in corr_values:
            try:
                clean_val = float(val)
                if np.isfinite(clean_val):
                    clean_corr_values.append(clean_val)
                else:
                    clean_corr_values.append(0.0)
            except (ValueError, TypeError):
                clean_corr_values.append(0.0)

        if len(clean_features) != len(clean_corr_values):
            raise ValueError("Mismatch between cleaned features and correlation values")

        # Create the plot
        plt.figure(figsize=(max(8, len(clean_features) * 0.8), 8))
        bars = plt.bar(range(len(clean_features)), clean_corr_values, color="skyblue")

        # Add a horizontal line at y=0
        plt.axhline(y=0, color="black", linewidth=0.5)
        plt.title(f"Correlation of Features with {target_col}")
        plt.xlabel("Features")
        plt.ylabel("Correlation")

        # Set x-axis labels
        plt.xticks(range(len(clean_features)), clean_features, rotation=45, ha="right")

        # Add value labels on bars if there are few features
        if len(clean_features) <= 20:
            for i, (bar, val) in enumerate(zip(bars, clean_corr_values)):
                height = bar.get_height()
                plt.text(
                    bar.get_x() + bar.get_width()/2., height,
                    f'{val:.3f}',
                    ha='center', va='bottom' if height >= 0 else 'top'
                )

        plt.tight_layout()

        # Save the plot to a BytesIO object and encode it as base64
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100, bbox_inches='tight')
        plt.close()
        buf.seek(0)
        image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        print(f"Successfully created visualization with {len(clean_features)} features")
        return image_base64

    except SoftTimeLimitExceeded:
        print("Plot Features task timed out.")
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
