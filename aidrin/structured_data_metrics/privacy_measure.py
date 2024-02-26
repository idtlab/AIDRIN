import numpy as np
import matplotlib.pyplot as plt
import io
import base64

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
        result_dict['BoxPlot'] = base64_image
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
        result_dict["Box Plot"] = base64_image
        result_dict['Dataset Risk Score'] = normalized_distance

        return result_dict

    except Exception as e:
        result_dict["Error"] = str(e)
        return result_dict
        
    

    

    