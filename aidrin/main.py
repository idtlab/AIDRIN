from flask import Flask, request, jsonify, send_file, Response,render_template,send_from_directory,session,redirect,url_for, current_app,  Blueprint
from celery.result import AsyncResult, TimeoutError
from celery import shared_task, Task
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
from aidrin.structured_data_metrics.privacy_measure import generate_single_attribute_MM_risk_scores, generate_multiple_attribute_MM_risk_scores
from aidrin.structured_data_metrics.conditional_demo_disp import conditional_demographic_disparity
from aidrin.structured_data_metrics.summary_statistics import summary_histograms
from aidrin.logging import setup_logging
from aidrin.read_file import read_file
import redis
import logging
import pandas as pd
import numpy as np 
import matplotlib.pyplot as plt
import os
import atexit
import json
import time
import io
import base64
import seaborn as sns
import uuid



##### Setup #####
main = Blueprint('main',__name__) # register main blueprint
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0) # initialize Redis client for result storage
### Logging ###
setup_logging()  #  sets log config
file_upload_time_log = logging.getLogger('file_upload') # file upload related logs
metric_time_log = logging.getLogger('metric') # metric parsing related logs


######## Simple Routes ########

@main.route('/images/<path:filename>')
def serve_image(filename):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, 'images'), filename)

@main.route('/')
def homepage():
    return render_template('homepage.html')

@main.route('/publications', methods=['GET'])
def publications():
    return render_template('publications.html')

# for viewing data logs
@main.route('/view_logs')
def view_logs():
    log_path = os.path.join(os.path.dirname(__file__), 'data', 'logs', 'aidrin.log')

    log_rows = []
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            for line in f:
                parts = line.strip().split(" | ",maxsplit=3)
                if len(parts)==4:
                    timestamp, logger, level, message = parts
                    log_rows.append({
                        "timestamp": timestamp,
                        "logger": logger,
                        "level": level,
                        "message": message
                    })
                else:
                    log_rows.append({
                        "timestamp": "",
                        "logger": "",
                        "level": "",
                        "message": line.strip()
                    })

            return jsonify(log_rows)
    return jsonify({"error": "Log file not found."}), 404
##### Result Polling #####
@main.get("/result/<id>")
def result(id: str):
    result = AsyncResult(id)
    ready = result.ready()
    successful = result.successful() if ready else None

    try:
        value = result.get(timeout=1) if ready else result.result
    except TimeoutError:
        value = {"error": "Task did not return in time"}
    except Exception as e:
        value = {"error": str(e)}

    return {
        "ready": ready,
        "successful": successful,
        "value": value,
    }
######### Uploading, Retrieving, Clearing File Routes ############

@main.route('/upload_file',methods=['GET','POST'])
def upload_file():
    
    
    uploaded_file_path = None

    if request.method == 'POST':
        #Log file processing request
        file_upload_time_log.info("File upload initiated")
        
        file = request.files['file']
        
        if file:
            #create name and add to folder
            displayName= file.filename
            filename = f"{uuid.uuid4().hex}_{file.filename}"
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            print(f"Saving file to {file_path}")
            #save file 
            file.save(file_path)
            #store the file path in the session
            session['uploaded_file_name'] = displayName
            session['uploaded_file_path'] = file_path
            session['uploaded_file_type'] = request.form.get('fileTypeSelector')
            print("fileType POST: %s",request.form.get('fileTypeSelector'))
            return redirect(url_for('upload_file'))
    
    uploaded_file_name = session.get('uploaded_file_name')
    uploaded_file_path = session.get('uploaded_file_path')
    file_type = session.get('uploaded_file_type')
    #log uploaded file
    if uploaded_file_name and uploaded_file_path: 
        file_upload_time_log.info("File Uploaded. Type: %s",file_type)
    
    return render_template('upload_file.html', 
                                   uploaded_file_path=uploaded_file_path,
                                   uploaded_file_name=uploaded_file_name,
                                   file_type=file_type)

@main.route('/retrieve_uploaded_file', methods=['GET'])
def retrieve_uploaded_file():
    file_upload_time_log.info("Retrieving File")

    uploaded_file_path = session.get('uploaded_file_path')
    if uploaded_file_path:
        # Ensure the file exists at the given path
        if os.path.exists(uploaded_file_path):
            file_upload_time_log.info("File Successfully Found")
            return send_file(uploaded_file_path, as_attachment=True)
        else:
            file_upload_time_log.info("File not found in os")
            return jsonify({"error": "File not found in os"}), 404
    else:
        file_upload_time_log.info("No file path found")
        return jsonify({"error": "No file path found"}), 404

@main.route('/clear', methods=['POST'])
def clear_file():
    file_upload_time_log.info("Clearing File")
    #remove file path/name
    file_path = session.pop('uploaded_file_path', None)
    file_name = session.pop('uploaded_file_name', None)
    file_type = session.pop('uploaded_file_type', None)
    if file_path and os.path.exists(file_path):
        os.remove(file_path)  # Delete the file 
        file_upload_time_log.info("File Cleared Succesfully")
    else:
        file_upload_time_log.info("File Clear Failure: No File Found")
    return redirect(url_for('upload_file'))

######## Metric Page Routes ###########

@main.route('/dataQuality', methods=['GET', 'POST'])
def dataQuality():
   
    final_dict = {}
    uploaded_file_path = session.get('uploaded_file_path')
    uploaded_file_name = session.get('uploaded_file_name')
    uploaded_file_type = session.get('uploaded_file_type')

    if request.method == 'POST':
        start_time = time.time()
        metric_time_log.info("Data quality Request Started")
        #check for parameters
        #Completeness
        if request.form.get('completeness') == "yes":  
            start_time_completeness = time.time()  
            result = completeness.delay(uploaded_file_path, uploaded_file_name, uploaded_file_type)    
            compl_dict = result.get()
            compl_dict['Description'] = 'Indicate the proportion of available data for each feature, with values closer to 1 indicating high completeness, and values near 0 indicating low completeness. If the visualization is empty, it means that all features are complete.'
            final_dict['Completeness'] = compl_dict
            metric_time_log.info("Completeness took %.2f seconds",time.time()-start_time_completeness)
        #Outliers    
        if request.form.get('outliers') == 'yes':
            start_time_outliers = time.time()  
            result = outliers.delay(uploaded_file_path, uploaded_file_name, uploaded_file_type)   
            out_dict = result.get()
            out_dict['Description'] = "Outlier scores are calculated for numerical columns using the Interquartile Range (IQR) method, where a score of 1 indicates that all data points in a column are identified as outliers, a score of 0 signifies no outliers are detected"
            final_dict['Outliers'] = out_dict
            metric_time_log.info("Outliers took %.2f seconds",time.time()-start_time_outliers)
        #Duplicity
        if request.form.get('duplicity') == 'yes':
            start_time_duplicity = time.time()  
            result = duplicity.delay(uploaded_file_path, uploaded_file_name, uploaded_file_type)
            dup_dict = result.get()
            dup_dict['Description'] = "A value of 0 indicates no duplicates, and a value closer to 1 signifies a higher proportion of duplicated data points in the dataset"
            final_dict['Duplicity'] = dup_dict 
            metric_time_log.info("Duplicity took %.2f seconds",time.time()-start_time_duplicity)
            
        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(f"Data Quality Execution time: {execution_time:.2f} seconds")

        return store_result('dataQuality',final_dict)
    
    return get_result_or_default('dataQuality',uploaded_file_path,uploaded_file_name)
   
@main.route('/fairness', methods=['GET', 'POST'])
def fairness():
    
    final_dict={}
    uploaded_file_path = session.get('uploaded_file_path')
    uploaded_file_name = session.get('uploaded_file_name')
    uploaded_file_type = session.get('uploaded_file_type')

    file, _, _ = read_file()

    if request.method == 'POST':
        metric_time_log.info("Fairness Request Started")
        start_time = time.time()
        #check for parameters
        #Representation Rate
        if request.form.get('representation rate') == "yes" and request.form.get('features for representation rate') != None:
            start_time_repRate = time.time()
            #convert the string values a list
            rep_dict = {}
            list_of_cols = [item.strip() for item in request.form.get('features for representation rate').split(',')]
            result = calculate_representation_rate.delay(list_of_cols,uploaded_file_path, uploaded_file_name, uploaded_file_type)    
            rep_dict['Probability ratios'] = result.get()
            result = create_representation_rate_vis.delay(list_of_cols,uploaded_file_path, uploaded_file_name, uploaded_file_type)
            rep_dict['Representation Rate Visualization'] = result.get()
            rep_dict['Description'] = "Represent probability ratios that quantify the relative representation of different categories within the sensitive features, highlighting differences in representation rates between various groups. Higher values imply overrepresentation relative to another"
            final_dict['Representation Rate'] = rep_dict
            metric_time_log.info("Representation Rate took %.2f seconds",time.time()-start_time_repRate)
        #statistical rate
        if request.form.get('statistical rate') == "yes" and request.form.get('features for statistical rate') != None and request.form.get('target for statistical rate') != None:
            try:
                start_time_statRate = time.time()
                y_true = request.form.get('target for statistical rate')
                sensitive_attribute_column = request.form.get('features for statistical rate')

                print("Inputs:", y_true, sensitive_attribute_column)
                # This function never completes (loads numpy in which is not supported)?
                result = calculate_statistical_rates.delay(y_true, sensitive_attribute_column, uploaded_file_path, uploaded_file_name, uploaded_file_type)
                sr_dict = result.get()

                sr_dict['Description'] = (
                    'The graph illustrates the statistical rates of various classes across different sensitive attributes. '
                    'Each group in the graph represents a specific sensitive attribute, and within each group, each bar corresponds '
                    'to a class, with the height indicating the proportion of that sensitive attribute within that particular class'
                )
                final_dict["Statistical Rate"] = sr_dict
                metric_time_log.info("Statistical Rate analysis took %.2f seconds",time.time()-start_time_statRate)
            except Exception as e:
                print("Error during Statistical Rate analysis:", e)
        #conditional demographic disparity
        if request.form.get('conditional demographic disparity') == 'yes':
            start_time_condDemoDisp = time.time()
            cdd_dict = {}
            target = request.form.get('target for conditional demographic disparity')
            sensitive = request.form.get('sensitive for conditional demographic disparity')
            accepted_value = request.form.get('target value for conditional demographic disparity')
            print ("Inputs:", file[target].to_list(), file[sensitive].to_list(), accepted_value)
            result = conditional_demographic_disparity.delay(file[target].to_list(), file[sensitive].to_list(), accepted_value)
            cdd_dict = result.get()
            cdd_dict['Description'] = 'The conditional demographic disparity metric evaluates the distribution of outcomes categorized as positive and negative across various sensitive groups. The user specifies which outcome category is considered "positive" for the analysis, with all other outcome categories classified as "negative". The metric calculates the proportion of outcomes classified as "positive" and "negative" within each sensitive group. A resulting disparity value of True indicates that within a specific sensitive group, the proportion of outcomes classified as "negative" exceeds the proportion classified as "positive". This metric provides insights into potential disparities in outcome distribution across sensitive groups based on the user-defined positive outcome criterion.'                 
            final_dict['Conditional Demographic Disparity'] = cdd_dict
            metric_time_log.info("Conditional Demographic Disparity took %.2f seconds",time.time()-start_time_condDemoDisp)
        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(f"Fairness Execution time: {execution_time:.2f} seconds")

        return store_result('fairness',final_dict)
    
    return get_result_or_default('fairness',uploaded_file_path,uploaded_file_name)

@main.route('/correlationAnalysis', methods=['GET', 'POST'])
def correlationAnalysis():
   
    final_dict = {}
    uploaded_file_path = session.get('uploaded_file_path')
    uploaded_file_name = session.get('uploaded_file_name')
    uploaded_file_type = session.get('uploaded_file_type')

    if request.method == 'POST':
        metric_time_log.info("Correlation Analysis Request Started")
        start_time = time.time()
        #check for parameters
        #correlations
        if request.form.get('compare real to dataset') == 'yes':
            start_time_realData = time.time()
            result = compare_rep_rates.delay(rep_dict['Probability ratios'],rrr_dict["Probability ratios"])
            comp_dict = result.get()
            comp_dict["Description"] = "The stacked bar graph visually compares the proportions of specific sensitive attributes within both the real-world population and the given dataset. Each stack in the graph represents the combined ratio of these attributes, allowing for an immediate comparison of their distribution between the observed dataset and the broader demographic context"
            final_dict['Representation Rate Comparison with Real World'] = comp_dict
            metric_time_log.info("Real dataset comparison took %.2f seconds",time.time()-start_time_realData)

        if request.form.get('correlations') == 'yes':
            start_time_correlations = time.time()
            columns = request.form.getlist('all features for data transformation')
            result = calc_correlations.delay(columns, uploaded_file_path, uploaded_file_name,uploaded_file_type)
            corr_dict = result.get()
            #catch potential errors
            if 'Message' in corr_dict:
                print("Correlation analysis failed:", corr_dict['Message'])
                final_dict['Error'] = corr_dict['Message']
            else:
                
                final_dict['Correlations Analysis Categorical'] = corr_dict['Correlations Analysis Categorical']
                final_dict['Correlations Analysis Numerical'] = corr_dict['Correlations Analysis Numerical']
            metric_time_log.info("Correlations took %.2f seconds",time.time()-start_time_correlations)

        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(f"Correlation Analysis Execution time: {execution_time:.2f} seconds")
    
        return store_result('correlationAnalysis',final_dict)

    return get_result_or_default('correlationAnalysis',uploaded_file_path,uploaded_file_name)

@main.route('/featureRelevance', methods=['GET', 'POST'])
def featureRelevance():
    
    final_dict = {}

    uploaded_file_path = session.get('uploaded_file_path')
    uploaded_file_name = session.get('uploaded_file_name')
    uploaded_file_type = session.get('uploaded_file_type')

    if request.method == 'POST':
        metric_time_log.info("Feature Relevance Request Started")
        start_time = time.time()
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
                result = data_cleaning.delay(cat_cols, num_cols, target, uploaded_file_path, uploaded_file_name, uploaded_file_type)
                df_json = result.get() #json serialized
                print("Data cleaning returned df with shape:", pd.DataFrame.from_dict(df_json).shape if df_json is not None else "None")
            except Exception as e:
                print("Error occurred during data cleaning:", e)
                df_json = None

            
            
            # Generate Pearson correlation
            result = pearson_correlation.delay(df_json, target)
            correlations = result.get()
            #don't let the user check the same target and feature
            if correlations is None:
                print("Error: Correlations is None")
                return jsonify({"trigger": "correlationError"}), 200
            result = plot_features.delay(correlations, target)
            f_plot = result.get()
            f_dict = {}
            
            f_dict['Pearson Correlation to Target'] = correlations
            f_dict['Feature Relevance Visualization'] = f_plot
            f_dict['Description'] = "With minimum data cleaning (drop missing values, onehot encode categorical features, labelencode target feature), the Pearson correlation coefficient is calculated for each feature against the target variable. A value of 1 indicates a perfect positive correlation, while a value of -1 indicates a perfect negative correlation."
            final_dict['Feature Relevance'] = f_dict
            
            end_time = time.time()
            execution_time = end_time - start_time
            metric_time_log.info(f"Feature Relevance Execution time: {execution_time:.2f} seconds")
        
        return store_result('featureRelevance',final_dict)
    
    return get_result_or_default('featureRelevance',uploaded_file_path,uploaded_file_name)
                
@main.route('/classImbalance', methods=['GET', 'POST'])
def classImbalance():
    
    final_dict = {}
    
    uploaded_file_path = session.get('uploaded_file_path')
    uploaded_file_name = session.get('uploaded_file_name')
    uploaded_file_type = session.get('uploaded_file_type')

    if request.method == 'POST':
        metric_time_log.info("Class Imbalance Request Started")
        start_time = time.time()
        #check for parameters
        if request.form.get("class imbalance") == "yes":
            ci_dict = {}
            classes = request.form.get("features for class imbalance")
            # known display issue
            result = class_distribution_plot.delay(classes, uploaded_file_path, uploaded_file_name, uploaded_file_type)
            ci_dict['Class Imbalance Visualization'] = result.get()
            ci_dict['Description'] = "The chart displays the distribution of classes within the specified feature, providing a visual representation of the relative proportions of each class."
            result = calc_imbalance_degree.delay(classes, uploaded_file_path, uploaded_file_name, uploaded_file_type, dist_metric="EU")  #By default the distance metric is euclidean distance
            ci_dict['Imbalance degree score'] = result.get()
            final_dict['Class Imbalance'] = ci_dict
            
        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(f"Class Imbalance Execution time: {execution_time:.2f} seconds")
        
        return store_result('classImbalance',final_dict)
    
    return get_result_or_default('classImbalance',uploaded_file_path,uploaded_file_name)
    
@main.route('/privacyPreservation', methods=['GET', 'POST'])
def privacyPreservation():

    final_dict = {}

    uploaded_file_path = session.get('uploaded_file_path')
    uploaded_file_name = session.get('uploaded_file_name')
    uploaded_file_type = session.get('uploaded_file_type')

    if request.method == 'POST':
        metric_time_log.info("Privacy Preservation Request Started")
        start_time = time.time()
        #check for parameters
        #differential privacy
        if request.form.get("differential privacy") == "yes":
            start_time_diffPrivacy = time.time()
            feature_to_add_noise = request.form.get("numerical features to add noise").split(",")
            epsilon = request.form.get("privacy budget")
            if epsilon is None or epsilon == "":
                epsilon = 0.1  # Assign a default value for epsilon

            noisy_stat = return_noisy_stats(feature_to_add_noise, float(epsilon), uploaded_file_path, uploaded_file_name, uploaded_file_type)
            final_dict['DP Statistics'] = noisy_stat
            metric_time_log.info("Differential privacy took %.2f seconds",time.time()-start_time_diffPrivacy)
            
        #single attribute risk scores using markov model
        if request.form.get("single attribute risk score") == "yes":
            start_time_oneAttributeRisk = time.time()
            id_feature = request.form.get("id feature to measure single attribute risk score")
            eval_features = request.form.get("quasi identifiers to measure single attribute risk score").split(",")
            print("Eval Features:",eval_features)
            result = generate_single_attribute_MM_risk_scores.delay(id_feature,eval_features, uploaded_file_path,uploaded_file_name,uploaded_file_type)
            final_dict["Single attribute risk scoring"] = result.get()
            metric_time_log.info("Differential privacy took %2f seconds",time.time()-start_time_oneAttributeRisk)
        #multpiple attribute risk score using markov model
        if request.form.get("multiple attribute risk score") == "yes":
            start_time_multAttributeRisk = time.time()
            id_feature = request.form.get("id feature to measure multiple attribute risk score")
            eval_features = request.form.get("quasi identifiers to measure multiple attribute risk score").split(",")
            result = generate_multiple_attribute_MM_risk_scores.delay(id_feature,eval_features, uploaded_file_path,uploaded_file_name,uploaded_file_type)
            final_dict["Multiple attribute risk scoring"] = result.get()
            metric_time_log.info("Differential privacy took %.2f seconds",time.time()-start_time_multAttributeRisk)
        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(f"Privacy Preservation Execution time: {execution_time:.2f} seconds")
              
        return store_result('privacyPreservation',final_dict)
    
    return get_result_or_default('privacyPreservation',uploaded_file_path,uploaded_file_name)

@main.route('/FAIR', methods=['GET', 'POST'])
def FAIR():
    
    try:
        if request.method == 'POST':
            metric_time_log.info("FAIR Request Started")
            start_tiime = time.time()
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
            metric_time_log.info(f"FAIR Execution time: {end_time - start_tiime} seconds")
            # Render the form for a GET request
            return render_template("metricTemplates/upload_meta.html")
            

    except Exception as e:
        return jsonify({"error": str(e)}), 400
    
##### Summary Statistics Routes #####

@main.route('/summary_statistics', methods=['POST'])
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
     
@main.route('/summary_statistics',methods=['GET'])
def get_summary_stastistics():
    try:
            metric_time_log.info("Summary Statistics Request Started")
            start_time = time.time()
            df, uploaded_file_path, uploaded_file_name = read_file()
            # Extract summary statistics
            summary_statistics = df.describe().round(2).to_dict()
            
            # Calculate probability distributions
            uploaded_file_path = session.get('uploaded_file_path')
            uploaded_file_name = session.get('uploaded_file_name')
            uploaded_file_type = session.get('uploaded_file_type')
            result = summary_histograms.delay(uploaded_file_path, uploaded_file_name, uploaded_file_type)
            histograms = result.get()

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
            end_time=time.time()
            metric_time_log.info(f"Summary Statistics Execution time: {end_time - start_time:.2f} seconds")
            return jsonify(response_data)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    
##### Feature Set Route #####

@main.route('/feature_set', methods=['POST'])
def extract_features():
    try:
        metric_time_log.info("Feature Set Request Started")
        start_time = time.time()

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
        end_time=time.time()
        metric_time_log.info(f"Feature Set Execution time: {end_time - start_time:.2f} seconds")
        return jsonify(response_data)

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

##### Functions #####

# Clears the data log on app exit
def clear_files():
    log_path = os.path.join(os.path.dirname(__file__), 'data', 'logs', 'aidrin.log')
    uploads_path = os.path.join(current_app.root_path, "data", "uploads")
    #clear log
    with open(log_path, 'w') as f:
        f.truncate(0)
    #clear uploads folder
    for filename in os.listdir(uploads_path):
        file_path = os.path.join(uploads_path, filename)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}: {e}")
    file_upload_time_log.info("Files Cleared")
atexit.register(clear_files)    

# Parses the uploaded file into a pandas database 
def read_file():
    file_upload_time_log.info("file parsing intiaited...")

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
    #json
    if uploaded_file_type==('.json'):
        readFile = pd.read_json(uploaded_file_path)
    #hdf
    if uploaded_file_type==('.h5'):
        readFile = pd.read_hdf(uploaded_file_path)
    file_upload_time_log.info("file successfully parsed!")
    return readFile, uploaded_file_path, uploaded_file_name


def store_result(metric, final_dict):
        formatted_final_dict = format_dict_values(final_dict)
        
        #save results
        results_id = uuid.uuid4().hex #unique id
        # Serialize the data as JSON
        redis_client.setex(
            name=f'results:{results_id}',
            time=600,  # expires in 10 minutes
            value=json.dumps(formatted_final_dict)
        )
        return redirect(url_for(metric, 
                                results_id=results_id, 
                                return_type=request.args.get('returnType')))

def get_result_or_default(metric,uploaded_file_path,uploaded_file_name):
    #check for data from POST request
    results_id = request.args.get('results_id')
    return_type = request.args.get('return_type')
    formatted_final_dict = None
    
    #if present, load data from database
    data_json = redis_client.get(f'results:{results_id}')
    
    if data_json is not None:
        formatted_final_dict = json.loads(data_json)
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
    current_app.run(debug=True)
