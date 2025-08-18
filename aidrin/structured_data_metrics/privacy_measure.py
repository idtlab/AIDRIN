import base64
import io
import logging
from typing import List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)


def generate_single_attribute_MM_risk_scores(df, id_col, eval_cols, task=None):
    result_dict = {}

    try:
        # Stage 1: Data validation & preprocessing (0-15%)
        if task:
            task.update_state(
                state='PROGRESS',
                meta={'current': 5, 'total': 100, 'status': 'Data validation & preprocessing...'}
            )

        # Check if the DataFrame is empty
        if df.empty:
            raise ValueError("Dataset is empty. Please upload a dataset with data.")

        # Handle eval_cols - it might be a string or list
        if isinstance(eval_cols, str):
            # If it's a string, split by comma and clean up
            eval_cols = [col.strip() for col in eval_cols.split(",") if col.strip()]
        elif isinstance(eval_cols, list):
            # If it's already a list, clean up each item
            eval_cols = [col.strip() for col in eval_cols if col.strip()]
        else:
            raise ValueError("Quasi-identifiers must be provided as a string or list.")

        # Check if eval_cols is empty after processing
        if not eval_cols:
            raise ValueError("No valid quasi-identifiers provided.")

        # Validate that all columns exist in the dataframe
        missing_cols = [col for col in eval_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Quasi-identifier columns not found in dataset: {', '.join(missing_cols)}")

        # Validate id_col
        if not id_col or id_col not in df.columns:
            raise ValueError(f"ID column '{id_col}' not found in dataset.")

        # Check if ID column has unique values
        if df[id_col].nunique() != len(df):
            raise ValueError(f"ID column '{id_col}' must contain unique values for each row.")

        # Select the specified columns from the DataFrame
        selected_columns = [id_col] + eval_cols
        selected_df = df[selected_columns]

        # Check data types - ensure quasi-identifiers are categorical or string
        non_categorical_cols = []
        for col in eval_cols:
            if df[col].dtype in ['int64', 'float64'] and df[col].nunique() > 100:
                non_categorical_cols.append(col)
        
        if non_categorical_cols:
            raise ValueError(f"Columns {', '.join(non_categorical_cols)} appear to be numerical with too many unique values. Quasi-identifiers should be categorical.")

        # Drop rows with missing values
        initial_rows = len(selected_df)
        selected_df = selected_df.dropna()
        rows_after_dropna = len(selected_df)
        print(rows_after_dropna)
        if rows_after_dropna == 0:
            raise ValueError("After removing missing values, no data remains. Please check your data quality or select different columns.")
        
        #if rows_after_dropna < initial_rows * 0.5:
        #    raise ValueError(f"More than 50% of data was removed due to missing values ({initial_rows - rows_after_dropna}/{initial_rows} rows). Please check data quality.")

        # Convert the selected DataFrame to a NumPy array
        my_array = selected_df.to_numpy()

        # Stage 2: Calculate risk scores for each column (15-70%)
        if task:
            task.update_state(
                state='PROGRESS',
                meta={'current': 15, 'total': 100, 'status': 'Calculating risk scores...'}
            )

        sing_res = {}
        total_columns = len(eval_cols)

        for col_idx, col in enumerate(eval_cols):
            if task:
                # Progress from 15% to 70% based on column completion
                progress = 15 + (col_idx / total_columns) * 55
                task.update_state(
                    state='PROGRESS',
                    meta={'current': int(progress), 'total': 100, 'status': f'Calculating risk scores for {col}... ({col_idx + 1}/{total_columns})'}
                )

            risk_scores = np.zeros(len(my_array))
            
            # Check if column has sufficient variation
            unique_values = np.unique(my_array[:, col_idx + 1])
            if len(unique_values) == 1:
                raise ValueError(f"Column '{col}' has only one unique value, making risk assessment meaningless.")
            
            

            for j in range(len(my_array)):
                attr1_tot = np.count_nonzero(my_array[:, col_idx + 1] == my_array[j, col_idx + 1])

                mask_attr1_user = (my_array[:, 0] == my_array[j, 0]) & (my_array[:, col_idx + 1] == my_array[j, col_idx + 1])
                count_attr1_user = np.count_nonzero(mask_attr1_user)

                # Prevent division by zero
                if attr1_tot == 0:
                    raise ValueError(f"Column '{col}' has unexpected data structure causing division by zero.")

                start_prob_attr1 = attr1_tot / len(my_array)
                obs_prob_attr1 = 1 - (count_attr1_user / attr1_tot)

                priv_prob_MM = start_prob_attr1 * obs_prob_attr1
                worst_case_MM_risk_score = round(1 - priv_prob_MM, 2)
                risk_scores[j] = worst_case_MM_risk_score

            sing_res[col] = risk_scores

        # Stage 3: Calculate descriptive statistics (70-85%)
        if task:
            task.update_state(
                state='PROGRESS',
                meta={'current': 75, 'total': 100, 'status': 'Calculating descriptive statistics...'}
            )

        # Calculate descriptive statistics for risk scores
        descriptive_stats_dict = {}
        for key, value in sing_res.items():
            stats_dict = {
                "mean": np.mean(value),
                "std": np.std(value),
                "min": np.min(value),
                "25%": np.percentile(value, 25),
                "50%": np.median(value),
                "75%": np.percentile(value, 75),
                "max": np.max(value),
            }
            descriptive_stats_dict[key] = stats_dict

        # Stage 4: Generate visualization (85-100%)
        if task:
            task.update_state(
                state='PROGRESS',
                meta={'current': 90, 'total': 100, 'status': 'Generating visualization...'}
            )

        # Create a box plot
        plt.figure(figsize=(8, 8))
        plt.boxplot(list(sing_res.values()), labels=sing_res.keys())
        plt.title("Box plot of single feature risk scores")
        plt.xlabel("Feature")
        plt.ylabel("Risk Score")

        # Save the plot as a PNG image in memory
        image_stream = io.BytesIO()
        plt.tight_layout()
        plt.savefig(image_stream, format="png", bbox_inches='tight', dpi=300)
        plt.close()

        # Convert the image to a base64 string
        image_stream.seek(0)
        base64_image = base64.b64encode(image_stream.read()).decode("utf-8")
        image_stream.close()

        result_dict["Descriptive statistics of the risk scores"] = descriptive_stats_dict
        result_dict["Single attribute risk scoring Visualization"] = base64_image
        result_dict["Description"] = (
            "This metric quantifies the re-identification risk for each "
            "quasi-identifier. Lower values are preferred, indicating "
            "features that are less likely to uniquely identify individuals. "
            "High-risk features may require further anonymization or removal."
        )
        result_dict["Graph interpretation"] = (
            "The box plot displays the distribution of risk scores for each feature. Features with "
            "higher medians or more outliers indicate greater privacy risk. A compact, lower box is desirable."
        )

    except SoftTimeLimitExceeded:
        raise Exception("Single Attribute Risk task timed out. The dataset may be too large or complex.")
    except ValueError as ve:
        # Handle specific validation errors
        result_dict["Error"] = str(ve)
        result_dict["Single attribute risk scoring Visualization"] = ""
        result_dict["Description"] = f"Validation Error: {str(ve)}"
        result_dict["Graph interpretation"] = "No visualization available due to validation error."
        result_dict["ErrorType"] = "Validation Error"
    except Exception as e:
        # Handle other unexpected errors
        result_dict["Error"] = f"Processing error: {str(e)}"
        result_dict["Single attribute risk scoring Visualization"] = ""
        result_dict["Description"] = f"Processing Error: {str(e)}"
        result_dict["Graph interpretation"] = "No visualization available due to processing error."
        result_dict["ErrorType"] = "Processing Error"

    return result_dict


def generate_multiple_attribute_MM_risk_scores(df, id_col, eval_cols, task=None):
    result_dict = {}

    try:
        # Stage 1: Data validation & preprocessing (5%)
        if task:
            task.update_state(
                state='PROGRESS',
                meta={'current': 5, 'total': 100, 'status': 'Data validation & preprocessing...'}
            )

        # Check if DataFrame is empty
        if df.empty:
            raise ValueError("Input DataFrame is empty.")

        # Handle eval_cols - it might be a string or list
        if isinstance(eval_cols, str):
            eval_cols = [col.strip() for col in eval_cols.split(',') if col.strip()]
        elif isinstance(eval_cols, list):
            eval_cols = [col.strip() for col in eval_cols if col.strip()]
        else:
            raise ValueError("eval_cols must be a string or list")

        # Check if eval_cols is empty after processing
        if not eval_cols:
            raise ValueError("No valid columns provided in eval_cols after processing")

        # Validate that all columns exist in the dataframe
        missing_cols = [col for col in eval_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Columns not found in dataset: {missing_cols}")

        # Validate id_col
        if not id_col or id_col not in df.columns:
            raise ValueError(f"ID column '{id_col}' not found in dataset")
        
        selected_columns = [id_col] + eval_cols
        selected_df = df[selected_columns]
        selected_df = selected_df.dropna()

        # Check if DataFrame is still non-empty after dropping missing values
        rows_after_dropna = len(selected_df)
        

        if rows_after_dropna == 0:
            print("DEBUG: About to raise ValueError - no data remains after dropna")
            raise ValueError("After removing missing values, no data remains. Please check your data quality or select different columns.")

        # Check data quality for quasi-identifiers
        for col in eval_cols:
            if col in df.columns:
                unique_values = df[col].nunique()
                if unique_values == 1:
                    raise ValueError(f"Column '{col}' has only one unique value, making risk assessment meaningless.")
                
        # Check if ID column has unique values
        if df[id_col].nunique() != len(df):
            raise ValueError(f"ID column '{id_col}' must contain unique values for each row.")

        # Select specified columns from DataFrame
        
        # convert dataframe to numpy array
        my_array = selected_df.to_numpy()

        # Stage 2: Calculate risk scores for all rows (15-70%)
        if task:
            task.update_state(
                state='PROGRESS',
                meta={'current': 15, 'total': 100, 'status': 'Starting risk score calculations...'}
            )

        # array to store risk scores of each data point
        risk_scores = np.zeros(len(my_array))
        total_rows = len(my_array)

        # risk scoring
        for j in range(len(my_array)):
            if len(my_array[0]) > 2:
                priv_prob_MM = 1

                for i in range(2, len(my_array[0])):
                    attr1_tot = np.count_nonzero(
                        my_array[:, i - 1] == my_array[j][i - 1]
                    )

                    if attr1_tot == 0:
                        raise ValueError(f"Column '{eval_cols[i-2] if i-2 < len(eval_cols) else 'unknown'}' has unexpected data structure causing division by zero.")

                    mask_attr1_user = (my_array[:, 0] == my_array[j][0]) & (my_array[:, i-1] == my_array[j][i-1])
                    count_attr1_user = np.count_nonzero(mask_attr1_user)

                    start_prob_attr1 = attr1_tot / len(my_array)  # 1

                    obs_prob_attr1 = 1 - (count_attr1_user / attr1_tot)  # 2

                    mask_attr1_attr2 = (my_array[:, i-1] == my_array[j][i-1])
                    count_attr1_attr2 = np.count_nonzero(mask_attr1_attr2)

                    mask2_attr1_attr2 = (my_array[:, i-1] == my_array[j][i-1]) & (my_array[:, i] == my_array[j][i])
                    count2_attr1_attr2 = np.count_nonzero(mask2_attr1_attr2)

                    trans_prob_attr1_attr2 = count2_attr1_attr2 / count_attr1_attr2  # 3

                    attr2_tot = np.count_nonzero(my_array[:, i] == my_array[j][i])

                    if attr2_tot == 0:
                        raise ValueError(f"Column '{eval_cols[i-1] if i-1 < len(eval_cols) else 'unknown'}' has unexpected data structure causing division by zero.")

                    mask_attr2_user = (my_array[:, 0] == my_array[j][0]) & (my_array[:, i] == my_array[j][i])
                    count_attr2_user = np.count_nonzero(mask_attr2_user)

                    obs_prob_attr2 = 1 - (count_attr2_user / attr2_tot)  # 4

                    priv_prob_MM = priv_prob_MM * start_prob_attr1 * obs_prob_attr1 * trans_prob_attr1_attr2 * obs_prob_attr2
                    worst_case_MM_risk_score = round(1 - priv_prob_MM, 2)  # 5
                risk_scores[j] = worst_case_MM_risk_score
            elif len(my_array[0]) == 2:
                priv_prob_MM = 1
                attr1_tot = np.count_nonzero(my_array[:, 1] == my_array[j][1])

                if attr1_tot == 0:
                    raise ValueError(f"Column '{eval_cols[0] if eval_cols else 'unknown'}' has unexpected data structure causing division by zero.")

                mask_attr1_user = (my_array[:, 0] == my_array[j][0]) & (my_array[:, 1] == my_array[j][1])
                count_attr1_user = np.count_nonzero(mask_attr1_user)

                start_prob_attr1 = attr1_tot / len(my_array)  # 1

                obs_prob_attr1 = 1 - (count_attr1_user / attr1_tot)  # 2

                priv_prob_MM = priv_prob_MM * start_prob_attr1 * obs_prob_attr1
                worst_case_MM_risk_score = round(1 - priv_prob_MM, 2)  # 5
                risk_scores[j] = worst_case_MM_risk_score

        # Stage 3: Calculate dataset privacy level (70-80%)
        if task:
            task.update_state(
                state='PROGRESS',
                meta={'current': 75, 'total': 100, 'status': 'Calculating dataset privacy level...'}
            )

        # calculate the entire dataset privacy level
        min_risk_scores = np.zeros(len(risk_scores))
        # Calculate the Euclidean distance
        euclidean_distance = np.linalg.norm(risk_scores - min_risk_scores)

        max_risk_scores = np.ones(len(risk_scores))

        # max euclidean distance
        max_euclidean_distance = np.linalg.norm(max_risk_scores - min_risk_scores)
        normalized_distance = euclidean_distance / max_euclidean_distance

        # Stage 4: Calculate descriptive statistics (80-90%)
        if task:
            task.update_state(
                state='PROGRESS',
                meta={'current': 85, 'total': 100, 'status': 'Calculating descriptive statistics...'}
            )

        # descriptive statistics
        stats_dict = {
            'mean': np.mean(risk_scores),
            'std': np.std(risk_scores),
            'min': np.min(risk_scores),
            '25%': np.percentile(risk_scores, 25),
            '50%': np.median(risk_scores),
            '75%': np.percentile(risk_scores, 75),
            'max': np.max(risk_scores)
        }

        # Stage 5: Generate visualization (90-100%)
        if task:
            task.update_state(
                state='PROGRESS',
                meta={'current': 95, 'total': 100, 'status': 'Generating visualization...'}
            )

        x_label = ",".join(eval_cols)
        # Create a box plot
        plt.figure(figsize=(8, 8))
        plt.boxplot(risk_scores, vert=True)  # vert=False for horizontal box plot
        plt.title('Box Plot of Multiple Attribute Risk Scores')
        plt.ylabel('Risk Score')
        plt.xlabel('Feature Combination')
        plt.xticks([1], [x_label])

        # Save the plot as a PNG image in memory
        image_stream = io.BytesIO()
        plt.tight_layout()
        plt.savefig(image_stream, format='png', bbox_inches='tight', dpi=300)
        plt.close()

        # Convert the image to a base64 string
        image_stream.seek(0)
        base64_image = base64.b64encode(image_stream.read()).decode('utf-8')
        image_stream.close()

        result_dict["Description"] = (
            "This metric evaluates the joint risk posed by combinations of "
            "quasi-identifiers. Lower values are preferred, as they indicate "
            "that the selected set of features does not easily allow "
            "re-identification."
        )
        result_dict["Graph interpretation"] = (
            "The box plot shows the distribution of combined risk scores. A distribution concentrated at lower values indicates better privacy."
        )
        result_dict["Descriptive statistics of the risk scores"] = stats_dict
        result_dict["Multiple attribute risk scoring Visualization"] = base64_image
        result_dict['Dataset Risk Score'] = normalized_distance

    except SoftTimeLimitExceeded:
        raise Exception("Multiple Attribute Risk task timed out. The dataset may be too large or complex.")
    except ValueError as ve:
        # Handle specific validation errors 
        result_dict["Error"] = str(ve)
        result_dict["Multiple attribute risk scoring Visualization"] = ""
        result_dict["Description"] = f"Validation Error: {str(ve)}"
        result_dict["Graph interpretation"] = "No visualization available due to validation error."
        result_dict["ErrorType"] = "Validation Error"
    except Exception as e:
        # Handle other unexpected errors
        result_dict["Error"] = f"Processing error: {str(e)}"
        result_dict["Multiple attribute risk scoring Visualization"] = ""
        result_dict["Description"] = f"Processing Error: {str(e)}"
        result_dict["Graph interpretation"] = "No visualization available due to processing error."
        result_dict["ErrorType"] = "Processing Error"

    return result_dict


def compute_k_anonymity(quasi_identifiers: List[str], file_info):
    # Handle both DataFrame and tuple inputs
    if isinstance(file_info, tuple):
        data = read_file(file_info)
    else:
        data = file_info
    result_dict = {}
    try:
        if data.empty:
            raise ValueError("Input DataFrame is empty.")

        for qi in quasi_identifiers:
            if qi not in data.columns:
                raise ValueError(f"Quasi-identifier '{qi}' not found in the dataset.")

        data.replace("?", pd.NA, inplace=True)
        clean_data = data.dropna(subset=quasi_identifiers)
        if clean_data.empty:
            raise ValueError(
                "No data left after dropping rows with missing quasi-identifiers."
            )

        equivalence_classes = (
            clean_data.groupby(quasi_identifiers).size().reset_index(name="count")
        )
        counts = equivalence_classes["count"]

        # Compute k-anonymity
        k_anonymity = int(counts.min())

        # Descriptive statistics
        desc_stats = {
            "min": int(counts.min()),
            "max": int(counts.max()),
            "mean": round(counts.mean(), 2),
            "median": int(counts.median()),
        }

        # Histogram of equivalence class sizes
        hist_data = counts.value_counts().sort_index().to_dict()
        plt.figure(figsize=(8, 5))
        plt.bar(hist_data.keys(), hist_data.values(), color="skyblue")
        plt.xlabel("Equivalence Class Size (k)")
        plt.ylabel("Number of Equivalence Classes")
        plt.title("Distribution of Equivalence Class Sizes")
        plt.grid(axis="y", alpha=0.75)
        # Save histogram to base64
        img_stream = io.BytesIO()
        plt.tight_layout()
        plt.savefig(img_stream, format="png", bbox_inches='tight', dpi=300)
        plt.close()
        img_stream.seek(0)
        base64_image = base64.b64encode(img_stream.read()).decode("utf-8")
        img_stream.close()

        # Final result
        result_dict = {
            "k-Value": k_anonymity,
            "descriptive_statistics": desc_stats,
            "histogram_data": hist_data,
            "k-Anonymity Visualization": base64_image,
            "Description": (
                "k-anonymity measures the minimum group size sharing the same quasi-identifier values. "
                "Higher k values are preferred, as they indicate stronger anonymity."
            ),
            "Graph interpretation": (
                "The histogram shows the distribution of equivalence class sizes. A shift toward larger "
                "class sizes (higher k) is desirable for privacy."
            ),
        }
    except SoftTimeLimitExceeded:
        raise Exception("K anonymity task timed out.")
    except ValueError as ve:
        result_dict["Error"] = str(ve)
        result_dict["k-Anonymity Visualization"] = ""
        result_dict["Graph interpretation"] = "No visualization available due to validation error."
        result_dict["ErrorType"] = "Validation Error"
        return result_dict
    except Exception as e:
        result_dict["Error"] = f"Processing error: {str(e)}"
        result_dict["k-Anonymity Visualization"] = ""
        result_dict["Graph interpretation"] = "No visualization available due to processing error."
        result_dict["ErrorType"] = "Processing Error"
        return result_dict

    return result_dict


def compute_l_diversity(
    quasi_identifiers: list,
    sensitive_column: str,
    file_info,
):
    # Handle both DataFrame and tuple inputs
    if isinstance(file_info, tuple):
        data = read_file(file_info)
    else:
        data = file_info
    result_dict = {}
    try:
        # Validate input DataFrame
        if data.empty:
            raise ValueError("Input DataFrame is empty.")

        # Validate quasi-identifiers
        for qi in quasi_identifiers:
            if qi not in data.columns:
                raise ValueError(f"Quasi-identifier '{qi}' not found in the dataset.")

        # Validate sensitive column presence
        if sensitive_column not in data.columns:
            raise ValueError(
                f"Sensitive column '{sensitive_column}' not found in the dataset."
            )

        data = data.replace("?", pd.NA)

        # Drop rows with missing quasi-identifiers or sensitive values
        clean_data = data.dropna(subset=quasi_identifiers + [sensitive_column])
        if clean_data.empty:
            raise ValueError(
                "No data left after dropping rows with missing quasi-identifiers or sensitive values."
            )

        # Compute l-diversities: count of unique sensitive values per equivalence class
        l_diversities = clean_data.groupby(quasi_identifiers)[
            sensitive_column
        ].nunique()

        # Minimum l-diversity (lowest number of distinct sensitive values)
        min_l_diversity = int(l_diversities.min())

        # Descriptive statistics for l-diversity distribution
        desc_stats = {
            "min": int(l_diversities.min()),
            "max": int(l_diversities.max()),
            "mean": round(l_diversities.mean(), 2),
            "median": int(l_diversities.median()),
        }

        # Histogram plot of l-diversity counts
        # or use: (l_diversities / 2).round() * 2 for bin size of 2
        binned_l_diversities = l_diversities.round()
        hist_data = binned_l_diversities.value_counts().sort_index()
        plt.figure(figsize=(8, 8))
        plt.bar(hist_data.index, hist_data.values, color="skyblue")
        plt.xlabel("Number of Distinct Sensitive Values (l)")
        plt.ylabel("Number of Equivalence Classes")
        plt.title("Distribution of l-Diversity Across Equivalence Classes")
        plt.xticks(sorted(hist_data.index))
        plt.grid(axis="y", alpha=0.75)

        # Save plot to base64 string
        img_stream = io.BytesIO()
        plt.tight_layout()
        plt.savefig(img_stream, format="png", bbox_inches='tight', dpi=300)
        plt.close()
        img_stream.seek(0)
        base64_image = base64.b64encode(img_stream.read()).decode("utf-8")
        img_stream.close()

        # Compose result dictionary
        result_dict = {
            "l-Value": min_l_diversity,
            "descriptive_statistics": desc_stats,
            "histogram_data": hist_data.to_dict(),
            "l-Diversity Visualization": base64_image,
            "Description": (
                "l-diversity quantifies the diversity of sensitive attributes within each group. "
                "Higher l values are preferred, indicating less risk of attribute disclosure."
            ),
            "Graph interpretation": (
                "The histogram displays the spread of l-diversity values. A distribution concentrated at higher l values is optimal."
            ),
        }
    except SoftTimeLimitExceeded:
        raise Exception("L Diversity task timed out.")
    except ValueError as ve:
        result_dict["Error"] = str(ve)
        result_dict["l-Diversity Visualization"] = ""
        result_dict["Graph interpretation"] = "No visualization available due to validation error."
        result_dict["ErrorType"] = "Validation Error"
        return result_dict
    except Exception as e:
        result_dict["Error"] = f"Processing error: {str(e)}"
        result_dict["l-Diversity Visualization"] = ""
        result_dict["Graph interpretation"] = "No visualization available due to processing error."
        result_dict["ErrorType"] = "Processing Error"
        return result_dict

    return result_dict


def compute_t_closeness(
    quasi_identifiers: List[str],
    sensitive_column: str,
    file_info,
):
    # Handle both DataFrame and tuple inputs
    if isinstance(file_info, tuple):
        data = read_file(file_info)
    else:
        data = file_info
    result_dict = {}
    try:
        # TVD computation
        def tvd(p, q):
            all_keys = set(p.index).union(set(q.index))
            p_full = p.reindex(all_keys, fill_value=0)
            q_full = q.reindex(all_keys, fill_value=0)
            return 0.5 * np.abs(p_full - q_full).sum()

        if data.empty:
            raise ValueError("Input DataFrame is empty.")

        for qi in quasi_identifiers:
            if qi not in data.columns:
                raise ValueError(f"Quasi-identifier '{qi}' not found in the dataset.")

        if sensitive_column not in data.columns:
            raise ValueError(
                f"Sensitive column '{sensitive_column}' not found in the dataset."
            )

        data = data.replace("?", pd.NA)
        clean_data = data.dropna(subset=quasi_identifiers + [sensitive_column])
        if clean_data.empty:
            raise ValueError("No data left after dropping rows with missing values.")

        # Global distribution of sensitive column
        global_dist = clean_data[sensitive_column].value_counts(normalize=True)

        # Compute t-closeness per equivalence class
        t_values = {}
        for keys, group in clean_data.groupby(quasi_identifiers):
            group_dist = group[sensitive_column].value_counts(normalize=True)
            t_values[keys] = tvd(group_dist, global_dist)

        t_series = pd.Series(t_values)
        max_t = round(t_series.max(), 4)

        # Descriptive stats
        desc_stats = {
            "min": round(t_series.min(), 4),
            "max": max_t,
            "mean": round(t_series.mean(), 4),
            "median": round(t_series.median(), 4),
        }

        # Histogram plot
        hist_data = t_series.round(2).value_counts().sort_index()
        plt.figure(figsize=(8, 5))
        plt.bar(hist_data.index, hist_data.values, color="salmon")
        plt.xlabel("t-Closeness Value (TVD)")
        plt.ylabel("Number of Equivalence Classes")
        plt.title("Distribution of T-Closeness Across Equivalence Classes")
        plt.grid(axis="y", alpha=0.75)

        img_stream = io.BytesIO()
        plt.tight_layout()
        plt.savefig(img_stream, format="png", bbox_inches='tight', dpi=300)
        plt.close()
        img_stream.seek(0)
        base64_image = base64.b64encode(img_stream.read()).decode("utf-8")
        img_stream.close()

        result_dict = {
            "t-Value": max_t,
            "descriptive_statistics": desc_stats,
            "histogram_data": hist_data.to_dict(),
            "t-Closeness Visualization": base64_image,
            "Description": (
                "t-closeness measures the distance between the distribution of sensitive attributes "
                "in a group and the overall distribution. Lower t values are preferred, indicating less information leakage."
            ),
            "Graph interpretation": (
                "The histogram shows the distribution of t values. Lower t values across groups indicate stronger privacy."
            ),
        }
    except SoftTimeLimitExceeded:
        raise Exception("T Closeness task timed out.")
    except ValueError as ve:
        result_dict["Error"] = str(ve)
        result_dict["t-Closeness Visualization"] = ""
        result_dict["Graph interpretation"] = "No visualization available due to validation error."
        result_dict["ErrorType"] = "Validation Error"
        return result_dict
    except Exception as e:
        result_dict["Error"] = f"Processing error: {str(e)}"
        result_dict["t-Closeness Visualization"] = ""
        result_dict["Graph interpretation"] = "No visualization available due to processing error."
        result_dict["ErrorType"] = "Processing Error"
        return result_dict

    return result_dict


def compute_entropy_risk(quasi_identifiers, file_info):
    # Handle both DataFrame and tuple inputs
    if isinstance(file_info, tuple):
        data = read_file(file_info)
    else:
        data = file_info
    result_dict = {}

    try:
        if data.empty:
            raise ValueError("Input DataFrame is empty.")

        for qi in quasi_identifiers:
            if qi not in data.columns:
                raise ValueError(f"Quasi-identifier '{qi}' not found in the dataset.")

        data = data.replace("?", pd.NA)
        clean_data = data.dropna(subset=quasi_identifiers)

        if clean_data.empty:
            raise ValueError("No data left after dropping rows with missing values.")

        total_records = len(clean_data)
        grouped = clean_data.groupby(quasi_identifiers)

        entropy_values = {}
        for keys, group in grouped:
            size = len(group)
            p_i = 1 / size
            entropy = -size * p_i * np.log2(p_i)
            entropy_values[keys] = entropy

        entropy_series = pd.Series(entropy_values)
        avg_entropy = entropy_series.sum() / total_records if total_records > 0 else 0.0
        rounded_entropy = round(avg_entropy, 4)

        # Histogram plot of entropy values
        hist_data = entropy_series.round(2).value_counts().sort_index()
        plt.figure(figsize=(8, 5))
        plt.bar(hist_data.index, hist_data.values, color="royalblue")
        plt.xlabel("Entropy Value")
        plt.ylabel("Number of Equivalence Classes")
        plt.title("Distribution of Entropy Across Equivalence Classes")
        plt.grid(axis="y", alpha=0.75)

        img_stream = io.BytesIO()
        plt.tight_layout()
        plt.savefig(img_stream, format="png", bbox_inches='tight', dpi=300)
        plt.close()
        img_stream.seek(0)
        base64_image = base64.b64encode(img_stream.read()).decode("utf-8")
        img_stream.close()

        desc_stats = {
            "min": round(entropy_series.min(), 4),
            "max": round(entropy_series.max(), 4),
            "mean": round(entropy_series.mean(), 4),
            "median": round(entropy_series.median(), 4),
        }

        result_dict = {
            "Entropy-Value": rounded_entropy,
            "descriptive_statistics": desc_stats,
            "histogram_data": hist_data.to_dict(),
            "Entropy Risk Visualization": base64_image,
            "Description": (
                "Entropy risk quantifies the uncertainty in identifying individuals within equivalence classes. "
                "Higher entropy values are preferred, indicating greater anonymity and lower re-identification risk."
            ),
            "Graph interpretation": (
                "The bar chart visualizes the distribution of entropy values. Higher bars on the right (higher entropy) "
                "indicate better privacy; left-skewed distributions suggest higher risk."
            ),
        }
    except SoftTimeLimitExceeded:
        raise Exception("Entropy Risk task timed out.")
    except ValueError as ve:
        result_dict["Error"] = str(ve)
        result_dict["Entropy Risk Visualization"] = ""
        result_dict["Graph interpretation"] = "No visualization available due to validation error."
        result_dict["ErrorType"] = "Validation Error"
        return result_dict
    except Exception as e:
        result_dict["Error"] = f"Processing error: {str(e)}"
        result_dict["Entropy Risk Visualization"] = ""
        result_dict["Graph interpretation"] = "No visualization available due to processing error."
        result_dict["ErrorType"] = "Processing Error"
        return result_dict

    return result_dict


# Celery tasks for async processing
try:

    @shared_task(bind=True, time_limit=1200, soft_time_limit=900)
    def calculate_single_attribute_risk_score(self, df_data, id_col, eval_cols):
        """
        Celery task for calculating single attribute MM risk scores.
        """
        try:
            # Update task state
            self.update_state(
                state='PROGRESS',
                meta={'current': 0, 'total': 100, 'status': 'Starting single attribute risk calculation...'}
            )

            # Convert DataFrame from JSON back to pandas DataFrame
            df = pd.read_json(df_data)

            # Update progress
            self.update_state(
                state='PROGRESS',
                meta={'current': 15, 'total': 100, 'status': 'Data loaded, calculating risk scores...'}
            )

            # Calculate risk scores using existing function
            result = generate_single_attribute_MM_risk_scores(df, id_col, eval_cols, self)

            # Update progress
            self.update_state(
                state='PROGRESS',
                meta={'current': 75, 'total': 100, 'status': 'Risk scores calculated, finalizing...'}
            )

            # Return the actual result (don't update state to SUCCESS as it overwrites the result)
            return result

        except Exception as e:
            logger.error(f"Error in single attribute risk calculation: {str(e)}")
            # Return error result instead of raising exception
            error_result = {
                "Error": str(e),
                "Single attribute risk scoring Visualization": "",
                "Graph interpretation": "No visualization available due to processing error.",
                "ErrorType": "Processing Error"
            }
            return error_result

    @shared_task(bind=True, time_limit=1200, soft_time_limit=900)
    def calculate_multiple_attribute_risk_score(self, df_data, id_col, eval_cols):
        """
        Celery task for calculating multiple attribute MM risk scores.
        """
        try:
            # Update task state
            self.update_state(
                state='PROGRESS',
                meta={'current': 0, 'total': 100, 'status': 'Starting multiple attribute risk calculation...'}
            )

            # Convert DataFrame from JSON back to pandas DataFrame
            df = pd.read_json(df_data)

            # Update progress
            self.update_state(
                state='PROGRESS',
                meta={'current': 25, 'total': 100, 'status': 'Data loaded, calculating risk scores...'}
            )

            # Calculate risk scores using existing function
            result = generate_multiple_attribute_MM_risk_scores(df, id_col, eval_cols, self)

            # Update progress
            self.update_state(
                state='PROGRESS',
                meta={'current': 75, 'total': 100, 'status': 'Risk scores calculated, finalizing...'}
            )

            # Return the actual result (don't update state to SUCCESS as it overwrites the result)
            return result

        except Exception as e:
            logger.error(f"Error in multiple attribute risk calculation: {str(e)}")
            # Return error result instead of raising exception
            error_result = {
                "Error": str(e),
                "Multiple attribute risk scoring Visualization": "",
                "Graph interpretation": "No visualization available due to processing error.",
                "ErrorType": "Processing Error"
            }
            return error_result

except ImportError:
    # Fallback for when running outside of the Flask app context
    pass
