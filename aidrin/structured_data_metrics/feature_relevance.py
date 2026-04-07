import base64
import io

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sklearn.preprocessing import LabelEncoder

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def data_cleaning(self: Task, cat_cols, num_cols, target_col, file_info):
    """Prepare a dataset for Pearson correlation analysis.

    Reads the file, filters to the selected columns, imputes missing values
    (``"Missing"`` sentinel for categorical, column mean for numerical), one-hot
    encodes categorical columns, and label-encodes a categorical target column.
    The cleaned
    DataFrame is returned as a column-oriented dict (``df.to_dict("list")``)
    so it can be passed safely through the Celery result backend.

    Parameters
    ----------
    cat_cols : list of str
        Categorical feature column names to include.
    num_cols : list of str
        Numerical feature column names to include.
    target_col : str
        Target column name.  Must not appear in *cat_cols* or *num_cols*.
    file_info : tuple
        ``(file_path, file_name, file_type)``

    Returns
    -------
    dict
        Column-oriented data dict suitable for ``pd.DataFrame.from_dict()``,
        or ``{"Error": str}`` on failure.
    """
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
        if pd.api.types.is_object_dtype(df_filtered[target_col]) or isinstance(df_filtered[target_col].dtype, pd.StringDtype):
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
    """Compute Pearson correlation between each feature and the target column.

    Accepts the column-oriented dict produced by :func:`data_cleaning`,
    reconstructs a DataFrame, and calculates the Pearson correlation
    coefficient for every numeric feature against *target_col*.  Columns
    with zero standard deviation or insufficient data are skipped silently.

    Parameters
    ----------
    df_json : dict
        Column-oriented data dict (output of ``data_cleaning``).
    target_col : str
        Name of the target column.

    Returns
    -------
    dict
        ``{feature_name: float}`` mapping feature names to their Pearson
        correlation with the target, or ``{"Error": str}`` on failure.
    """
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
    """Render a bar chart of feature–target Pearson correlations.

    Takes the ``{feature: correlation}`` dict produced by
    :func:`pearson_correlation` and returns a base64-encoded PNG bar chart
    suitable for embedding directly in JSON responses or HTML.

    Parameters
    ----------
    correlations : dict
        ``{feature_name: float}`` mapping produced by :func:`pearson_correlation`.
    target_col : str
        Target column name (used as the chart title).

    Returns
    -------
    str
        Base64-encoded PNG image, or ``None`` on error.
    """
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
