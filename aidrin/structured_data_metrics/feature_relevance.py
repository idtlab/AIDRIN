import base64
import io
import logging

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sklearn.preprocessing import LabelEncoder

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)


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
        logger.info("Data cleaning task started: %d cat cols, %d num cols, target=%r", len(cat_cols), len(num_cols), target_col)

        try:
            df = read_file(file_info)
            logger.info("File read successfully: shape=%s", df.shape)
        except Exception as e:
            logger.error("Error reading file: %s", e)
            return {
                "Error": "Failed to read the file. Please check the file path and type."
            }

        # Filter DataFrame to include only the specified columns
        selected_columns = [target_col] + cat_cols + num_cols
        logger.debug("Selected columns: %s", selected_columns)

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
        logger.debug("Filtered DataFrame shape: %s", df_filtered.shape)

        # Fill missing values more robustly
        if cat_cols:  # Only process if there are categorical columns
            for col in cat_cols:
                logger.debug("Imputing missing values in categorical column %r", col)
                try:
                    df_filtered[col] = df_filtered[col].fillna("Missing")
                except Exception as e:
                    logger.warning("Error filling missing values in categorical column %r: %s", col, e)
                    # Fallback: replace NaN with a default value
                    df_filtered[col] = df_filtered[col].astype(str).replace('nan', 'Missing')
        else:
            logger.debug("No categorical columns to impute")

        if num_cols:  # Only process if there are numerical columns
            for col in num_cols:
                col_mean = df_filtered[col].mean()
                if pd.isna(col_mean):
                    col_mean = 0.0
                logger.debug("Imputing missing values in numerical column %r with mean=%.4f", col, col_mean)
                try:
                    df_filtered[col] = df_filtered[col].fillna(col_mean)
                except Exception as e:
                    logger.warning("Error filling missing values in numerical column %r: %s", col, e)
                    # Fallback: replace NaN with 0
                    df_filtered[col] = df_filtered[col].fillna(0.0)
        else:
            logger.debug("No numerical columns to impute")

        # One-hot encode categorical columns only if they exist
        if cat_cols:
            logger.debug("Starting one-hot encoding for %d categorical columns", len(cat_cols))
            try:
                df_filtered = pd.get_dummies(df_filtered, columns=cat_cols)
                logger.debug("One-hot encoding completed: DataFrame now has %d columns", df_filtered.shape[1])
            except Exception as e:
                logger.error("Error during one-hot encoding: %s", e)
                return {"Error": f"One-hot encoding failed: {str(e)}"}
        else:
            logger.debug("No categorical columns to one-hot encode")

        # Encode target variable if categorical
        if pd.api.types.is_object_dtype(df_filtered[target_col]) or isinstance(df_filtered[target_col].dtype, pd.StringDtype):
            logger.debug("Encoding categorical target column %r", target_col)
            try:
                le_target = LabelEncoder()
                df_filtered[target_col] = le_target.fit_transform(df_filtered[target_col])
                logger.debug("Target column %r encoded successfully", target_col)
            except Exception as e:
                logger.error("Error encoding target column: %s", e)
                return {"Error": f"Target column encoding failed: {str(e)}"}

        # Convert to JSON more safely
        try:
            result = df_filtered.to_dict(orient="list")
            logger.info("Data cleaning task completed: final shape=%s", df_filtered.shape)
            return result
        except Exception as e:
            logger.error("Error converting to dict: %s", e)
            return {"Error": f"JSON conversion failed: {str(e)}"}

    except SoftTimeLimitExceeded:
        logger.error("Data cleaning task timed out")
        raise Exception("Data Cleaning task timed out.")
    except Exception as e:
        logger.error("Error occurred during data cleaning: %s", e)
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
        logger.info("Pearson correlation task started: target=%r", target_col)

        # Convert JSON back to DataFrame with proper error handling
        try:
            df = pd.DataFrame.from_dict(df_json)
            logger.info("DataFrame reconstructed: shape=%s", df.shape)
        except Exception as e:
            logger.error("Error converting dict to DataFrame: %s", e)
            return {"Error": f"Failed to convert data: {str(e)}"}

        # Ensure target column exists
        if target_col not in df.columns:
            logger.error("Target column %r not found. Available: %s", target_col, list(df.columns))
            return {"Error": f"Target column '{target_col}' not found in the data"}

        # Get columns excluding target column
        cols = df.columns.difference([target_col])
        if len(cols) == 0:
            return {"Error": "No feature columns found for correlation analysis"}

        logger.info("Computing Pearson correlation for %d feature columns", len(cols))

        correlations = {}
        skipped = 0
        for col in cols:
            if col != target_col:
                try:
                    # Ensure both columns are numeric
                    if not pd.api.types.is_numeric_dtype(df[col]) or not pd.api.types.is_numeric_dtype(df[target_col]):
                        logger.debug("Skipping column %r — non-numeric dtype", col)
                        skipped += 1
                        continue

                    # Remove any NaN values for this specific column pair
                    valid_data = df[[col, target_col]].dropna()
                    if len(valid_data) < 2:
                        logger.debug("Skipping column %r — insufficient valid data (%d rows)", col, len(valid_data))
                        skipped += 1
                        continue

                    # Calculate covariance
                    cov = np.cov(valid_data[col], valid_data[target_col], ddof=0)[0, 1]
                    # Calculate standard deviations
                    std_dev_col = np.std(valid_data[col], ddof=0)
                    std_dev_target = np.std(valid_data[target_col], ddof=0)

                    # Check for division by zero
                    if std_dev_col == 0 or std_dev_target == 0:
                        logger.debug("Skipping column %r — zero standard deviation", col)
                        skipped += 1
                        continue

                    # Calculate Pearson correlation coefficient
                    corr = cov / (std_dev_col * std_dev_target)

                    # Ensure correlation is a valid number
                    if np.isfinite(corr):
                        correlations[col] = float(corr)
                    else:
                        logger.debug("Skipping column %r — invalid correlation value: %s", col, corr)
                        skipped += 1

                except Exception as e:
                    logger.warning("Error calculating correlation for column %r: %s", col, e)
                    skipped += 1
                    continue

        if not correlations:
            logger.error("No valid correlations could be calculated for target=%r (%d features skipped)", target_col, skipped)
            return {"Error": "No valid correlations could be calculated"}

        logger.info("Pearson correlation task completed: %d features computed, %d skipped", len(correlations), skipped)
        return correlations

    except SoftTimeLimitExceeded:
        logger.error("Pearson correlation task timed out")
        raise Exception("Pearson Correlation task timed out.")
    except Exception as e:
        logger.error("Unexpected error in pearson_correlation: %s", e)
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
        logger.info("Plot features task started: %d features, target=%r", len(correlations), target_col)

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

        logger.info("Plot features task completed: %d features visualized", len(clean_features))
        return image_base64

    except SoftTimeLimitExceeded:
        logger.error("Plot features task timed out")
        raise Exception("Plot Features task timed out.")
    except Exception as e:
        logger.error("Error occurred during plotting: %s", e)
        return None
