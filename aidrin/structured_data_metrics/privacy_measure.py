import numpy as np
import matplotlib.pyplot as plt
import io
import base64
import pandas as pd
from typing import List

def generate_single_attribute_MM_risk_scores(df, id_col, eval_cols):
    result_dict = {}

    try:
        # Check if the DataFrame is empty
        if df.empty:
            raise ValueError("Input DataFrame is empty.")

        # eval_cols = eval_cols.split(',')
    
        # # Remove any leading or trailing whitespace from each element
        # eval_cols = [identifier.strip() for identifier in eval_cols]


        # Check if the DataFrame is still non-empty after dropping missing values
        if df.empty:
            raise ValueError("After dropping missing values, the DataFrame is empty.")

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
                attr1_tot = np.count_nonzero(my_array[:, i + 1] == my_array[j, i + 1])

                mask_attr1_user = (my_array[:, 0] == my_array[j, 0]) & (my_array[:, i + 1] == my_array[j, i + 1])
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
        plt.figure(figsize=(8,8))
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
        result_dict["Description"] = "Box plots depict the privacy risk scores associated with each selected features"
        

    except Exception as e:
        result_dict["Error"] = str(e)

    return result_dict


def generate_multiple_attribute_MM_risk_scores(df, id_col, eval_cols):
    result_dict = {}

    try:
        #check if dataframe is empty
        if df.empty:
            result_dict["Value Error"] = "Input dataframe is empty"
            return result_dict

        #select specidied columns from dataframe
        selected_columns = [id_col] + eval_cols
        selected_df = df[selected_columns]

        selected_df = selected_df.dropna()

        #check if the dataframe is still non-empty after dropping missing values
        if selected_df.empty:
            result_dict["Values Error"] = "After dropping missing values, the dataframe is empty"
            return result_dict
            
        #convert dataframe to numpy array
        my_array = selected_df.to_numpy()

        #array to store risk scores of each data point
        risk_scores = np.zeros(len(my_array))
        #risk scoring
        for j in range(len(my_array)):
    
            if len(my_array[0]) >2:
                priv_prob_MM = 1
        
                for i in range(2,len(my_array[0])):    
                    
                    attr1_tot = np.count_nonzero(my_array[:,i-1] == my_array[j][i-1])
            
                    mask_attr1_user = (my_array[:, 0] == my_array[j][0]) & (my_array[:, i-1] == my_array[j][i-1])
                    count_attr1_user = np.count_nonzero(mask_attr1_user)
                    
                    start_prob_attr1 = attr1_tot/len(my_array)#1
                    
                    obs_prob_attr1 = 1 - (count_attr1_user/attr1_tot)#2
                    
                    mask_attr1_attr2 = (my_array[:, i-1] == my_array[j][i-1]) 
                    count_attr1_attr2 = np.count_nonzero(mask_attr1_attr2)
            
                    mask2_attr1_attr2 = (my_array[:, i-1] == my_array[j][i-1]) & (my_array[:, i] == my_array[j][i]) 
                    count2_attr1_attr2 = np.count_nonzero(mask2_attr1_attr2)
                    
                    trans_prob_attr1_attr2 = count2_attr1_attr2/count_attr1_attr2#3
                    
                    attr2_tot = np.count_nonzero(my_array[:,i]==my_array[j][i])
            
                    mask_attr2_user = (my_array[:, 0] == my_array[j][0]) & (my_array[:, i] == my_array[j][i])
                    count_attr2_user = np.count_nonzero(mask_attr2_user)
        
                    obs_prob_attr2 = 1 - (count_attr2_user/attr2_tot)#4
            
                    priv_prob_MM = priv_prob_MM * start_prob_attr1*obs_prob_attr1*trans_prob_attr1_attr2*obs_prob_attr2
                    worst_case_MM_risk_score = round(1 - priv_prob_MM,2)#5
                risk_scores[j] = worst_case_MM_risk_score
            elif len(my_array[0]) == 2:
                priv_prob_MM = 1
                attr1_tot = np.count_nonzero(my_array[:,1] == my_array[j][1])
        
                mask_attr1_user = (my_array[:, 0] == my_array[j][0]) & (my_array[:, 1] == my_array[j][1])
                count_attr1_user = np.count_nonzero(mask_attr1_user)
                
                start_prob_attr1 = attr1_tot/len(my_array)#1
                
                obs_prob_attr1 = 1 - (count_attr1_user/attr1_tot)#2
        
                priv_prob_MM = priv_prob_MM * start_prob_attr1*obs_prob_attr1
                worst_case_MM_risk_score = round(1 - priv_prob_MM,2)#5
                risk_scores[j] = worst_case_MM_risk_score

        # calculate the entire dataset privacy level
        min_risk_scores = np.zeros(len(risk_scores))
        # Calculate the Euclidean distance
        euclidean_distance = np.linalg.norm(risk_scores - min_risk_scores)
        
        max_risk_scores = np.ones(len(risk_scores))

        #max euclidean distance
        max_euclidean_distance = np.linalg.norm(max_risk_scores - min_risk_scores)
        normalized_distance = euclidean_distance/max_euclidean_distance
                
        #descriptive statistics
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
        plt.figure(figsize=(8,8))
        plt.boxplot(risk_scores, vert=True)  # vert=False for horizontal box plot
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

        result_dict["Description"] = "Distribution of risk scores derived from user-selected features"
        result_dict["Descriptive statistics of the risk scores"] = stats_dict
        result_dict["Multiple attribute risk scoring Visualization"] = base64_image
        result_dict['Dataset Risk Score'] = normalized_distance

        return result_dict

    except Exception as e:
        result_dict["Error"] = str(e)
        return result_dict
        
def compute_k_anonymity(data: pd.DataFrame, quasi_identifiers: List[str]):
    result_dict = {}
    try:
        if data.empty:
            raise ValueError("Input DataFrame is empty.")

        for qi in quasi_identifiers:
            if qi not in data.columns:
                raise ValueError(f"Quasi-identifier '{qi}' not found in the dataset.")

        data.replace('?', pd.NA, inplace=True)
        clean_data = data.dropna(subset=quasi_identifiers)
        if clean_data.empty:
            raise ValueError("No data left after dropping rows with missing quasi-identifiers.")

        equivalence_classes = clean_data.groupby(quasi_identifiers).size().reset_index(name='count')
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
        max_safe_k = max(5, int( dataset_size*0.01))   # 1% of dataset, clamped between 5 and 100
        risk_score = min(1.0, round(1 - min(k_anonymity / max_safe_k, 1.0), 2))

        # Final result
        result_dict = {
            "k_anonymity": k_anonymity,
            "risk_score": risk_score,
            "descriptive_statistics": desc_stats,
            "histogram_data": hist_data,
            "histogram_plot_base64": base64_image,
            "description": "k-anonymity measures the minimum size of equivalence classes formed by quasi-identifiers. "
                           "Higher k indicates better privacy protection. The histogram shows the distribution of equivalence class sizes."
        }

    except Exception as e:
        result_dict["error"] = str(e)

    return result_dict

    try:
        # Validate input DataFrame
        if data.empty:
            raise ValueError("Input DataFrame is empty.")
        
        # Validate quasi-identifiers
        for qi in quasi_identifiers:
            if qi not in data.columns:
                raise ValueError(f"Quasi-identifier '{qi}' not found in the dataset.")   
        data.replace('?', pd.NA, inplace=True)

        # Drop rows with missing values in quasi-identifiers
        clean_data = data.dropna(subset=quasi_identifiers)
        
        if clean_data.empty:
            raise ValueError("No data left after dropping rows with missing quasi-identifiers.")
        
        # Group by quasi-identifiers and count occurrences
        equivalence_classes = clean_data.groupby(quasi_identifiers).size().reset_index(name='count')
        
        # Determine k-anonymity
        k_anonymity = equivalence_classes.min()
        sorted_equivalence_classes = equivalence_classes.sort_values()

        

        return k_anonymity, sorted_equivalence_classes
    

    except Exception as e:
        print(f"[Error in compute_k_anonymity]: {e}")
        return None

def compute_l_diversity(data: pd.DataFrame, quasi_identifiers: List[str], sensitive_column: str):
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
            raise ValueError(f"Sensitive column '{sensitive_column}' not found in the dataset.")

        data = data.replace('?', pd.NA)

        # Drop rows with missing values in quasi-identifiers or sensitive column
        clean_data = data.dropna(subset=quasi_identifiers + [sensitive_column])
        if clean_data.empty:
            raise ValueError("No data left after dropping rows with missing quasi-identifiers or sensitive values.")

        # Group by quasi-identifiers and count unique sensitive values
        l_diversities = clean_data.groupby(quasi_identifiers)[sensitive_column].nunique()

        # Minimum number of distinct sensitive values across all groups
        l_diversity = l_diversities.min()

        return l_diversity, l_diversities.sort_values()

    except Exception as e:
        print(f"[Error in compute_l_diversity]: {e}")
        return None


def compute_t_closeness(data: pd.DataFrame,quasi_identifiers: List[str],sensitive_column: str):
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
            raise ValueError(f"Sensitive column '{sensitive_column}' not found in the dataset.")
        
        # Treat '?' as missing values and replace with pd.NA
        data = data.replace('?', pd.NA)
        clean_data = data.dropna(subset=quasi_identifiers + [sensitive_column])
        
        if clean_data.empty:
            raise ValueError("No data left after dropping rows with missing values.")

        # Overall sensitive value distribution (normalized counts)
        global_dist = clean_data[sensitive_column].value_counts(normalize=True)

        # Function to compute total variation distance
        def tvd(p, q):
            all_keys = set(p.index).union(set(q.index))
            p_full = p.reindex(all_keys, fill_value=0)
            q_full = q.reindex(all_keys, fill_value=0)
            return 0.5 * np.abs(p_full - q_full).sum()

        # Group by quasi-identifiers and compute t-closeness for each group
        t_values = {}

        for group_keys, group_df in clean_data.groupby(quasi_identifiers):
            group_dist = group_df[sensitive_column].value_counts(normalize=True)
            t_values[group_keys] = tvd(group_dist, global_dist)

        t_series = pd.Series(t_values)
        t_max = t_series.max()  # Worst case (largest divergence from global distribution)

        return t_max, t_series.sort_values(ascending=False)

    except Exception as e:
        print(f"[Error in compute_t_closeness]: {e}")
        return None

    

    