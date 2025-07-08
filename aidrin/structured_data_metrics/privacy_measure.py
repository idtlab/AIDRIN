import numpy as np
import matplotlib.pyplot as plt
import io
import base64
from celery import shared_task, Task
from celery.exceptions import SoftTimeLimitExceeded
from aidrin.file_handling.file_parser import read_file
import pandas as pd
from typing import List


@shared_task(bind=True, ignore_result=False)
def generate_single_attribute_MM_risk_scores(self: Task, id_col, eval_cols, file_info):
    df = read_file(file_info)
    result_dict = {}

    try:
        # Check if the DataFrame is empty
        if df.empty:
            raise ValueError("Input DataFrame is empty.")

        # Handle eval_cols - it might be a string or list
        if isinstance(eval_cols, str):
            # If it's a string, split by comma and clean up
            eval_cols = [col.strip()
                         for col in eval_cols.split(',') if col.strip()]
        elif isinstance(eval_cols, list):
            # If it's already a list, clean up each item
            eval_cols = [col.strip() for col in eval_cols if col.strip()]
        else:
            raise ValueError("eval_cols must be a string or list")

        # Validate that all columns exist in the dataframe
        missing_cols = [col for col in eval_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Columns not found in dataset: {missing_cols}")

        # Check if the DataFrame is still non-empty after dropping missing values
        if df.empty:
            raise ValueError(
                "After dropping missing values, the DataFrame is empty.")

        # Select the specified columns from the DataFrame
        selected_columns = [id_col] + eval_cols
        selected_df = df[selected_columns]

        # Drop rows with missing values
        selected_df = selected_df.dropna()

        # Convert the selected DataFrame to a NumPy array
        my_array = selected_df.to_numpy()

        # Single attribute risk scoring
        sing_res = {}
        for i, col in enumerate(eval_cols):
            risk_scores = np.zeros(len(my_array))
            for j in range(len(my_array)):
                attr1_tot = np.count_nonzero(
                    my_array[:, i + 1] == my_array[j, i + 1])

                mask_attr1_user = (my_array[:, 0] == my_array[j, 0]) & (
                    my_array[:, i + 1] == my_array[j, i + 1])
                count_attr1_user = np.count_nonzero(mask_attr1_user)

                start_prob_attr1 = attr1_tot / len(my_array)
                obs_prob_attr1 = 1 - (count_attr1_user / attr1_tot)

                priv_prob_MM = start_prob_attr1 * obs_prob_attr1
                worst_case_MM_risk_score = round(1 - priv_prob_MM, 2)
                risk_scores[j] = worst_case_MM_risk_score

            sing_res[col] = risk_scores

        # Calculate descriptive statistics for risk scores
        descriptive_stats_dict = {}
        for key, value in sing_res.items():
            stats_dict = {
                'mean': np.mean(value),
                'std': np.std(value),
                'min': np.min(value),
                '25%': np.percentile(value, 25),
                '50%': np.median(value),
                '75%': np.percentile(value, 75),
                'max': np.max(value)
            }
            descriptive_stats_dict[key] = stats_dict

        # Create a box plot
        plt.figure(figsize=(8, 8))
        plt.boxplot(list(sing_res.values()), labels=sing_res.keys())
        plt.title('Box plot of single feature risk scores')
        plt.xlabel('Feature')
        plt.ylabel('Risk Score')

        # Save the plot as a PNG image in memory
        image_stream = io.BytesIO()
        plt.savefig(image_stream, format='png')
        plt.close()

        # Convert the image to a base64 string
        image_stream.seek(0)
        base64_image = base64.b64encode(image_stream.read()).decode('utf-8')
        image_stream.close()

        result_dict["DescriptiveStatistics"] = descriptive_stats_dict
        result_dict['Single attribute risk scoring Visualization'] = base64_image
        result_dict["Description"] = (
            "This metric quantifies the re-identification risk for each quasi-identifier. Lower risk scores are preferred, indicating features that are less likely to uniquely identify individuals. High-risk features may require further anonymization or removal."
        )
        result_dict["Graph interpretation"] = (
            "The box plot displays the distribution of risk scores for each feature. Features with higher medians or more outliers indicate greater privacy risk. A compact, lower box is desirable."
        )

    except SoftTimeLimitExceeded:
        raise Exception("Single Attribute Risk task timed out.")
    except Exception as e:
        result_dict["Error"] = str(e)
        # Ensure the visualization key is always present for frontend compatibility
        result_dict['Single attribute risk scoring Visualization'] = ""
        result_dict["Description"] = f"Error occurred: {str(e)}"
        result_dict["Graph interpretation"] = "No visualization available due to error."

    return result_dict


@shared_task(bind=True, ignore_result=False)
def generate_multiple_attribute_MM_risk_scores(self: Task, id_col, eval_cols, file_info):
    df = read_file(file_info)
    result_dict = {}

    try:
        # check if dataframe is empty
        if df.empty:
            result_dict["Value Error"] = "Input dataframe is empty"
            return result_dict

        # Debug: Print input parameters
        print(f"DEBUG: id_col = {id_col}, type = {type(id_col)}")
        print(f"DEBUG: eval_cols = {eval_cols}, type = {type(eval_cols)}")
        print(f"DEBUG: DataFrame columns = {list(df.columns)}")

        # Handle eval_cols - it might be a string or list
        if isinstance(eval_cols, str):
            # If it's a string, split by comma and clean up
            eval_cols = [col.strip()
                         for col in eval_cols.split(',') if col.strip()]
            print(f"DEBUG: After string processing, eval_cols = {eval_cols}")
        elif isinstance(eval_cols, list):
            # If it's already a list, clean up each item
            eval_cols = [col.strip() for col in eval_cols if col.strip()]
            print(f"DEBUG: After list processing, eval_cols = {eval_cols}")
        else:
            raise ValueError(
                f"eval_cols must be a string or list, got {type(eval_cols)}")

        # Check if eval_cols is empty after processing
        if not eval_cols:
            raise ValueError(
                "No valid columns provided in eval_cols after processing")

        # Validate that all columns exist in the dataframe
        missing_cols = [col for col in eval_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Columns not found in dataset: {missing_cols}")

        # Validate id_col
        if not id_col or id_col not in df.columns:
            raise ValueError(f"ID column '{id_col}' not found in dataset")

        print(f"DEBUG: Final eval_cols = {eval_cols}")
        print(f"DEBUG: Final id_col = {id_col}")

        # select specidied columns from dataframe
        selected_columns = [id_col] + eval_cols
        print(f"DEBUG: selected_columns = {selected_columns}")
        selected_df = df[selected_columns]

        selected_df = selected_df.dropna()

        # check if the dataframe is still non-empty after dropping missing values
        if selected_df.empty:
            result_dict["Values Error"] = "After dropping missing values, the dataframe is empty"
            return result_dict

        # convert dataframe to numpy array
        my_array = selected_df.to_numpy()

        # array to store risk scores of each data point
        risk_scores = np.zeros(len(my_array))
        # risk scoring
        for j in range(len(my_array)):

            if len(my_array[0]) > 2:
                priv_prob_MM = 1

                for i in range(2, len(my_array[0])):

                    attr1_tot = np.count_nonzero(
                        my_array[:, i-1] == my_array[j][i-1])

                    mask_attr1_user = (my_array[:, 0] == my_array[j][0]) & (
                        my_array[:, i-1] == my_array[j][i-1])
                    count_attr1_user = np.count_nonzero(mask_attr1_user)

                    start_prob_attr1 = attr1_tot/len(my_array)  # 1

                    obs_prob_attr1 = 1 - (count_attr1_user/attr1_tot)  # 2

                    mask_attr1_attr2 = (my_array[:, i-1] == my_array[j][i-1])
                    count_attr1_attr2 = np.count_nonzero(mask_attr1_attr2)

                    mask2_attr1_attr2 = (
                        my_array[:, i-1] == my_array[j][i-1]) & (my_array[:, i] == my_array[j][i])
                    count2_attr1_attr2 = np.count_nonzero(mask2_attr1_attr2)

                    trans_prob_attr1_attr2 = count2_attr1_attr2/count_attr1_attr2  # 3

                    attr2_tot = np.count_nonzero(
                        my_array[:, i] == my_array[j][i])

                    mask_attr2_user = (my_array[:, 0] == my_array[j][0]) & (
                        my_array[:, i] == my_array[j][i])
                    count_attr2_user = np.count_nonzero(mask_attr2_user)

                    obs_prob_attr2 = 1 - (count_attr2_user/attr2_tot)  # 4

                    priv_prob_MM = priv_prob_MM * start_prob_attr1 * \
                        obs_prob_attr1*trans_prob_attr1_attr2*obs_prob_attr2
                    worst_case_MM_risk_score = round(1 - priv_prob_MM, 2)  # 5
                risk_scores[j] = worst_case_MM_risk_score
            elif len(my_array[0]) == 2:
                priv_prob_MM = 1
                attr1_tot = np.count_nonzero(my_array[:, 1] == my_array[j][1])

                mask_attr1_user = (my_array[:, 0] == my_array[j][0]) & (
                    my_array[:, 1] == my_array[j][1])
                count_attr1_user = np.count_nonzero(mask_attr1_user)

                start_prob_attr1 = attr1_tot/len(my_array)  # 1

                obs_prob_attr1 = 1 - (count_attr1_user/attr1_tot)  # 2

                priv_prob_MM = priv_prob_MM * start_prob_attr1*obs_prob_attr1
                worst_case_MM_risk_score = round(1 - priv_prob_MM, 2)  # 5
                risk_scores[j] = worst_case_MM_risk_score

        # calculate the entire dataset privacy level
        min_risk_scores = np.zeros(len(risk_scores))
        # Calculate the Euclidean distance
        euclidean_distance = np.linalg.norm(risk_scores - min_risk_scores)

        max_risk_scores = np.ones(len(risk_scores))

        # max euclidean distance
        max_euclidean_distance = np.linalg.norm(
            max_risk_scores - min_risk_scores)
        normalized_distance = euclidean_distance/max_euclidean_distance

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
        x_label = ",".join(eval_cols)
        # Create a box plot
        plt.figure(figsize=(8, 8))
        # vert=False for horizontal box plot
        plt.boxplot(risk_scores, vert=True)
        plt.title('Box Plot of Multiple Attribute Risk Scores')
        plt.ylabel('Risk Score')
        plt.xlabel('Feature Combination')
        plt.xticks([1], [x_label])

        # Save the plot as a PNG image in memory
        image_stream = io.BytesIO()
        plt.savefig(image_stream, format='png')
        plt.close()

        # Convert the image to a base64 string
        image_stream.seek(0)
        base64_image = base64.b64encode(image_stream.read()).decode('utf-8')
        image_stream.close()

        result_dict["Description"] = (
            "This metric evaluates the joint risk posed by combinations of quasi-identifiers. Lower overall risk scores are preferred, as they indicate that the selected set of features does not easily allow re-identification."
        )
        result_dict["Graph interpretation"] = (
            "The box plot shows the distribution of combined risk scores. A distribution concentrated at lower values indicates better privacy."
        )
        result_dict["Descriptive statistics of the risk scores"] = stats_dict
        result_dict["Multiple attribute risk scoring Visualization"] = base64_image
        result_dict['Dataset Risk Score'] = normalized_distance

        return result_dict
    except SoftTimeLimitExceeded:
        raise Exception("Multiple Attribute Risk task timed out.")
    except Exception as e:
        result_dict["Error"] = str(e)
        # Ensure the visualization key is always present for frontend compatibility
        result_dict["Multiple attribute risk scoring Visualization"] = ""
        result_dict["Description"] = f"Error occurred: {str(e)}"
        result_dict["Graph interpretation"] = "No visualization available due to error."
        return result_dict


@shared_task(bind=True, ignore_result=False)
def compute_k_anonymity(self: Task, quasi_identifiers: List[str], file_info: tuple[str, str, str]):
    data = read_file(file_info)
    result_dict = {}
    try:
        if data.empty:
            raise ValueError("Input DataFrame is empty.")

        for qi in quasi_identifiers:
            if qi not in data.columns:
                raise ValueError(
                    f"Quasi-identifier '{qi}' not found in the dataset.")

        data.replace('?', pd.NA, inplace=True)
        clean_data = data.dropna(subset=quasi_identifiers)
        if clean_data.empty:
            raise ValueError(
                "No data left after dropping rows with missing quasi-identifiers.")

        equivalence_classes = clean_data.groupby(
            quasi_identifiers).size().reset_index(name='count')
        counts = equivalence_classes["count"]

        # Compute k-anonymity
        k_anonymity = int(counts.min())

        # Descriptive statistics
        desc_stats = {
            'min': int(counts.min()),
            'max': int(counts.max()),
            'mean': round(counts.mean(), 2),
            'median': int(counts.median())
        }

        # Histogram of equivalence class sizes
        hist_data = counts.value_counts().sort_index().to_dict()
        plt.figure(figsize=(8, 5))
        plt.bar(hist_data.keys(), hist_data.values(), color='skyblue')
        plt.xlabel('Equivalence Class Size (k)')
        plt.ylabel('Number of Equivalence Classes')
        plt.title('Distribution of Equivalence Class Sizes')
        plt.grid(axis='y', alpha=0.75)
        # Save histogram to base64
        img_stream = io.BytesIO()
        plt.savefig(img_stream, format='png')
        plt.close()
        img_stream.seek(0)
        base64_image = base64.b64encode(img_stream.read()).decode('utf-8')
        img_stream.close()

        # Risk scoring based on k value
        # Normalize risk: Higher k = lower risk, scale it from 0 to 1
        # Example: if k=1 => high risk (1.0), if k>=50 => very low risk (~0.0)
        dataset_size = clean_data.shape[0]

        if dataset_size < 150:
            # 5% of dataset or at least 3
            max_safe_k = max(3, int(dataset_size * 0.05))
        elif dataset_size < 1500:
            max_safe_k = max(10, int(dataset_size * 0.01))  # 1% or at least 10
        else:
            max_safe_k = min(100, int(dataset_size * 0.01))  # Cap at 100

        if k_anonymity == 1:
            risk_score = 1.0
        else:
            risk_score = min(1.0, round(
                1 - min(k_anonymity / max_safe_k, 1.0), 2))

        # Final result
        result_dict = {
            "Value": k_anonymity,
            "Risk Score": risk_score,
            "descriptive_statistics": desc_stats,
            "histogram_data": hist_data,
            "k-Anonymity Visualization": base64_image,
            "Description": (
                "k-anonymity measures the minimum group size sharing the same quasi-identifier values. Higher k values are preferred, as they indicate stronger anonymity."
            ),
            "Graph interpretation": (
                "The histogram shows the distribution of equivalence class sizes. A shift toward larger class sizes (higher k) is desirable for privacy."
            )
        }
    except SoftTimeLimitExceeded:
        raise Exception("K anonymity task timed out.")
    except Exception as e:
        result_dict["error"] = str(e)

    return result_dict


@shared_task(bind=True, ignore_result=False)
def compute_l_diversity(self: Task, quasi_identifiers: list, sensitive_column: str, file_info: tuple[str, str, str]):
    data = read_file(file_info)
    result_dict = {}
    try:
        # Validate input DataFrame
        if data.empty:
            raise ValueError("Input DataFrame is empty.")

        # Validate quasi-identifiers
        for qi in quasi_identifiers:
            if qi not in data.columns:
                raise ValueError(
                    f"Quasi-identifier '{qi}' not found in the dataset.")

        # Validate sensitive column presence
        if sensitive_column not in data.columns:
            raise ValueError(
                f"Sensitive column '{sensitive_column}' not found in the dataset.")

        data = data.replace('?', pd.NA)

        # Drop rows with missing quasi-identifiers or sensitive values
        clean_data = data.dropna(subset=quasi_identifiers + [sensitive_column])
        if clean_data.empty:
            raise ValueError(
                "No data left after dropping rows with missing quasi-identifiers or sensitive values.")

        # Compute l-diversities: count of unique sensitive values per equivalence class
        l_diversities = clean_data.groupby(quasi_identifiers)[
            sensitive_column].nunique()

        # Minimum l-diversity (lowest number of distinct sensitive values)
        min_l_diversity = int(l_diversities.min())

        # Descriptive statistics for l-diversity distribution
        desc_stats = {
            'min': int(l_diversities.min()),
            'max': int(l_diversities.max()),
            'mean': round(l_diversities.mean(), 2),
            'median': int(l_diversities.median())
        }

        # Histogram plot of l-diversity counts
        # or use: (l_diversities / 2).round() * 2 for bin size of 2
        binned_l_diversities = l_diversities.round()
        hist_data = binned_l_diversities.value_counts().sort_index()
        plt.figure(figsize=(8, 8))
        plt.bar(hist_data.index, hist_data.values, color='skyblue')
        plt.xlabel('Number of Distinct Sensitive Values (l)')
        plt.ylabel('Number of Equivalence Classes')
        plt.title('Distribution of l-Diversity Across Equivalence Classes')
        plt.xticks(sorted(hist_data.index))
        plt.grid(axis='y', alpha=0.75)

        # Save plot to base64 string
        img_stream = io.BytesIO()
        plt.savefig(img_stream, format='png')
        plt.close()
        img_stream.seek(0)
        base64_image = base64.b64encode(img_stream.read()).decode('utf-8')
        img_stream.close()

        # Calculate risk score based on min l-diversity
        dataset_size = clean_data.shape[0]
        if dataset_size < 150:
            max_safe_l = max(2, int(dataset_size * 0.05)
                             )  # 5% for small datasets
        elif dataset_size < 1500:
            max_safe_l = max(10, int(dataset_size * 0.01))  # 1% or minimum 10
        else:
            max_safe_l = min(50, int(dataset_size * 0.01))  # Cap at 50

        risk_score = max(
            0.0, min(1.0, round(1 - min_l_diversity / max_safe_l, 2)))

        # Compose result dictionary
        result_dict = {
            "Value": min_l_diversity,
            "Risk Score": risk_score,
            "descriptive_statistics": desc_stats,
            "histogram_data": hist_data.to_dict(),
            "l-Diversity Visualization": base64_image,
            "Description": (
                "l-diversity quantifies the diversity of sensitive attributes within each group. Higher l values are preferred, indicating less risk of attribute disclosure."
            ),
            "Graph interpretation": (
                "The histogram displays the spread of l-diversity values. A distribution concentrated at higher l values is optimal."
            )
        }
    except SoftTimeLimitExceeded:
        raise Exception("L Diversity task timed out.")
    except Exception as e:
        result_dict["error"] = str(e)

    return result_dict


@shared_task(bind=True, ignore_result=False)
def compute_t_closeness(self: Task, quasi_identifiers: List[str], sensitive_column: str, file_info: tuple[str, str, str]):
    data = read_file(file_info)
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
                raise ValueError(
                    f"Quasi-identifier '{qi}' not found in the dataset.")

        if sensitive_column not in data.columns:
            raise ValueError(
                f"Sensitive column '{sensitive_column}' not found in the dataset.")

        data = data.replace('?', pd.NA)
        clean_data = data.dropna(subset=quasi_identifiers + [sensitive_column])
        if clean_data.empty:
            raise ValueError(
                "No data left after dropping rows with missing values.")

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
            "median": round(t_series.median(), 4)
        }

        # Histogram plot
        hist_data = t_series.round(2).value_counts().sort_index()
        plt.figure(figsize=(8, 5))
        plt.bar(hist_data.index, hist_data.values, color='salmon')
        plt.xlabel('t-Closeness Value (TVD)')
        plt.ylabel('Number of Equivalence Classes')
        plt.title('Distribution of T-Closeness Across Equivalence Classes')
        plt.grid(axis='y', alpha=0.75)

        img_stream = io.BytesIO()
        plt.savefig(img_stream, format='png')
        plt.close()
        img_stream.seek(0)
        base64_image = base64.b64encode(img_stream.read()).decode('utf-8')
        img_stream.close()

        # Risk Score: Higher t_closeness → higher privacy loss → higher risk
        if max_t <= 0.1:
            risk_score = 0.0
        elif max_t >= 0.4:
            risk_score = 1.0
        else:
            risk_score = round((max_t - 0.1) / 0.3, 2)

        result_dict = {

            "Value": max_t,
            "Risk Score": risk_score,
            "descriptive_statistics": desc_stats,
            "histogram_data": hist_data.to_dict(),
            "t-Closeness Visualization": base64_image,
            "Description": (
                "t-closeness measures the distance between the distribution of sensitive attributes in a group and the overall distribution. Lower t values are preferred, indicating less information leakage."
            ),
            "Graph interpretation": (
                "The histogram shows the distribution of t values. Lower t values across groups indicate stronger privacy."
            )
        }
    except SoftTimeLimitExceeded:
        raise Exception("T Closeness task timed out.")
    except Exception as e:
        result_dict["error"] = str(e)

    return result_dict


@shared_task(bind=True, ignore_result=False)
def compute_entropy_risk(self: Task, quasi_identifiers, file_info: tuple[str, str, str]):
    data = read_file(file_info)
    result_dict = {}

    try:
        if data.empty:
            raise ValueError("Input DataFrame is empty.")

        for qi in quasi_identifiers:
            if qi not in data.columns:
                raise ValueError(
                    f"Quasi-identifier '{qi}' not found in the dataset.")

        data = data.replace('?', pd.NA)
        clean_data = data.dropna(subset=quasi_identifiers)

        if clean_data.empty:
            raise ValueError(
                "No data left after dropping rows with missing values.")

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
        plt.bar(hist_data.index, hist_data.values, color='royalblue')
        plt.xlabel('Entropy Value')
        plt.ylabel('Number of Equivalence Classes')
        plt.title('Distribution of Entropy Across Equivalence Classes')
        plt.grid(axis='y', alpha=0.75)

        img_stream = io.BytesIO()
        plt.savefig(img_stream, format='png')
        plt.close()
        img_stream.seek(0)
        base64_image = base64.b64encode(img_stream.read()).decode('utf-8')
        img_stream.close()

        desc_stats = {
            "min": round(entropy_series.min(), 4),
            "max": round(entropy_series.max(), 4),
            "mean": round(entropy_series.mean(), 4),
            "median": round(entropy_series.median(), 4)
        }

        risk_score = round(
            1 - (rounded_entropy / np.log2(total_records + 1)), 4)
        risk_score = max(0.0, min(risk_score, 1.0))  # Bound it between 0 and 1

        result_dict = {
            "Value": rounded_entropy,
            "Risk Score": risk_score,
            "descriptive_statistics": desc_stats,
            "histogram_data": hist_data.to_dict(),
            "Entropy Risk Visualization": base64_image,
            "Description": (
                "Entropy risk quantifies the uncertainty in identifying individuals within equivalence classes. Higher entropy values are preferred, indicating greater anonymity and lower re-identification risk."
            ),
            "Graph interpretation": (
                "The bar chart visualizes the distribution of entropy values. Higher bars on the right (higher entropy) indicate better privacy; left-skewed distributions suggest higher risk."
            )
        }
    except SoftTimeLimitExceeded:
        raise Exception("Entropy Risk task timed out.")
    except Exception as e:
        result_dict["error"] = str(e)

    return result_dict
