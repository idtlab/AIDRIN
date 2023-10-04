from flask import Flask, request, jsonify, send_file, Response,render_template,send_from_directory
from structured_data_metrics.completeness import completeness
from structured_data_metrics.outliers import outliers
from structured_data_metrics.duplicity import duplicity
from structured_data_metrics.representation_rate import calculate_representation_rate
from structured_data_metrics.statistical_rate import calculate_statistical_rates
from structured_data_metrics.real_repreentation_rate import calculate_real_representation_rates
from structured_data_metrics.compare_representation_rate import compare_rep_rates
from structured_data_metrics.correlation_score import calc_correlations
from structured_data_metrics.feature_relevance import calc_shapely
from structured_data_metrics.FAIRness_dcat import categorize_metadata,extract_keys_and_values
from structured_data_metrics.FAIRness_datacite import categorize_keys_fair
from structured_data_metrics.add_noise import return_noisy_stats


import pandas as pd
import matplotlib.pyplot as plt
import os
import json

app = Flask(__name__)

def visualize(name,dict):

    # Extract labels and completeness values
    labels = list(dict.keys())
    values = list(dict.values())

    # Create a bar chart
    plt.figure(figsize=(20, 10))
    plt.bar(labels, values)
    plt.xlabel("Categories")
    plt.ylabel("Metric Value")
    plt.title(f"{name} Data Visualization")
    plt.xticks(rotation=90)  # Rotate x-axis labels for better readability
    
    # Specify the folder name
    folder_name = "Visualizations"

    # Ensure that the folder exists, or create it if it doesn't
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    # Save the chart inside the "Visualizations" folder
    plt.savefig(os.path.join(folder_name, f"{name}_chart.png"))

    # plt.show()


def format_dict_values(d):
    formatted_dict = {}
    
    for key, value in d.items():
        if isinstance(value, dict):
            formatted_dict[key] = format_dict_values(value)
        elif isinstance(value, (int, float)):
            formatted_dict[key] = round(value, 2)  # Format numerical values to two decimal places
        else:
            formatted_dict[key] = value  # Preserve non-numeric values
    
    return formatted_dict

@app.route('/images/<path:filename>')
def serve_image(filename):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, 'images'), filename)

@app.route('/')
def homepage():
    return render_template('homepage.html')

@app.route('/upload_file', methods=['GET'])
def upload_file_form():
    return render_template('upload_file.html')

@app.route('/upload_file', methods=['POST'])
def upload_csv():

    try: 
        final_dict = {}
        uploaded_file = request.files['file']
        
        if uploaded_file.filename != '':
            final_dict['message']="File uploaded successfully"
            file = pd.read_csv(uploaded_file,index_col=False)
         
            #Completeness
            if request.form.get('completeness') == "yes":
                
                compl_dict = completeness(file)
                compl_dict['Description'] = 'These scores indicate the proportion of available data for each feature, with values closer to 1 indicating high completeness, and values near 0 indicating low completeness.'
                final_dict['Completeness'] = compl_dict

                #visualization
                visualize("Completeness",compl_dict['Completeness scores'])
                # return send_file("Completeness_chart.png",mimetype='image/png')

            #Outliers    
            if request.form.get('outliers') == 'yes':
                out_dict = outliers(file)
                out_dict['Description'] = "Outlier scores are calculated for numerical columns using the Interquartile Range (IQR) method, where a score of 1 indicates that all data points in a column are identified as outliers, a score of 0 signifies no outliers are detected"
                final_dict['Outliers'] = out_dict

                visualize('Outliers',out_dict['Outlier scores'])
            #Duplicity
            if request.form.get('duplicity') == 'yes':
                dup_dict = duplicity(file)
                dup_dict['Description'] = "A value of 0 indicates no duplicates, and a value closer to 1 signifies a higher proportion of duplicated data points in the dataset"
                final_dict['Duplicity'] = dup_dict    
            #Representation Rate
            if request.form.get('representation rate') == "yes" and request.form.get('features for representation rate') != None:
                #convert the string values a list
                rep_dict = {}
                list_of_cols = [item.strip() for item in request.form.get('features for representation rate').split(',')]
                rep_dict["Probability ratios"] = calculate_representation_rate(file,list_of_cols)
                rep_dict['Description'] = "Represent probability ratios that quantify the relative representation of different categories within the sensitive features, highlighting differences in representation rates between various groups. Higher values imply overrepresentation relative to another"
                final_dict['Representation Rate'] = rep_dict
            #statistical rate
            if request.form.get('statistical rate') == "yes" and request.form.get('features for statistical rate') != None and request.form.get('target for statitical rate') != None:
                y_true = request.form.get('target for statitical rate')
                sensitive_attribute_column = request.form.get('features for statistical rate')
                sr_dict = calculate_statistical_rates(file,y_true,sensitive_attribute_column)
                sr_dict['Description'] = 'Represent probability ratios that quantify the likelihood of an association between specific categories within a sensitive feature and a target variable, where smaller values indicate a lower likelihood, and higher values indicate a higher likelihood of association'
                final_dict["Statistical Rate"] = sr_dict

            if request.form.get('real representation rate') == 'yes':
                rrr_dict = {}
                real_col = request.form.get('real column1')
                real_attr = [item.strip() for item in request.form.get('real attributes1').split(",")]
                real_val = [item.strip() for item in request.form.get("real values1").split(",")]
                rrr_dict["Probability ratios"] = calculate_real_representation_rates(real_col,real_attr,real_val)
                rrr_dict['Description'] = 'Represent probability ratios that quantify the relative representation of different categories within the sensitive features in the actual world, highlighting differences in representation rates between various groups. Higher values imply overrepresentation relative to another'
                final_dict['Real Representation Rate'] = rrr_dict

            if request.form.get('compare real to dataset') == 'yes':
                comp_dict = compare_rep_rates(rep_dict['Probability ratios'],rrr_dict["Probability ratios"])
                comp_dict["Description"] = "These scores indicate the proportion of available data for each feature, with values closer to 1 indicating high completeness, and values near 0 indicating low completeness"
                final_dict['Representation Rate Comparison with Real World'] = comp_dict
                visualize("Real World vs Dataset's Representation Rate Comparisons",comp_dict["Comparisons"])

            if request.form.get('correlations') == 'yes':
                columns = request.form.get('correlation columns').split(",")
                corr_dict = calc_correlations(file,columns)
                corr_dict['Description'] = "Categorical correlations are assessed using Theil's U statistic, while numerical feature correlations are determined using Pearson correlation. The resulting values fall within the range of 0 to 1, with a value of 1 indicating a strong correlation with the target variable"
                final_dict['Correlation Scores'] = corr_dict

            if request.form.get("top 3 features") == "yes":
                cat_cols = request.form.get("categorical features for feature relevancy").split(",")
                num_cols = request.form.get("numerical features for feature relevancy").split(",")
                target = request.form.get("target for feature relevance")
                f_dict =  calc_shapely(file,cat_cols,num_cols,target)
                f_dict['Description'] = "The top 3 dataset features are identified through Shapley values computed with a Random Forest classifier. Additionally, categorical features have been one-hot encoded, which might lead to certain feature names appearing in this encoded representation."
                final_dict['Top 3 features based on shapley values'] = f_dict
            #differential privacy
            if request.form.get("privacy preservation") == "yes":
                feature_to_add_noise = request.form.get("numerical features to add noise").split(",")
                epsilon = request.form.get("privacy budget")
                noisy_stat = return_noisy_stats(file,feature_to_add_noise,float(epsilon))
                final_dict['Privacy preservation statistics'] = noisy_stat
            
            formated_final_dict = format_dict_values(final_dict)
            return jsonify(formated_final_dict)

        
        else:
            return jsonify({'error': 'No file uploaded'})
    except Exception as e:
        return jsonify({"Error":"Error occured"})
    
@app.route('/FAIRness', methods=['GET', 'POST'])
def cal_FAIRness():
    try:
        if request.method == 'POST':
            # Check if the 'metadata' field exists in the form data
            if 'metadata' not in request.files:
                return jsonify({"error": "No 'metadata' field found in form data"}), 400

            # Get the uploaded file
            file = request.files['metadata']

            if file.filename == '':
                return jsonify({"error": "No selected file"}), 400

            if file.filename.endswith('.json'):
                if request.form.get("metadata type") == "DCAT":
                    # Read and parse the JSON data
                    json_data = file.read()
                    try:
                        data_dict = json.loads(json_data.decode('utf-8'))
                        extracted_json = extract_keys_and_values(data_dict)
                        fair_dict = categorize_metadata(extracted_json, data_dict)
                        return jsonify(format_dict_values(fair_dict)), 200
                    except json.JSONDecodeError as e:
                        return jsonify({"error": f"Error parsing JSON: {str(e)}"}), 400
                elif request.form.get("metadata type") == "Datacite":
                    json_data = file.read()
                    data_dict = json.loads(json_data.decode('utf-8'))
                    
                    try:
                        categorized_data= categorize_keys_fair(data_dict)
                        return jsonify(categorized_data), 200
                    except json.JSONDecodeError as e:
                        return jsonify({"error": f"Error parsing JSON: {str(e)}"}), 400

            else:
                return jsonify({"error": "Invalid file format. Please upload a JSON file."}), 400
        else:
            # Render the form for a GET request
            return render_template('upload_meta.html')

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/FAIRness', methods=['GET', 'POST'])
def FAIRness():
    return cal_FAIRness()

            
if __name__ == '__main__':
    app.run(debug=True)