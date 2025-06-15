from flask import Flask, request, jsonify, send_file, Response,render_template,send_from_directory,session,redirect,url_for, current_app
from aidrin.structured_data_metrics.completeness import completeness
from aidrin.structured_data_metrics.outliers import outliers
from aidrin.structured_data_metrics.duplicity import duplicity
from aidrin.structured_data_metrics.representation_rate import calculate_representation_rate, create_representation_rate_vis
from aidrin.structured_data_metrics.statistical_rate import calculate_statistical_rates
from aidrin.structured_data_metrics.real_repreentation_rate import calculate_real_representation_rates
from aidrin.structured_data_metrics.compare_representation_rate import compare_rep_rates
from aidrin.structured_data_metrics.correlation_score import calc_correlations
from aidrin.structured_data_metrics.feature_relevance import data_cleaning, pearson_correlation, plot_features
from aidrin.structured_data_metrics.FAIRness_dcat import categorize_metadata,extract_keys_and_values
from aidrin.structured_data_metrics.FAIRness_datacite import categorize_keys_fair
from aidrin.structured_data_metrics.add_noise import return_noisy_stats
from aidrin.structured_data_metrics.class_imbalance import calc_imbalance_degree,class_distribution_plot
from aidrin.structured_data_metrics.privacy_measure import generate_single_attribute_MM_risk_scores, generate_multiple_attribute_MM_risk_scores, compute_k_anonymity, compute_l_diversity, compute_t_closeness 
from aidrin.structured_data_metrics.conditional_demo_disp import conditional_demographic_disparity
from aidrin import app
import pandas as pd
import numpy as np 
import matplotlib.pyplot as plt
import os
import json
import time
import io
import base64
import seaborn as sns
import uuid
import logging

##### Time Logging #####

TIMEOUT_DURATION = 60 #seconds

time_log = logging.getLogger('aidrin')
file_upload_time_log = logging.getLogger('aidrin.file_upload')
metric_time_log = logging.getLogger('aidrin.metric')


######## Simple Routes ########

@app.route('/images/<path:filename>')
def serve_image(filename):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, 'images'), filename)

@app.route('/')
def homepage():
    return render_template('homepage.html')

@app.route('/publications', methods=['GET'])
def publications():
    return render_template('publications.html')



######### Uploading, Retrieving, Clearing File Routes ############

@app.route('/upload_file',methods=['GET','POST'])
def upload_file():
    
    file_upload_time_log.info("File upload initiated")
    uploaded_file_path = None

    if request.method == 'POST':
        file = request.files['file']
        
        if file:
            #create name and add to folder
            displayName= file.filename
            filename = f"{uuid.uuid4().hex}_{file.filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            print(f"Saving file to {file_path}")
            #save file to server
            file.save(file_path)
            #store the file path in the session
            session['uploaded_file_name'] = displayName
            session['uploaded_file_path'] = file_path
            session['uploaded_file_type'] = request.form.get('fileTypeSelector')
            
            return redirect(url_for('upload_file'))
    
    uploaded_file_name = session.get('uploaded_file_name')
    uploaded_file_path = session.get('uploaded_file_path')
    file_type = session.get('uploaded_file_type')
    
    file_upload_time_log.info("File Uploaded. Type: %s",file_type)
    
    return render_template('upload_file.html', 
                                   uploaded_file_path=uploaded_file_path,
                                   uploaded_file_name=uploaded_file_name,
                                   file_type=file_type)

@app.route('/retrieve_uploaded_file', methods=['GET'])
def retrieve_uploaded_file():
    uploaded_file_path = session.get('uploaded_file_path')
    
    if uploaded_file_path:
        # Ensure the file exists at the given path
        if os.path.exists(uploaded_file_path):
            return send_file(uploaded_file_path, as_attachment=True)
        else:
            return jsonify({"error": "File not found"}), 404
    else:
        return jsonify({"error": "No file uploaded yet"}), 404

@app.route('/clear', methods=['GET','POST'])
def clear_file():
    #remove file path/name
    file_path = session.pop('uploaded_file_path', None)
    file_name = session.pop('uploaded_file_name', None)
    if file_path and os.path.exists(file_path):
        os.remove(file_path)  # Delete the uploaded file from the server
    return redirect(url_for('upload_file'))  # Redirect back to the homepage to reset the form
    

######## Metric Page Routes ###########

@app.route('/dataQuality', methods=['GET', 'POST'])
def dataQuality():
    start_time = time.time()
    final_dict = {}
    
    file, uploaded_file_path, uploaded_file_name = read_file()

    if request.method == 'POST':
        #check for parameters
        #Completeness
        if request.form.get('completeness') == "yes":          
            compl_dict = completeness(file)
            compl_dict['Description'] = 'Indicate the proportion of available data for each feature, with values closer to 1 indicating high completeness, and values near 0 indicating low completeness. If the visualization is empty, it means that all features are complete.'
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
            
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time} seconds")

        return store_result('dataQuality',final_dict)
    
    return get_result_or_default('dataQuality',uploaded_file_path,uploaded_file_name)
   
@app.route('/fairness', methods=['GET', 'POST'])
def fairness():
    start_time = time.time()
    final_dict={}

    file, uploaded_file_path, uploaded_file_name = read_file()

    if request.method == 'POST':
        #check for parameters
        #Representation Rate
        if request.form.get('representation rate') == "yes" and request.form.get('features for representation rate') != None:
            print("Running Representation Rate anaylsis")
            #convert the string values a list
            rep_dict = {}
            list_of_cols = [item.strip() for item in request.form.get('features for representation rate').split(',')]
            rep_dict['Probability ratios'] = calculate_representation_rate(file,list_of_cols)       
            rep_dict['Representation Rate Visualization'] = create_representation_rate_vis(file,list_of_cols)
            rep_dict['Description'] = "Represent probability ratios that quantify the relative representation of different categories within the sensitive features, highlighting differences in representation rates between various groups. Higher values imply overrepresentation relative to another"
            final_dict['Representation Rate'] = rep_dict
        #statistical rate
        if request.form.get('statistical rate') == "yes" and request.form.get('features for statistical rate') != None and request.form.get('target for statistical rate') != None:
            try:
                y_true = request.form.get('target for statistical rate')
                sensitive_attribute_column = request.form.get('features for statistical rate')

                print("Inputs:", y_true, sensitive_attribute_column)
                # This function never completes?
                sr_dict = calculate_statistical_rates(file, y_true, sensitive_attribute_column)

                sr_dict['Description'] = (
                    'The graph illustrates the statistical rates of various classes across different sensitive attributes. '
                    'Each group in the graph represents a specific sensitive attribute, and within each group, each bar corresponds '
                    'to a class, with the height indicating the proportion of that sensitive attribute within that particular class'
                )
                final_dict["Statistical Rate"] = sr_dict
                print("Statistical Rate analysis complete")

            except Exception as e:
                print("Error during Statistical Rate analysis:", e)
        #conditional demographic disparity
        if request.form.get('conditional demographic disparity') == 'yes':
            print("Running Conditional demograpic disparity anaylsis")
            cdd_dict = {}
            target = request.form.get('target for conditional demographic disparity')
            sensitive = request.form.get('sensitive for conditional demographic disparity')
            accepted_value = request.form.get('target value for conditional demographic disparity')
            cdd_dict = conditional_demographic_disparity(file[target].to_list(),file[sensitive].to_list(),accepted_value)
            cdd_dict['Description'] = 'The conditional demographic disparity metric evaluates the distribution of outcomes categorized as positive and negative across various sensitive groups. The user specifies which outcome category is considered "positive" for the analysis, with all other outcome categories classified as "negative". The metric calculates the proportion of outcomes classified as "positive" and "negative" within each sensitive group. A resulting disparity value of True indicates that within a specific sensitive group, the proportion of outcomes classified as "negative" exceeds the proportion classified as "positive". This metric provides insights into potential disparities in outcome distribution across sensitive groups based on the user-defined positive outcome criterion.'                 
            final_dict['Conditional Demographic Disparity'] = cdd_dict

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time} seconds")

        return store_result('fairness',final_dict)
    
    return get_result_or_default('fairness',uploaded_file_path,uploaded_file_name)

@app.route('/correlationAnalysis', methods=['GET', 'POST'])
def correlationAnalysis():
    start_time = time.time()
    final_dict = {}

    file, uploaded_file_path, uploaded_file_name = read_file()

    if request.method == 'POST':
        #check for parameters
        #correlations
        if request.form.get('compare real to dataset') == 'yes':
            comp_dict = compare_rep_rates(rep_dict['Probability ratios'],rrr_dict["Probability ratios"])
            comp_dict["Description"] = "The stacked bar graph visually compares the proportions of specific sensitive attributes within both the real-world population and the given dataset. Each stack in the graph represents the combined ratio of these attributes, allowing for an immediate comparison of their distribution between the observed dataset and the broader demographic context"
            final_dict['Representation Rate Comparison with Real World'] = comp_dict

        if request.form.get('correlations') == 'yes':
            columns = request.form.getlist('all features for data transformation')
            corr_dict = calc_correlations(file,columns)
            #catch potential errors
            if 'Message' in corr_dict:
                print("Correlation analysis failed:", corr_dict['Message'])
                final_dict['Error'] = corr_dict['Message']
            else:
                
                final_dict['Correlations Analysis Categorical'] = corr_dict['Correlations Analysis Categorical']
                final_dict['Correlations Analysis Numerical'] = corr_dict['Correlations Analysis Numerical']

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time} seconds")
    
        return store_result('correlationAnalysis',final_dict)

    return get_result_or_default('correlationAnalysis',uploaded_file_path,uploaded_file_name)

@app.route('/featureRelevance', methods=['GET', 'POST'])
def featureRelevance():
    start_time = time.time()
    final_dict = {}

    file, uploaded_file_path, uploaded_file_name = read_file()

    if request.method == 'POST':
        #check for parameters
        #feature relevancy
        if request.form.get("feature relevancy") == "yes":
           # Get raw input from form and sanitize
            raw_cat_cols = request.form.get("categorical features for feature relevancy", "")
            raw_num_cols = request.form.get("numerical features for feature relevancy", "")

            # Clean each list by removing empty strings and whitespace-only entries
            cat_cols = [col.strip() for col in raw_cat_cols.split(",") if col.strip()]
            num_cols = [col.strip() for col in raw_num_cols.split(",") if col.strip()]

            print(cat_cols)
            print(num_cols)

            target = request.form.get("target for feature relevance")
            
            try:
                print("Calling data_cleaning with:", cat_cols, num_cols, target)
                if target in cat_cols or target in num_cols:
                    print("Error: Target is same as feature")
                    return jsonify({"trigger": "correlationError"}), 200
                df = data_cleaning(file, cat_cols, num_cols, target)
                print("Data cleaning returned df with shape:", df.shape if df is not None else "None")
            except Exception as e:
                print("Error occurred during data cleaning:", e)
                df = None

            
            
            # Generate Pearson correlation
            correlations = pearson_correlation(df, df.columns.difference([target]), target)
            #don't let the user check the same target and feature
            if correlations is None:
                print("Error: Correlations is None")
                return jsonify({"trigger": "correlationError"}), 200
            
            f_plot = plot_features(correlations,target)
            f_dict = {}
            
            f_dict['Pearson Correlation to Target'] = correlations
            f_dict['Feature Relevance Visualization'] = f_plot
            f_dict['Description'] = "With minimum data cleaning (drop missing values, onehot encode categorical features, labelencode target feature), the Pearson correlation coefficient is calculated for each feature against the target variable. A value of 1 indicates a perfect positive correlation, while a value of -1 indicates a perfect negative correlation."
            final_dict['Feature Relevance'] = f_dict
            
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"Execution time: {execution_time} seconds")
        
        return store_result('featureRelevance',final_dict)
    
    return get_result_or_default('featureRelevance',uploaded_file_path,uploaded_file_name)
                
@app.route('/classImbalance', methods=['GET', 'POST'])
def classImbalance():
    start_time = time.time()
    final_dict = {}
    
    file, uploaded_file_path, uploaded_file_name = read_file()

    if request.method == 'POST':
        #check for parameters
        if request.form.get("class imbalance") == "yes":
            ci_dict = {}
            classes = request.form.get("features for class imbalance")
            ci_dict['Class Imbalance Visualization'] = class_distribution_plot(file,classes)
            ci_dict['Description'] = "The chart displays the distribution of classes within the specified feature, providing a visual representation of the relative proportions of each class."
            ci_dict['Imbalance degree'] = calc_imbalance_degree(file,classes,dist_metric="EU")#By default the distance metric is euclidean distance
            final_dict['Class Imbalance'] = ci_dict
            
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time} seconds")
        
        return store_result('classImbalance',final_dict)
    
    return get_result_or_default('classImbalance',uploaded_file_path,uploaded_file_name)
    
@app.route('/privacyPreservation', methods=['GET', 'POST'])
def privacyPreservation():
    start_time = time.time()
    final_dict = {}

    file, uploaded_file_path, uploaded_file_name = read_file()

    if request.method == 'POST':
        #check for parameters
        #differential privacy
        if request.form.get("differential privacy") == "yes":
            
            feature_to_add_noise = request.form.get("numerical features to add noise").split(",")
            epsilon = request.form.get("privacy budget")
            if epsilon is None or epsilon == "":
                epsilon = 0.1  # Assign a default value for epsilon

            noisy_stat = return_noisy_stats(file, feature_to_add_noise, float(epsilon))
            final_dict['DP Statistics'] = noisy_stat
            
            
        #single attribute risk scores using markov model
        if request.form.get("single attribute risk score") == "yes":
            id_feature = request.form.get("id feature to measure single attribute risk score")
            eval_features = request.form.getlist("quasi identifiers to measure single attribute risk score")
            print("Eval Features:",eval_features)
            final_dict["Single attribute risk scoring"] = generate_single_attribute_MM_risk_scores(file,id_feature,eval_features)
        
        #multpiple attribute risk score using markov model
        if request.form.get("multiple attribute risk score") == "yes":
            id_feature = request.form.get("id feature to measure multiple attribute risk score")
            eval_features = request.form.getlist("quasi identifiers to measure multiple attribute risk score")
            final_dict["Multiple attribute risk scoring"] = generate_multiple_attribute_MM_risk_scores(file,id_feature,eval_features)

        # k-Anonymity
        if request.form.get("k-anonymity") == "yes":
            k_qis = request.form.getlist("quasi identifiers for k-anonymity")
            final_dict["k-Anonymity"] = compute_k_anonymity(file, k_qis)

        # l-Diversity
        if request.form.get("l-diversity") == "yes":
            l_qis = request.form.getlist("quasi identifiers for l-diversity")
            l_sensitive = request.form.get("sensitive attribute for l-diversity")
            final_dict["l-Diversity"] = compute_l_diversity(file, l_qis, l_sensitive)

        # t-Closeness
        if request.form.get("t-closeness") == "yes":
            t_qis = request.form.getlist("quasi identifiers for t-closeness")
            t_sensitive = request.form.get("sensitive attribute for t-closeness")
            final_dict["t-Closeness"] = compute_t_closeness(file, t_qis, t_sensitive)

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time} seconds")
        #print("Final Dict Privacy:", final_dict)      
        return store_result('privacyPreservation',final_dict)
    
    return get_result_or_default('privacyPreservation',uploaded_file_path,uploaded_file_name)

@app.route('/FAIR', methods=['GET', 'POST'])
def FAIR():
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
            if not file.filename.endswith('.json'):
                 return jsonify({"error": "Invalid file format. Please upload a JSON file."}), 400
            
            json_data = file.read()
            data_dict = json.loads(json_data.decode('utf-8'))
            if request.form.get("metadata type") == "DCAT":
                # Read and parse the JSON data
                try:
                    data_dict = json.loads(json_data.decode('utf-8'))
                    extracted_json = extract_keys_and_values(data_dict)
                    fair_dict = categorize_metadata(extracted_json, data_dict)
                    result = format_dict_values(fair_dict)
                except json.JSONDecodeError as e:
                    return jsonify({"error": f"Error parsing JSON: {str(e)}"}), 400
            elif request.form.get("metadata type") == "Datacite":
                try:
                    result =  categorize_keys_fair(data_dict)
                except json.JSONDecodeError as e:
                    return jsonify({"error": f"Error parsing JSON: {str(e)}"}), 400
            else:
                return jsonify({"Error:","Unknown metadata type"}),400
            
            return store_result('FAIR',result)
        
        else:
            #check for data from POST request
            results_id = request.args.get('results_id')
            #if present, load data
            if results_id and results_id in current_app.TEMP_RESULTS_CACHE:
                entry = current_app.TEMP_RESULTS_CACHE.pop(results_id)  # Remove data after use
                data = entry['data']
                return jsonify(data)

            end_time = time.time()
            print(f"Execution time: {end_time - start_tiime} seconds")
            # Render the form for a GET request
            return render_template("metricTemplates/upload_meta.html")
            

    except Exception as e:
        return jsonify({"error": str(e)}), 400
    
##### Summary Statistics Routes #####

@app.route('/summary_statistics', methods=['POST'])
def handle_summary_statistics():
    try:
        # Get the uploaded file
        uploaded_file_path = session.get('uploaded_file_path')
        if uploaded_file_path and os.path.exists(uploaded_file_path):
            #if data to be parsed, reroute to GET Request
            return redirect(url_for('get_summary_stastistics'))
        #otherwise no file is uploaded, redirect back to file upload
        else:
            return render_template('upload_file.html')
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
     
@app.route('/summary_statistics',methods=['GET'])
def get_summary_stastistics():
    try:
            df, uploaded_file_path, uploaded_file_name = read_file()
            # Extract summary statistics
            summary_statistics = df.describe().round(2).to_dict()
            
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
    
##### Feature Set Route #####

@app.route('/feature_set', methods=['POST'])
def extract_features():
    try:
        df, uploaded_file_path, uploaded_file_name = read_file()


        # Separate numerical and categorical columns
        numerical_columns = [col for col, dtype in df.dtypes.items() if pd.api.types.is_numeric_dtype(dtype)]
        categorical_columns = [col for col, dtype in df.dtypes.items() if pd.api.types.is_object_dtype(dtype)]
        all_features = numerical_columns + categorical_columns

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
        }

        return jsonify(response_data)

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

##### Functions #####

def read_file():
    
    uploaded_file_path = session.get('uploaded_file_path')
    uploaded_file_name = session.get('uploaded_file_name')
    uploaded_file_type = session.get('uploaded_file_type')

    if not uploaded_file_path and uploaded_file_name:
        return redirect(request.url)
    
    #default result
    readFile = None
    #csv
    if uploaded_file_type==('.csv'):
        readFile = pd.read_csv(uploaded_file_path, index_col=False)
    #npz
    if uploaded_file_type==('.npz'):
        npz_data = np.load(uploaded_file_path,allow_pickle=True)
        readFile = pd.DataFrame({key: npz_data[key] for key in npz_data.files})
    #excel
    if uploaded_file_type==('.xls,.xlsb,.xlsx,.xlsm'):
        readFile = pd.read_excel(uploaded_file_path)

    return readFile, uploaded_file_path, uploaded_file_name


def store_result(metric, final_dict):
        formatted_final_dict = format_dict_values(final_dict)
        #save results
        results_id = uuid.uuid4().hex
        
        # ISSUE: Cache size is RAM dependent, if the cache is too large, it may cause memory issues.
        # POTENTIAL SOLUTION: Use a database (doc.db?) to store results or iteratively parse the results.
        current_app.TEMP_RESULTS_CACHE[results_id] = {
        'data': formatted_final_dict,
        }
        return redirect(url_for(metric, 
                                results_id=results_id, 
                                return_type=request.args.get('returnType')))

def get_result_or_default(metric,uploaded_file_path,uploaded_file_name):
    #check for data from POST request
    results_id = request.args.get('results_id')
    return_type = request.args.get('return_type')
    formatted_final_dict = None
    #if present, load data
    if results_id and results_id in current_app.TEMP_RESULTS_CACHE:
        entry = current_app.TEMP_RESULTS_CACHE.pop(results_id)  # Remove data after use
        formatted_final_dict = entry['data']

    if return_type == 'json' and formatted_final_dict:
        return jsonify(formatted_final_dict)        
    return render_template('metricTemplates/'+metric+'.html',
                        uploaded_file_path=uploaded_file_path, 
                        uploaded_file_name=uploaded_file_name,
                        formatted_final_dict=formatted_final_dict)


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
    # background colors for plots (light and dark mode)
    plot_colors = {
        'light': { 
        'bg': '#FBFBF2',     
        'text': '#212529',
        'curve': 'blue'
        },
        'dark': { 
        'bg': '#495057',
        'text': '#F8F9FA',
        'curve': 'red'
        }
    }
    
    line_graphs = {}
    for column in df.select_dtypes(include='number').columns:
        for theme, colors in plot_colors.items():
            plt.figure(figsize=(6, 6),facecolor=colors['bg'])
            ax = plt.gca()
            ax.set_facecolor(colors['bg'])
            
            # Using seaborn's kdeplot to estimate the distribution
            sns.kdeplot(df[column], bw_adjust=0.5,ax=ax,color=colors['curve'])

            # Set a larger font size for the title
            plt.title(f'Distribution Estimate for {column}', fontsize=14, color=colors['text'])

            # Add labels to the axes
            plt.xlabel('Values', fontsize=12, color=colors['text'])
            plt.ylabel('Density', fontsize=12, color=colors['text'])
            # Set axis color
            ax.tick_params(colors=colors['text'])
            for spine in ax.spines.values():
                spine.set_color(colors['text'])
            # Encode the plot as base64
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png',bbox_inches='tight', pad_inches=0.1)
            img_buffer.seek(0)
            encoded_img = base64.b64encode(img_buffer.read()).decode('utf-8')

            line_graphs[f'{column}_{theme}'] = encoded_img
            plt.close()
            img_buffer.close()

    return line_graphs


# @app.route('/FAIRness', methods=['GET', 'POST'])
# def FAIRness():
#     return cal_FAIRness()

# @app.route('/medical_image_readiness',methods=['GET','POST'])
# def med_img_readiness():
#     final_dict = {}
#     if request.method == 'POST':
#         if "dicom" not in request.files:
#             return jsonify({"error": "No 'dicom' field found in form data"}), 400
        
#         # Get the uploaded file
#         file = request.files['dicom']

#         if file.filename == '':
#             return jsonify({"error": "No selected file"}), 400
        
#         if file.filename.endswith('.dcm'):
#             dicom_data = pydicom.dcmread(file,force=True)

#             final_dict['Message'] = "File uploaded successfully"

#             cnr_data = calculate_cnr_from_dicom(dicom_data)
#             spatial_res_data = calculate_spatial_resolution(dicom_data)
#             metadata_dcm = gather_image_quality_info(dicom_data)
#             artifact = detect_and_visualize_artifacts(dicom_data)
#             combined_dict = {**cnr_data, **spatial_res_data}
#             formatted_combined_dict = format_dict_values(combined_dict)
#             final_dict['Image Readiness Scores'] = formatted_combined_dict
#             final_dict['DCM Image Quality Metadata'] = metadata_dcm
#             final_dict['Artifacts'] = artifact

#             return jsonify(final_dict),200
#     return render_template('medical_image.html')
if __name__ == '__main__':
    app.run(debug=True)
