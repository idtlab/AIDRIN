from flask import Flask, request, jsonify, send_file, Response,render_template,send_from_directory
from structured_data_metrics.completeness import completeness
from structured_data_metrics.outliers import outliers
from structured_data_metrics.duplicity import duplicity
from structured_data_metrics.representation_rate import calculate_representation_rate, create_representation_rate_vis
from structured_data_metrics.statistical_rate import calculate_statistical_rates
from structured_data_metrics.real_repreentation_rate import calculate_real_representation_rates
from structured_data_metrics.compare_representation_rate import compare_rep_rates
from structured_data_metrics.correlation_score import calc_correlations
from structured_data_metrics.feature_relevance import generate_combined_plot_to_base64
from structured_data_metrics.FAIRness_dcat import categorize_metadata,extract_keys_and_values
from structured_data_metrics.FAIRness_datacite import categorize_keys_fair
from structured_data_metrics.add_noise import return_noisy_stats
from structured_data_metrics.class_imbalance import calc_imbalance_degree,class_distribution_plot
from structured_data_metrics.privacy_measure import generate_single_attribute_MM_risk_scores, generate_multiple_attribute_MM_risk_scores
 
from unstructured_data_metrics.chest_xray_image_readiness import *

import pandas as pd
import matplotlib.pyplot as plt
import os
import json
import pydicom
import time

app = Flask(__name__)


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

def summary_histograms(df):
    histograms = {}
    for column in df.select_dtypes(include='number').columns:
        plt.figure(figsize=(6, 4))
        plt.hist(df[column], bins=20)

        # Set a smaller font size for the title
        plt.title(f'Histogram for {column}', fontsize=8)

        # Add labels to the axes
        plt.xlabel('Values', fontsize=8)
        plt.ylabel('Frequency', fontsize=8)

        # Encode the plot as base64
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png')
        img_buffer.seek(0)
        encoded_img = base64.b64encode(img_buffer.read()).decode('utf-8')

        histograms[column] = encoded_img
        plt.close()
        img_buffer.close()

    return histograms

@app.route('/images/<path:filename>')
def serve_image(filename):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, 'images'), filename)

@app.route('/')
def homepage():
    return render_template('homepage.html')

@app.route('/summary_statistics', methods=['POST'])
def handle_summary_statistics():
    try:
        # Get the uploaded file
        file = request.files['file']

        # Read the CSV file
        csv_content = file.read().decode('utf-8')
        csv_data = io.StringIO(csv_content)
        
        # Load CSV data into a Pandas DataFrame
        df = pd.read_csv(csv_data)

        # Extract summary statistics
        summary_statistics = df.describe().to_dict()

        # Calculate probability distributions
        histograms = summary_histograms(df)

        # Separate numerical and categorical columns
        numerical_columns = [col for col, dtype in df.dtypes.items() if pd.api.types.is_numeric_dtype(dtype)]
        categorical_columns = [col for col, dtype in df.dtypes.items() if pd.api.types.is_object_dtype(dtype)]
        all_features = numerical_columns + categorical_columns

        for v in summary_statistics.values():
            for old_key in v:
                if old_key in ['25%','50%','75%']:
                    new_key = old_key.replace("%","th percentile")
                    v[new_key] = v.pop(old_key)

        # Count the number of records
        records_count = len(df)

        #count the number of features
        feature_count = len(df.columns)

        response_data = {
            'success': True,
            'message': 'File uploaded successfully',
            'records_count': records_count,
            'features_count': feature_count,
            'categorical_features': list(categorical_columns),
            'numerical_features': list(numerical_columns),
            'all_features':all_features,
            'summary_statistics': summary_statistics,
            'histograms': histograms
        }

        return jsonify(response_data)

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/upload_file', methods=['POST','GET'])
def upload_csv():

    start_time = time.time()


    try: 
        if request.method == 'GET':
            # Render the form for a GET request
            return render_template('upload_file.html')
        elif request.method == "POST":
            final_dict = {}
           
            uploaded_file = request.files['file']
            
            if uploaded_file.filename != '':
                final_dict['message']="File uploaded successfully"
                file = pd.read_csv(uploaded_file,index_col=False)

                #Completeness
                if request.form.get('completeness') == "yes":
                    
                    compl_dict = completeness(file)
                    compl_dict['Description'] = 'Indicate the proportion of available data for each feature, with values closer to 1 indicating high completeness, and values near 0 indicating low completeness.'
                    final_dict['Completeness'] = compl_dict
                #Outliers    
                if request.form.get('outliers') == 'yes':
                    out_dict = outliers(file)
                    out_dict['Description'] = "Outlier scores are calculated for numerical columns using the Interquartile Range (IQR) method, where a score of 1 indicates that all data points in a column are identified as outliers, a score of 0 signifies no outliers are detected"
                    final_dict['Outliers'] = out_dict
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
                    rep_dict['Probability ratios'] = calculate_representation_rate(file,list_of_cols)
                    rep_dict['Representation Rate Chart'] = create_representation_rate_vis(file,list_of_cols)
                    rep_dict['Description'] = "Represent probability ratios that quantify the relative representation of different categories within the sensitive features, highlighting differences in representation rates between various groups. Higher values imply overrepresentation relative to another"
                    final_dict['Representation Rate'] = rep_dict
                #statistical rate
                if request.form.get('statistical rate') == "yes" and request.form.get('features for statistical rate') != None and request.form.get('target for statistical rate') != None:
                    y_true = request.form.get('target for statistical rate')
                    sensitive_attribute_column = request.form.get('features for statistical rate')
                    sr_dict = calculate_statistical_rates(file,y_true,sensitive_attribute_column)
                    sr_dict['Description'] = 'The graph illustrates the statistical rates of various classes across different sensitive attributes. Each group in the graph represents a specific sensitive attribute, and within each group, each bar corresponds to a class, with the height indicating the proportion of that sensitive attribute within that particular class'
                    final_dict["Statistical Rate"] = sr_dict

                if request.form.get('real representation rate') == 'yes':
                    rrr_dict = {}
                    real_col = request.form.get('real column')
                    real_attr = [item.strip() for item in request.form.get('real attributes').split(",")]
                    real_val = [item.strip() for item in request.form.get("real values").split(",")]
                    rrr_dict["Probability ratios"] = calculate_real_representation_rates(real_col,real_attr,real_val)
                    rrr_dict['Description'] = 'Represent probability ratios that quantify the relative representation of different categories within the sensitive features in the actual world, highlighting differences in representation rates between various groups. Higher values imply overrepresentation relative to another'
                    final_dict['Real Representation Rate'] = rrr_dict

                if request.form.get('compare real to dataset') == 'yes':
                    comp_dict = compare_rep_rates(rep_dict['Probability ratios'],rrr_dict["Probability ratios"])
                    comp_dict["Description"] = "The stacked bar graph visually compares the proportions of specific sensitive attributes within both the real-world population and the given dataset. Each stack in the graph represents the combined ratio of these attributes, allowing for an immediate comparison of their distribution between the observed dataset and the broader demographic context"
                    final_dict['Representation Rate Comparison with Real World'] = comp_dict

                if request.form.get('correlations') == 'yes':
                    columns = request.form.get('correlation columns').replace("\r\n", "").split(",")
                    corr_dict = calc_correlations(file,columns)
                    corr_dict['Description'] = "Categorical correlations are assessed using Theil's U statistic, while numerical feature correlations are determined using Pearson correlation. The resulting values fall within the range of 0 to 1, with a value of 1 indicating a strong correlation between the variables"
                    final_dict['Correlations Analysis'] = corr_dict

                if request.form.get("feature relevancy") == "yes":
                    cat_cols = request.form.get("categorical features for feature relevancy").split(",")
                    num_cols = request.form.get("numerical features for feature relevancy").split(",")
                    target = request.form.get("target for feature relevance")
                    f_dict =  generate_combined_plot_to_base64(file,cat_cols,num_cols,target)
                    f_dict['Description'] = "For numerical target columns, scatter plots and box plots are generated to visually explore the relationship between numerical features and the target. For categorical target columns, count plots provide insights into the distribution of categorical features across different target categories. Additionally, a chi-squared test for independence is performed for each categorical feature against the target, yielding p-values that quantify the statistical significance of the association. Lower p-values indicate stronger evidence that a categorical feature is relevant for predicting the target."
                    final_dict['Feature relevance'] = f_dict

                #class imbalance
                if request.form.get("class imbalance") == "yes":
                    ci_dict = {}
                    classes = request.form.get("class feature")
                    ci_dict['Class distribution plot'] = class_distribution_plot(file,classes)
                    ci_dict['Description'] = "Each class is represented by a bar, and the height of the bar corresponds to the percentage of instances belonging to that class"
                    ci_dict['Imbalance degree'] = calc_imbalance_degree(file,classes,dist_metric="EU")#By default the distance metric is euclidean distance
                    final_dict['Class imbalance'] = ci_dict
                    
                #differential privacy
                if request.form.get("differential privacy") == "yes":
                    feature_to_add_noise = request.form.get("numerical features to add noise").split(",")
                    epsilon = request.form.get("privacy budget")
                    noisy_stat = return_noisy_stats(file,feature_to_add_noise,float(epsilon))
                    final_dict['DP statistics'] = noisy_stat
                
                #single attribute risk scores using markov model
                if request.form.get("single attribute risk score") == "yes":
                    id_feature = request.form.get("id feature to measure single attribute risk score")
                    eval_features = request.form.get("quasi identifiers to measure single attribute risk score").split(",")
                    final_dict["Single attribute risk scoring"] = generate_single_attribute_MM_risk_scores(file,id_feature,eval_features)
                
                #multpiple attribute risk score using markov model
                if request.form.get("multiple attribute risk score") == "yes":
                    id_feature = request.form.get("id feature to measure multiple attribute risk score")
                    eval_features = request.form.get("quasi identifiers to measure multiple attribute risk score").split(",")
                    final_dict["Multiple attribute risk scoring"] = generate_multiple_attribute_MM_risk_scores(file,id_feature,eval_features)
                
                formated_final_dict = format_dict_values(final_dict)

                end_time = time.time()

                execution_time = end_time - start_time
                print(f"Execution time: {execution_time} seconds")

                
                return jsonify(formated_final_dict)

            else:
                return jsonify({'error': 'No file uploaded'})
    except Exception as e:
        return jsonify({"Error":e})
    
    
    
@app.route('/FAIRness', methods=['GET', 'POST'])
def FAIRness():
    start_tiime = time.time()
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
            end_time = time.time()
            print(f"Execution time: {end_time - start_tiime} seconds")
            # Render the form for a GET request
            return render_template('upload_meta.html')

    except Exception as e:
        return jsonify({"error": str(e)}), 400

# @app.route('/FAIRness', methods=['GET', 'POST'])
# def FAIRness():
#     return cal_FAIRness()

@app.route('/medical_image_readiness',methods=['GET','POST'])
def med_img_readiness():
    final_dict = {}
    if request.method == 'POST':
        if "dicom" not in request.files:
            return jsonify({"error": "No 'dicom' field found in form data"}), 400
        
        # Get the uploaded file
        file = request.files['dicom']

        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400
        
        if file.filename.endswith('.dcm'):
            dicom_data = pydicom.dcmread(file,force=True)

            final_dict['Message'] = "File uploaded successfully"

            cnr_data = calculate_cnr_from_dicom(dicom_data)
            spatial_res_data = calculate_spatial_resolution(dicom_data)
            metadata_dcm = gather_image_quality_info(dicom_data)
            artifact = detect_and_visualize_artifacts(dicom_data)
            combined_dict = {**cnr_data, **spatial_res_data}
            formatted_combined_dict = format_dict_values(combined_dict)
            final_dict['Image Readiness Scores'] = formatted_combined_dict
            final_dict['DCM Image Quality Metadata'] = metadata_dcm
            final_dict['Artifacts'] = artifact

            return jsonify(final_dict),200
    return render_template('medical_image.html')
                        
if __name__ == '__main__':
    app.run(debug=True)
    
    