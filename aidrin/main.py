import json
import logging
import os
import time
import uuid
from werkzeug.utils import secure_filename
import sys
from .custom_metrics.base_dr import BaseDRAgent
import inspect
import importlib
import io
import base64

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import redis
from celery.result import AsyncResult
from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
    make_response
)
from aidrin.file_handling.file_parser import (
    SUPPORTED_FILE_TYPES,
    read_file as read_file_parser,
)
from aidrin.logging import setup_logging
from aidrin.structured_data_metrics.add_noise import return_noisy_stats
from aidrin.structured_data_metrics.class_imbalance import (
    calc_imbalance_degree,
    class_distribution_plot,
)
from aidrin.structured_data_metrics.completeness import completeness
from aidrin.structured_data_metrics.conditional_demo_disp import (
    conditional_demographic_disparity,
)
from aidrin.structured_data_metrics.correlation_score import calc_correlations
from aidrin.structured_data_metrics.duplicity import duplicity
from aidrin.structured_data_metrics.FAIRness_datacite import categorize_keys_fair
from aidrin.structured_data_metrics.FAIRness_dcat import (
    categorize_metadata,
    extract_keys_and_values,
)
from aidrin.structured_data_metrics.feature_relevance import (
    data_cleaning,
    pearson_correlation,
    plot_features,
)
from aidrin.structured_data_metrics.outliers import outliers
from aidrin.structured_data_metrics.privacy_measure import (
    compute_entropy_risk,
    compute_k_anonymity,
    compute_l_diversity,
    compute_t_closeness,
    calculate_single_attribute_risk_score,
    calculate_multiple_attribute_risk_score
)
from aidrin.structured_data_metrics.representation_rate import (
    calculate_representation_rate,
    create_representation_rate_vis,
)
from aidrin.structured_data_metrics.statistical_rate import calculate_statistical_rates

# Setup #####
main = Blueprint("main", __name__)  # register main blueprint
# initialize Redis client for result storage
redis_client = redis.StrictRedis(host="localhost", port=6379, db=0)
# Logging ###
setup_logging()  # sets log config
file_upload_time_log = logging.getLogger("file_upload")  # file upload related logs
metric_time_log = logging.getLogger("metric")  # metric parsing related logs

# Time Logging

TIMEOUT_DURATION = 60  # seconds

time_log = logging.getLogger('aidrin')

# Caching Functions


def get_current_user_id():
    """Get current user ID from session or generate one."""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    return session['user_id']


def generate_metric_cache_key(file_name, metric_type, **params):
    """
    Generate a user-specific cache key for metrics.
    """
    user_id = get_current_user_id()
    cache_parts = [f"user:{user_id}", f"file:{file_name}"]

    if metric_type == "dp":
        features = params.get('features', [])
        epsilon = params.get('epsilon', 0.1)
        cache_parts.append(f"dp:features:{', '.join(sorted(features))}:epsilon:{epsilon}")

    elif metric_type == "single":
        id_feature = params.get('id_feature', '')
        qis = params.get('qis', [])
        cache_parts.append(f"single:id:{id_feature}:qis:{', '.join(sorted(qis))}")

    elif metric_type == "multiple":
        id_feature = params.get('id_feature', '')
        qis = params.get('qis', [])
        cache_parts.append(f"multiple:id:{id_feature}:qis:{', '.join(sorted(qis))}")

    elif metric_type == "kanon":
        qis = params.get('qis', [])
        cache_parts.append(f"kanon:qis:{', '.join(sorted(qis))}")

    elif metric_type == "ldiv":
        qis = params.get('qis', [])
        sensitive = params.get('sensitive', '')
        cache_parts.append(f"ldiv:qis:{', '.join(sorted(qis))}:sensitive:{sensitive}")

    elif metric_type == "tclose":
        qis = params.get('qis', [])
        sensitive = params.get('sensitive', '')
        cache_parts.append(f"tclose:qis:{', '.join(sorted(qis))}:sensitive:{sensitive}")

    elif metric_type == "entropy":
        qis = params.get('qis', [])
        cache_parts.append(f"entropy:qis:{', '.join(sorted(qis))}")

    elif metric_type == "classimbalance":
        classes = params.get('classes', '')
        dist_metric = params.get('dist_metric', 'EU')
        cache_parts.append(f"classimbalance:classes:{classes}:dist_metric:{dist_metric}")

    return "|".join(cache_parts)


def is_metric_cache_valid(cache_entry, max_age_minutes=30):
    """Check if metric cache entry is still valid based on time."""
    current_time = time.time()
    expires_at = cache_entry.get('expires_at', 0)
    is_valid = current_time < expires_at
    print(f"Cache validation - Current time: {current_time}, Expires at: {expires_at}, Is valid: {is_valid}")
    return is_valid


def clear_all_user_cache():
    """Clear ALL cache entries for current user."""
    user_id = get_current_user_id()
    keys_to_remove = []
    for key in current_app.TEMP_RESULTS_CACHE.keys():
        if key.startswith(f"user:{user_id}"):
            keys_to_remove.append(key)

    for key in keys_to_remove:
        current_app.TEMP_RESULTS_CACHE.pop(key, None)

    print(f"User {user_id} ALL cache cleared: Removed {len(keys_to_remove)} entries")
    return len(keys_to_remove)


def cleanup_old_uploaded_files(max_age_hours=24):
    """
    Clean up uploaded files that are older than max_age_hours.
    This prevents accumulation of old files on the server.
    """
    try:
        upload_folder = current_app.config.get('UPLOAD_FOLDER')
        if not upload_folder or not os.path.exists(upload_folder):
            return 0

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        files_removed = 0

        for filename in os.listdir(upload_folder):
            file_path = os.path.join(upload_folder, filename)
            if os.path.isfile(file_path):
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > max_age_seconds:
                    try:
                        os.remove(file_path)
                        files_removed += 1
                        print(f"Cleaned up old file: {filename}")
                    except Exception as e:
                        print(f"Error removing old file {filename}: {e}")

        if files_removed > 0:
            print(f"Cleanup completed: {files_removed} old files removed")

        return files_removed
    except Exception as e:
        print(f"Error during file cleanup: {e}")
        return 0


# Simple Routes


@main.route('/images/<path:filename>')
def serve_image(filename):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, 'images'), filename)


@main.route('/docs/<path:filename>')
def serve_docs(filename):
    """Serve Sphinx documentation files"""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, '..', 'docs'), filename)


@main.route('/docs')
def docs_index():
    """Redirect to main Sphinx documentation index"""
    return redirect('/docs/build/html/index.html')


@main.route('/')
def homepage():
    return render_template('homepage.html')


@main.route('/publications', methods=['GET'])
def publications():
    return render_template('publications.html')


# for viewing data logs
@main.route("/view_logs")
def view_logs():
    log_path = os.path.join(os.path.dirname(__file__), "data", "logs", "aidrin.log")

    log_rows = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            for line in f:
                parts = line.strip().split(" | ", maxsplit=3)
                if len(parts) == 4:
                    timestamp, logger, level, message = parts
                    log_rows.append(
                        {
                            "timestamp": timestamp,
                            "logger": logger,
                            "level": level,
                            "message": message,
                        }
                    )
                else:
                    log_rows.append(
                        {
                            "timestamp": "",
                            "logger": "",
                            "level": "",
                            "message": line.strip(),
                        }
                    )

            return jsonify(log_rows)
    return jsonify({"error": "Log file not found."}), 404


@main.route('/class-imbalance-docs')
def class_imbalance_docs():
    return redirect('/docs/build/html/class_imbalance.html')


@main.route('/privacy-metrics-docs')
def privacy_metrics_docs():
    return redirect('/docs/build/html/privacy_metrics.html')


# Uploading, Retrieving, Clearing File Routes


@main.route('/upload_file', methods=['GET', 'POST'])
def upload_file():

    if request.method == "POST":
        # Log file processing request
        file_upload_time_log.info("File upload initiated")
        file = request.files['file']

        if file:
            # Clear all cache for the user when a new file is uploaded
            cleared_count = clear_all_user_cache()
            print(f"Cache cleared for new file upload: {cleared_count} entries removed")

            # create name and add to folder
            display_name = file.filename
            filename = f"{uuid.uuid4().hex}_{file.filename}"
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            print(f"Saving file to {file_path}")
            # save file to server
            file.save(file_path)
            # store the file path in the session
            session['uploaded_file_name'] = display_name
            session['uploaded_file_path'] = file_path
            session['uploaded_file_type'] = request.form.get('fileTypeSelector')

            return redirect(url_for('upload_file'))

    uploaded_file_name = session.get('uploaded_file_name', '')
    uploaded_file_path = session.get('uploaded_file_path', '')
    file_type = session.get('uploaded_file_type', '')

    file_upload_time_log.info("File Uploaded. Type: %s", file_type)

    return render_template(
        'upload_file.html',
        uploaded_file_path=uploaded_file_path or '',
        uploaded_file_name=uploaded_file_name or '',
        file_type=file_type or '',
        supported_file_types=SUPPORTED_FILE_TYPES,
        file_preview=None,
        current_checked_keys=None
    )


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


@main.route('/clear', methods=['GET', 'POST'])
def clear_file():
    file_upload_time_log.info("Clearing File")
    # remove file path/name
    session.pop("uploaded_file_path", None)
    session.pop("uploaded_file_name", None)
    session.pop("uploaded_file_type", None)
    session.pop("minimize_preview", None)
    session.clear()
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    try:
        for filename in os.listdir(upload_folder):
            file_path = os.path.join(upload_folder, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
    except Exception as e:
        file_upload_time_log.info("File Clear Failure: Unable to clear folder")
        return jsonify({"success": False, "error": str(e)}), 500
    return redirect(url_for("upload_file"))


# Metric Page Routes

@main.route('/dataQuality', methods=['GET', 'POST'])
def dataQuality():
    final_dict = {}
    # get file info
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)

    if request.method == "POST":
        start_time = time.time()
        metric_time_log.info("Data quality Request Started")
        # check for parameters
        # Completeness
        try:
            if request.form.get("completeness") == "yes":
                start_time_completeness = time.time()
                completeness_result = completeness(file_info)
                compl_dict = completeness_result
                compl_dict["Description"] = (
                    "Indicate the proportion of available data for each feature, "
                    "with values closer to 1 indicating high completeness, and values near "
                    "0 indicating low completeness. If the visualization is empty, it means "
                    "that all features are complete."
                )
                final_dict["Completeness"] = compl_dict
                metric_time_log.info(
                    "Completeness took %.2f seconds",
                    time.time() - start_time_completeness,
                )
            # Outliers
            if request.form.get("outliers") == "yes":
                start_time_outliers = time.time()
                outliers_result = outliers(file_info)
                out_dict = outliers_result
                out_dict["Description"] = (
                    "Outlier scores are calculated for numerical columns using the Interquartile"
                    " Range (IQR) method, where a score of 1 indicates that all data points in a "
                    "column are identified as outliers, a score of 0 signifies no outliers are detected"
                )
                final_dict["Outliers"] = out_dict
                metric_time_log.info(
                    "Outliers took %.2f seconds", time.time() - start_time_outliers
                )
            # Duplicity
            if request.form.get("duplicity") == "yes":
                start_time_duplicity = time.time()
                duplicity_result = duplicity(file_info)
                dup_dict = duplicity_result
                dup_dict["Description"] = (
                    "A value of 0 indicates no duplicates, and a value closer to 1 signifies a higher "
                    "proportion of duplicated data points in the dataset"
                )
                final_dict["Duplicity"] = dup_dict
                metric_time_log.info(
                    "Duplicity took %.2f seconds",
                    time.time() - start_time_duplicity,
                )
        except Exception as e:
            metric_time_log.error(f"Error: {e}")
            return jsonify({"error": str(e)}), 200
        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(
            f"Data Quality Execution time: {execution_time:.2f} seconds"
        )

        return store_result("dataQuality", final_dict)

    return get_result_or_default("dataQuality", file_path, file_name)


@main.route('/fairness', methods=['GET', 'POST'])
def fairness():

    final_dict = {}

    file, uploaded_file_path, uploaded_file_name = read_file()

    if request.method == 'POST':
        start_time = time.time()
        # check for parameters
        # Representation Rate
        if (request.form.get('representation rate') == "yes" and
                request.form.get('features for representation rate') is not None):
            print("Running Representation Rate analysis")
            # convert the string values a list
            rep_dict = {}
            list_of_cols = [item.strip() for item in request.form.get('features for representation rate').split(', ')]
            # Create file_info tuple for the representation rate functions
            file_info = (uploaded_file_path, uploaded_file_name, session.get('uploaded_file_type'))
            rep_dict['Probability ratios'] = calculate_representation_rate(list_of_cols, file_info)
            rep_dict['Representation Rate Visualization'] = create_representation_rate_vis(list_of_cols, file_info)
            rep_dict['Description'] = (
                "Represent probability ratios that quantify the relative representation "
                "of different categories within the sensitive features, highlighting "
                "differences in representation rates between various groups. Higher "
                "values imply overrepresentation relative to another"
            )
            final_dict['Representation Rate'] = rep_dict
        # statistical rate
        if (request.form.get('statistical rate') == "yes" and
                request.form.get('features for statistical rate') is not None and
                request.form.get('target for statistical rate') is not None):
            try:
                start_time_statRate = time.time()
                y_true = request.form.get('target for statistical rate')
                sensitive_attribute_column = request.form.get('features for statistical rate')

                print("Inputs:", y_true, sensitive_attribute_column)
                # Create file_info tuple for the calculate_statistical_rates function
                file_info = (uploaded_file_path, uploaded_file_name, session.get('uploaded_file_type'))
                sr_dict = calculate_statistical_rates(y_true, sensitive_attribute_column, file_info)

                sr_dict["Description"] = (
                    "The graph illustrates the statistical rates of various classes across different sensitive attributes. "
                    "Each group in the graph represents a specific sensitive attribute, and within each group, each bar corresponds "
                    "to a class, with the height indicating the proportion of that sensitive attribute within that particular class"
                )
                final_dict["Statistical Rate"] = sr_dict
                metric_time_log.info(
                    "Statistical Rate analysis took %.2f seconds",
                    time.time() - start_time_statRate,
                )
            except Exception as e:
                print("Error during Statistical Rate analysis:", e)

        # conditional demographic disparity
        if request.form.get("conditional demographic disparity") == "yes":
            start_time_condDemoDisp = time.time()
            cdd_dict = {}
            target = request.form.get(
                "target for conditional demographic disparity"
            )
            sensitive = request.form.get(
                "sensitive for conditional demographic disparity"
            )
            accepted_value = request.form.get(
                "target value for conditional demographic disparity"
            )
            cond_demo_disp_result = conditional_demographic_disparity.delay(
                file[target].to_list(), file[sensitive].to_list(), accepted_value
            )
            cdd_dict = cond_demo_disp_result.get()
            cdd_dict["Description"] = (
                'The conditional demographic disparity metric evaluates the distribution '
                'of outcomes categorized as positive and negative across various sensitive groups. '
                'The user specifies which outcome category is considered "positive" for the analysis, '
                'with all other outcome categories classified as "negative". The metric calculates the '
                'proportion of outcomes classified as "positive" and "negative" within each sensitive group.'
                ' A resulting disparity value of True indicates that within a specific sensitive group, '
                'the proportion of outcomes classified as "negative" exceeds the proportion classified as'
                ' "positive". This metric provides insights into potential disparities in outcome distribution '
                'across sensitive groups based on the user-defined positive outcome criterion.'
            )
            final_dict["Conditional Demographic Disparity"] = cdd_dict
            metric_time_log.info(
                "Conditional Demographic Disparity took %.2f seconds",
                time.time() - start_time_condDemoDisp,
            )

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time} seconds")

        return store_result('fairness', final_dict)

    return get_result_or_default('fairness', uploaded_file_path, uploaded_file_name)


@main.route('/correlationAnalysis', methods=['GET', 'POST'])
def correlationAnalysis():

    final_dict = {}

    file, uploaded_file_path, uploaded_file_name = read_file()

    if request.method == "POST":
        metric_time_log.info("Correlation Analysis Request Started")
        start_time = time.time()
        try:
            # check for parameters
            # correlations

            if request.form.get("correlations") == "yes":
                start_time_correlations = time.time()
                columns = request.form.getlist("all features for data transformation")
                # Create file_info tuple for the calc_correlations function
                file_info = (uploaded_file_path, uploaded_file_name, session.get('uploaded_file_type'))
                correlations_result = calc_correlations.delay(columns, file_info)
                corr_dict = correlations_result.get()
                # catch potential errors
                if "Message" in corr_dict:
                    print("Correlation analysis failed:", corr_dict["Message"])
                    final_dict["Error"] = corr_dict["Message"]
                else:
                    final_dict["Correlations Analysis Categorical"] = corr_dict[
                        "Correlations Analysis Categorical"
                    ]
                    final_dict["Correlations Analysis Numerical"] = corr_dict[
                        "Correlations Analysis Numerical"
                    ]
                metric_time_log.info(
                    "Correlations took %.2f seconds",
                    time.time() - start_time_correlations,
                )
        except Exception as e:
            metric_time_log.error(f"Error: {e}")
            return jsonify({"error": str(e)}), 200
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time} seconds")

        return store_result('correlationAnalysis', final_dict)

    return get_result_or_default('correlationAnalysis', uploaded_file_path, uploaded_file_name)


@main.route('/featureRelevance', methods=['GET', 'POST'])
def featureRelevance():

    final_dict = {}

    read_result = read_file()
    # Check if read_file returned a redirect response (error case)
    if hasattr(read_result, 'status_code'):  # It's a Response object
        return read_result
    file, uploaded_file_path, uploaded_file_name = read_result

    if request.method == 'POST':
        start_time = time.time()
        # check for parameters
        # feature relevancy
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
                # Create file_info tuple for the data_cleaning function
                file_info = (uploaded_file_path, uploaded_file_name, session.get('uploaded_file_type'))
                data_cleaning_result = data_cleaning.delay(cat_cols, num_cols, target, file_info)
                df_json = data_cleaning_result.get()  # json serialized
                print("Data cleaning returned df with shape:", (pd.DataFrame.from_dict(df_json).shape if df_json is not None else "None"))
            except Exception as e:
                print("Error occurred during data cleaning:", e)
                df_json = None

            # Generate Pearson correlation
            pearson_corr_result = pearson_correlation.delay(df_json, target)
            correlations = pearson_corr_result.get()
            # don't let the user check the same target and feature
            if correlations is None or len(correlations) == 0:
                print("Error: Correlations is None or empty")
                return jsonify({"trigger": "correlationError"}), 200

            plot_features_result = plot_features.delay(correlations, target)
            f_plot = plot_features_result.get()
            f_dict = {}

            f_dict['Pearson Correlation to Target'] = correlations
            f_dict['Feature Relevance Visualization'] = f_plot
            f_dict['Description'] = (
                "With minimum data cleaning (drop missing values, onehot encode "
                "categorical features, labelencode target feature), the Pearson "
                "correlation coefficient is calculated for each feature against the "
                "target variable. A value of 1 indicates a perfect positive "
                "correlation, while a value of -1 indicates a perfect negative "
                "correlation."
            )
            final_dict['Feature Relevance'] = f_dict

            end_time = time.time()
            execution_time = end_time - start_time
            print(f"Execution time: {execution_time} seconds")

        return store_result('featureRelevance', final_dict)

    return get_result_or_default('featureRelevance', uploaded_file_path, uploaded_file_name)


@main.route('/classImbalance', methods=['GET', 'POST'])
def classImbalance():

    final_dict = {}

    file, uploaded_file_path, uploaded_file_name = read_file()

    if request.method == 'POST':
        start_time = time.time()
        # check for parameters
        if request.form.get("class imbalance") == "yes":
            classes = request.form.get("features for class imbalance")
            dist_metric = request.form.get("distance metric for class imbalance", "EU")

            print("Class Imbalance - Form data:", dict(request.form))
            print("Class Imbalance - Form keys:", list(request.form.keys()))
            print("Class Imbalance - Processing class imbalance request")
            print("Class Imbalance - Selected feature:", classes)
            print("Class Imbalance - Selected distance metric:", dist_metric)

            # Generate cache key for class imbalance
            cache_key = generate_metric_cache_key(
                uploaded_file_name,
                "classimbalance",
                classes=classes,
                dist_metric=dist_metric
            )

            print(f"Class Imbalance - Generated cache key: {cache_key}")
            print(f"Class Imbalance - Current cache keys: {list(current_app.TEMP_RESULTS_CACHE.keys())}")

            # Check if this calculation has been cached
            if cache_key in current_app.TEMP_RESULTS_CACHE:
                print(f"Class Imbalance - Cache HIT for key: {cache_key}")
                cached_entry = current_app.TEMP_RESULTS_CACHE[cache_key]
                print(f"Class Imbalance - Cached entry: {cached_entry}")
                if is_metric_cache_valid(cached_entry):
                    print("Class Imbalance - Cache is VALID, using cached result")
                    final_dict['Class Imbalance'] = cached_entry['data']
                    # Reset expiration time when using cached result
                    current_app.TEMP_RESULTS_CACHE[cache_key] = {
                        'data': cached_entry['data'],
                        'timestamp': time.time(),
                        'expires_at': time.time() + (30 * 60)
                    }
                    print(f"Using cached Class Imbalance for key: {cache_key} (expiration reset)")
                else:
                    print("Class Imbalance - Cache is EXPIRED, recalculating")
                    current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
                    ci_dict = {}

                    try:
                        # Generate visualization
                        ci_dict['Class Imbalance Visualization'] = class_distribution_plot(file, classes)
                        ci_dict['Description'] = (
                            "The chart displays the distribution of classes within the "
                            "specified feature, providing a visual representation of the "
                            "relative proportions of each class."
                        )

                        # Calculate imbalance degree
                        imbalance_result = calc_imbalance_degree(file, classes, dist_metric=dist_metric)

                        # Check if there was an error in imbalance calculation
                        if 'Error' in imbalance_result:
                            ci_dict['Error'] = imbalance_result['Error']
                            ci_dict['ErrorType'] = imbalance_result.get('ErrorType', 'Processing Error')
                            ci_dict['Class Imbalance Visualization'] = ""
                            ci_dict['Description'] = f"Error: {imbalance_result['Error']}"
                        else:
                            ci_dict['Imbalance degree'] = imbalance_result

                        final_dict['Class Imbalance'] = ci_dict
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': ci_dict,
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60)
                        }
                        print(f"Cached Class Imbalance for key: {cache_key}")

                    except Exception as e:
                        error_msg = str(e)
                        print(f"Class Imbalance - Error: {error_msg}")
                        ci_dict['Error'] = error_msg
                        ci_dict['ErrorType'] = 'Processing Error'
                        ci_dict['Class Imbalance Visualization'] = ""
                        ci_dict['Description'] = f"Error: {error_msg}"
                        final_dict['Class Imbalance'] = ci_dict
            else:
                print(f"Class Imbalance - Cache MISS for key: {cache_key}")
                ci_dict = {}

                try:
                    # Generate visualization
                    ci_dict['Class Imbalance Visualization'] = class_distribution_plot(file, classes)
                    ci_dict['Description'] = (
                        "The chart displays the distribution of classes within the "
                        "specified feature, providing a visual representation of the "
                        "relative proportions of each class."
                    )
                    # Calculate imbalance degree
                    imbalance_result = calc_imbalance_degree(file, classes, dist_metric=dist_metric)

                    # Check if there was an error in imbalance calculation
                    if 'Error' in imbalance_result:
                        ci_dict['Error'] = imbalance_result['Error']
                        ci_dict['ErrorType'] = imbalance_result.get('ErrorType', 'Processing Error')
                        ci_dict['Class Imbalance Visualization'] = ""
                        ci_dict['Description'] = f"Error: {imbalance_result['Error']}"
                    else:
                        ci_dict['Imbalance degree'] = imbalance_result

                    final_dict['Class Imbalance'] = ci_dict
                    current_app.TEMP_RESULTS_CACHE[cache_key] = {
                        'data': ci_dict,
                        'timestamp': time.time(),
                        'expires_at': time.time() + (30 * 60)
                    }
                    print(f"Cached Class Imbalance for key: {cache_key}")

                except Exception as e:
                    error_msg = str(e)
                    print(f"Class Imbalance - Error: {error_msg}")
                    ci_dict['Error'] = error_msg
                    ci_dict['ErrorType'] = 'Processing Error'
                    ci_dict['Class Imbalance Visualization'] = ""
                    ci_dict['Description'] = f"Error: {error_msg}"
                    final_dict['Class Imbalance'] = ci_dict

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time} seconds")

        return store_result('classImbalance', final_dict)

    return get_result_or_default('classImbalance', uploaded_file_path, uploaded_file_name)


@main.route('/privacyPreservation', methods=['GET', 'POST'])
def privacyPreservation():
    final_dict = {}

    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)
    file = read_file_parser(file_info)

    if request.method == "POST":
        start_time = time.time()
        metric_time_log.info("Privacy Preservation Request Started")
        # check for parameters
        # differential privacy
        if request.form.get("differential privacy") == "yes":

            # Get numerical features and validate
            numerical_features_raw = request.form.get("numerical features to add noise")

            # Edge case 1: No features selected
            if not numerical_features_raw or numerical_features_raw.strip() == "":
                final_dict['DP Statistics'] = {
                    "Error": "No numerical features selected for differential privacy.",
                    "DP Statistics Visualization": "",
                    "Graph interpretation": "No visualization available - no features selected.",
                    "Mean of feature (before noise)": "N/A",
                    "Variance of feature (before noise)": "N/A",
                    "Mean of feature (after noise)": "N/A",
                    "Variance of feature (after noise)": "N/A",
                    "Noisy file saved": "Failed - No features selected"
                }
            else:
                # Edge case 2: Check if features contain valid data after splitting
                feature_to_add_noise = [f.strip() for f in numerical_features_raw.split(",") if f.strip()]

                if not feature_to_add_noise:
                    final_dict['DP Statistics'] = {
                        "Error": "Invalid numerical features selected.",
                        "DP Statistics Visualization": "",
                        "Graph interpretation": "No visualization available - invalid features.",
                        "Mean of feature (before noise)": "N/A",
                        "Variance of feature (before noise)": "N/A",
                        "Mean of feature (after noise)": "N/A",
                        "Variance of feature (after noise)": "N/A",
                        "Noisy file saved": "Failed - Invalid features"
                    }
                else:
                    # Edge case 3: Validate epsilon value
                    epsilon_raw = request.form.get("privacy budget")
                    epsilon = 0.1  # Default value

                    if epsilon_raw and epsilon_raw.strip() != "":
                        try:
                            epsilon = float(epsilon_raw)
                            if epsilon <= 0:
                                final_dict['DP Statistics'] = {
                                    "Error": "Invalid epsilon value. Epsilon must be greater than 0.",
                                    "DP Statistics Visualization": "",
                                    "Graph interpretation": "No visualization available due to invalid parameters.",
                                    "Mean of feature (before noise)": "N/A",
                                    "Variance of feature (before noise)": "N/A",
                                    "Mean of feature (after noise)": "N/A",
                                    "Variance of feature (after noise)": "N/A",
                                    "Noisy file saved": "Failed - Invalid parameters"
                                }
                            else:
                                # All validations passed, proceed with processing
                                process_differential_privacy(file_name, feature_to_add_noise, epsilon, file, final_dict, current_app)
                        except ValueError:
                            final_dict['DP Statistics'] = {
                                "Error": "Invalid epsilon value format.",
                                "DP Statistics Visualization": "",
                                "Graph interpretation": "No visualization available due to invalid parameters.",
                                "Mean of feature (before noise)": "N/A",
                                "Variance of feature (before noise)": "N/A",
                                "Mean of feature (after noise)": "N/A",
                                "Variance of feature (after noise)": "N/A",
                                "Noisy file saved": "Failed - Invalid parameters"
                            }
                    else:
                        # Use default epsilon value
                        process_differential_privacy(file_name, feature_to_add_noise, epsilon, file, final_dict, current_app)

        # single attribute risk scores using markov model (ASYNC)
        if request.form.get("single attribute risk score") == "yes":
            id_feature = request.form.get("id feature to measure single attribute risk score")
            eval_features = request.form.getlist("quasi identifiers to measure single attribute risk score")

            print("Privacy - Single Attribute Risk Score - ID Feature:", id_feature)
            print("Privacy - Single Attribute Risk Score - Eval Features:", eval_features)

            # Validate that user has selected quasi-identifiers
            if not eval_features or (len(eval_features) == 1 and eval_features[0] == ''):
                final_dict["Single attribute risk scoring"] = {
                    "Error": "No quasi-identifiers selected for single attribute risk scoring.",
                    "Single attribute risk scoring Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                    "ErrorType": "Selection Error"
                }
            else:
                # Generate cache key for single attribute risk scoring
                cache_key = generate_metric_cache_key(
                    file_name,
                    "single",
                    id_feature=id_feature,
                    qis=eval_features
                )

                print(f"Privacy - Single Attribute Risk Score Generated cache key: {cache_key}")

                # Check if this calculation has been cached
                if cache_key in current_app.TEMP_RESULTS_CACHE:
                    print(f"Privacy - Single Attribute Risk Score Cache HIT for key: {cache_key}")
                    cached_entry = current_app.TEMP_RESULTS_CACHE[cache_key]
                    if is_metric_cache_valid(cached_entry):
                        print("Privacy - Single Attribute Risk Score Cache is VALID, using cached result")
                        final_dict["Single attribute risk scoring"] = cached_entry['data']
                        # Reset expiration time when using cached result
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': cached_entry['data'],
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60)
                        }
                        print(f"Using cached Single attribute risk scoring for key: {cache_key} (expiration reset)")
                    else:
                        print("Privacy - Single Attribute Risk Score Cache is EXPIRED, starting new task")
                        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
                        try:
                            # Convert DataFrame to JSON for async processing
                            df_json = file.to_json()
                            # Start async task
                            task = calculate_single_attribute_risk_score.delay(df_json, id_feature, eval_features)
                            final_dict["Single attribute risk scoring"] = {
                                "task_id": task.id,
                                "status": "processing",
                                "message": "Single attribute risk scoring is being processed asynchronously. Please check back later.",
                                "is_async": True,
                                "cache_key": cache_key
                            }
                            current_app.TEMP_RESULTS_CACHE[cache_key] = {
                                'data': final_dict["Single attribute risk scoring"],
                                'timestamp': time.time(),
                                'expires_at': time.time() + (30 * 60),
                                'task_id': task.id
                            }
                            print(f"Started new Celery task for Single attribute risk scoring: {task.id}")
                        except Exception as e:
                            error_message = str(e)
                            if "Dataset is empty" in error_message:
                                error_response = {
                                    "Error": "Dataset is empty. Please upload a dataset with data.",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to empty dataset.",
                                    "ErrorType": "Data Error"
                                }
                            elif "No valid quasi-identifiers" in error_message:
                                error_response = {
                                    "Error": "No valid quasi-identifiers provided for single attribute risk scoring.",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to invalid quasi-identifiers.",
                                    "ErrorType": "Selection Error"
                                }
                            elif "not found in dataset" in error_message:
                                error_response = {
                                    "Error": f"Selected columns not found in dataset: {error_message}",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to missing columns.",
                                    "ErrorType": "Data Error"
                                }
                            elif "must contain unique values" in error_message:
                                error_response = {
                                    "Error": "One or more quasi-identifiers have only one unique value.",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to non-unique ID values.",
                                    "ErrorType": "Data Error"
                                }
                            elif "appear to be numerical" in error_message:
                                error_response = {
                                    "Error": "Selected quasi-identifiers appear to be numerical with too many unique values.",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to unsuitable column types.",
                                    "ErrorType": "Data Error"
                                }
                            elif "no data remains" in error_message:
                                error_response = {
                                    "Error": "After removing missing values, no data remains.",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to insufficient data.",
                                    "ErrorType": "Data Error"
                                }
                            elif "More than 50% of data was removed" in error_message:
                                error_response = {
                                    "Error": "More than 50% of data was removed due to missing values.",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to poor data quality.",
                                    "ErrorType": "Data Quality Error"
                                }
                            elif "has only one unique value" in error_message:
                                error_response = {
                                    "Error": "One or more quasi-identifiers have only one unique value.",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to insufficient column variation.",
                                    "ErrorType": "Data Error"
                                }
                            elif "already a perfect identifier" in error_message:
                                error_response = {
                                    "Error": "One or more quasi-identifiers are already perfect identifiers.",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to perfect identification.",
                                    "ErrorType": "Data Error"
                                }
                            elif "causing division by zero" in error_message:
                                error_response = {
                                    "Error": "Unexpected data structure causing division by zero.",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to data structure issues.",
                                    "ErrorType": "Processing Error"
                                }
                            elif "task timed out" in error_message:
                                error_response = {
                                    "Error": "Single Attribute Risk task timed out. The dataset may be too large or complex.",
                                    "ErrorType": "Timeout Error"
                                }
                            else:
                                error_response = {
                                    "Error": f"Processing error: {error_message}",
                                    "Single attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to processing error.",
                                    "ErrorType": "Processing Error"
                                }

                            final_dict["Single attribute risk scoring"] = error_response
                            print(f"Error in Single attribute risk scoring: {error_message}")
                else:
                    print(f"Privacy - Single Attribute Risk Score Cache MISS for key: {cache_key}")
                    try:
                        # Convert DataFrame to JSON for async processing
                        df_json = file.to_json()
                        # Start async task
                        task = calculate_single_attribute_risk_score.delay(df_json, id_feature, eval_features)
                        final_dict["Single attribute risk scoring"] = {
                            "task_id": task.id,
                            "status": "processing",
                            "message": "Single attribute risk scoring is being processed asynchronously. Please check back later.",
                            "is_async": True,
                            "cache_key": cache_key
                        }
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': final_dict["Single attribute risk scoring"],
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60),
                            'task_id': task.id
                        }
                        print(f"Started new Celery task for Single attribute risk scoring: {task.id}")
                    except Exception as e:
                        error_message = str(e)
                        if "Dataset is empty" in error_message:
                            error_response = {
                                "Error": "Dataset is empty. Please upload a dataset with data.",
                                "Description": "The uploaded dataset contains no data rows.",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to empty dataset.",
                                "ErrorType": "Data Error"
                            }
                        elif "No valid quasi-identifiers" in error_message:
                            error_response = {
                                "Error": "No valid quasi-identifiers provided for single attribute risk scoring.",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to invalid quasi-identifiers.",
                                "ErrorType": "Selection Error"
                            }
                        elif "not found in dataset" in error_message:
                            error_response = {
                                "Error": f"Selected columns not found in dataset: {error_message}",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to missing columns.",
                                "ErrorType": "Data Error"
                            }
                        elif "must contain unique values" in error_message:
                            error_response = {
                                "Error": "One or more quasi-identifiers have only one unique value.",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to non-unique ID values.",
                                "ErrorType": "Data Error"
                            }
                        elif "appear to be numerical" in error_message:
                            error_response = {
                                "Error": "Selected quasi-identifiers appear to be numerical with too many unique values.",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to unsuitable column types.",
                                "ErrorType": "Data Error"
                            }
                        elif "no data remains" in error_message:
                            error_response = {
                                "Error": "After removing missing values, no data remains.",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to insufficient data.",
                                "ErrorType": "Data Error"
                            }
                        elif "More than 50% of data was removed" in error_message:
                            error_response = {
                                "Error": "More than 50% of data was removed due to missing values.",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to poor data quality.",
                                "ErrorType": "Data Quality Error"
                            }
                        elif "has only one unique value" in error_message:
                            error_response = {
                                "Error": "One or more quasi-identifiers have only one unique value.",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to insufficient column variation.",
                                "ErrorType": "Data Error"
                            }
                        elif "already a perfect identifier" in error_message:
                            error_response = {
                                "Error": "One or more quasi-identifiers are already perfect identifiers.",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to perfect identification.",
                                "ErrorType": "Data Error"
                            }
                        elif "causing division by zero" in error_message:
                            error_response = {
                                "Error": "Unexpected data structure causing division by zero.",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to data structure issues.",
                                "ErrorType": "Processing Error"
                            }
                        elif "task timed out" in error_message:
                            error_response = {
                                "Error": "Single Attribute Risk task timed out. The dataset may be too large or complex.",
                                "ErrorType": "Timeout Error"
                            }
                        else:
                            error_response = {
                                "Error": f"Processing error: {error_message}",
                                "Single attribute risk scoring Visualization": "",
                                "Graph interpretation": "No visualization available due to processing error.",
                                "ErrorType": "Processing Error"
                            }

                        final_dict["Single attribute risk scoring"] = error_response
                        print(f"Error in Single attribute risk scoring: {error_message}")

        # multiple attribute risk score using markov model (ASYNC)
        if request.form.get("multiple attribute risk score") == "yes":
            id_feature = request.form.get("id feature to measure multiple attribute risk score")
            eval_features = request.form.getlist("quasi identifiers to measure multiple attribute risk score")

            print("Privacy - Multiple Attribute Risk Score - ID Feature:", id_feature)
            print("Privacy - Multiple Attribute Risk Score - Eval Features:", eval_features)

            # Validate that user has selected quasi-identifiers
            if not eval_features or (len(eval_features) == 1 and eval_features[0] == ''):
                final_dict["Multiple attribute risk scoring"] = {
                    "Error": "No quasi-identifiers selected for multiple attribute risk scoring.",
                    "Multiple attribute risk scoring Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                    "ErrorType": "Selection Error"
                }
            else:
                # Validate that ID feature is selected
                if not id_feature or id_feature.strip() == '':
                    final_dict["Multiple attribute risk scoring"] = {
                        "Error": "No ID feature selected for multiple attribute risk scoring.",
                        "Multiple attribute risk scoring Visualization": "",
                        "Graph interpretation": "No visualization available - no ID feature selected.",
                        "ErrorType": "Selection Error"
                    }
                else:
                    # Generate cache key for multiple attribute risk scoring
                    cache_key = generate_metric_cache_key(
                        file_name,
                        "multiple",
                        id_feature=id_feature,
                        qis=eval_features
                    )

                    print(f"Privacy - Multiple Attribute Risk Score Generated cache key: {cache_key}")

                    # Check if this calculation has been cached
                    if cache_key in current_app.TEMP_RESULTS_CACHE:
                        print(f"Privacy - Multiple Attribute Risk Score Cache HIT for key: {cache_key}")
                        cached_entry = current_app.TEMP_RESULTS_CACHE[cache_key]
                        if is_metric_cache_valid(cached_entry):
                            print("Privacy - Multiple Attribute Risk Score Cache is VALID, using cached result")
                            final_dict["Multiple attribute risk scoring"] = cached_entry['data']
                            # Reset expiration time when using cached result
                            current_app.TEMP_RESULTS_CACHE[cache_key] = {
                                'data': cached_entry['data'],
                                'timestamp': time.time(),
                                'expires_at': time.time() + (30 * 60)
                            }
                            print(f"Using cached Multiple attribute risk scoring for key: {cache_key} (expiration reset)")
                        else:
                            print("Privacy - Multiple Attribute Risk Score Cache is EXPIRED, starting new task")
                            current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
                            try:
                                # Convert DataFrame to JSON for async processing
                                df_json = file.to_json()
                                # Start async task
                                task = calculate_multiple_attribute_risk_score.delay(df_json, id_feature, eval_features)
                                final_dict["Multiple attribute risk scoring"] = {
                                    "task_id": task.id,
                                    "status": "processing",
                                    "message": "Multiple attribute risk scoring is being processed asynchronously. Please check back later.",
                                    "is_async": True,
                                    "cache_key": cache_key
                                }
                                current_app.TEMP_RESULTS_CACHE[cache_key] = {
                                    'data': final_dict["Multiple attribute risk scoring"],
                                    'timestamp': time.time(),
                                    'expires_at': time.time() + (30 * 60),
                                    'task_id': task.id
                                }
                                print(f"Started new Celery task for Multiple attribute risk scoring: {task.id}")
                            except Exception as e:
                                error_message = str(e)
                                if "Dataset is empty" in error_message:
                                    error_response = {
                                        "Error": "Dataset is empty. Please upload a dataset with data.",
                                        "Description": "The uploaded dataset contains no data rows.",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to empty dataset.",
                                        "ErrorType": "Data Error"
                                    }
                                elif "No valid quasi-identifiers" in error_message:
                                    error_response = {
                                        "Error": "No valid quasi-identifiers provided for multiple attribute risk scoring.",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to invalid quasi-identifiers.",
                                        "ErrorType": "Selection Error"
                                    }
                                elif "not found in dataset" in error_message:
                                    error_response = {
                                        "Error": f"Selected columns not found in dataset: {error_message}",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to missing columns.",
                                        "ErrorType": "Data Error"
                                    }
                                elif "must contain unique values" in error_message:
                                    error_response = {
                                        "Error": "One or more quasi-identifiers have only one unique value.",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to non-unique ID values.",
                                        "ErrorType": "Data Error"
                                    }
                                elif "appear to be numerical" in error_message:
                                    error_response = {
                                        "Error": "Selected quasi-identifiers appear to be numerical with too many unique values.",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to unsuitable column types.",
                                        "ErrorType": "Data Error"
                                    }
                                elif "no data remains" in error_message:
                                    error_response = {
                                        "Error": "After removing missing values, no data remains.",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to insufficient data.",
                                        "ErrorType": "Data Error"
                                    }
                                elif "More than 50% of data was removed" in error_message:
                                    error_response = {
                                        "Error": "More than 50% of data was removed due to missing values.",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to poor data quality.",
                                        "ErrorType": "Data Quality Error"
                                    }
                                elif "has only one unique value" in error_message:
                                    error_response = {
                                        "Error": "One or more quasi-identifiers have only one unique value.",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to insufficient column variation.",
                                        "ErrorType": "Data Error"
                                    }
                                elif "already a perfect identifier" in error_message:
                                    error_response = {
                                        "Error": "One or more quasi-identifiers are already perfect identifiers.",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to perfect identification.",
                                        "ErrorType": "Data Error"
                                    }
                                elif "causing division by zero" in error_message:
                                    error_response = {
                                        "Error": "Unexpected data structure causing division by zero.",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to data structure issues.",
                                        "ErrorType": "Processing Error"
                                    }
                                elif "task timed out" in error_message:
                                    error_response = {
                                        "Error": "Multiple Attribute Risk task timed out. The dataset may be too large or complex.",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to timeout.",
                                        "ErrorType": "Timeout Error"
                                    }
                                else:
                                    error_response = {
                                        "Error": f"Processing error: {error_message}",
                                        "Multiple attribute risk scoring Visualization": "",
                                        "Graph interpretation": "No visualization available due to processing error.",
                                        "ErrorType": "Processing Error"
                                    }

                                final_dict["Multiple attribute risk scoring"] = error_response
                                print(f"Error in Multiple attribute risk scoring: {error_message}")
                    else:
                        print(f"Privacy - Multiple Attribute Risk Score Cache MISS for key: {cache_key}")
                        try:
                            # Convert DataFrame to JSON for async processing
                            df_json = file.to_json()
                            # Start async task
                            task = calculate_multiple_attribute_risk_score.delay(df_json, id_feature, eval_features)
                            final_dict["Multiple attribute risk scoring"] = {
                                "task_id": task.id,
                                "status": "processing",
                                "message": "Multiple attribute risk scoring is being processed asynchronously. Please check back later.",
                                "is_async": True,
                                "cache_key": cache_key
                            }
                            current_app.TEMP_RESULTS_CACHE[cache_key] = {
                                'data': final_dict["Multiple attribute risk scoring"],
                                'timestamp': time.time(),
                                'expires_at': time.time() + (30 * 60),
                                'task_id': task.id
                            }
                            print(f"Started new Celery task for Multiple attribute risk scoring: {task.id}")
                        except Exception as e:
                            error_message = str(e)
                            if "Dataset is empty" in error_message:
                                error_response = {
                                    "Error": "Dataset is empty. Please upload a dataset with data.",
                                    "Description": "The uploaded dataset contains no data rows.",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to empty dataset.",
                                    "ErrorType": "Data Error"
                                }
                            elif "No valid quasi-identifiers" in error_message:
                                error_response = {
                                    "Error": "No valid quasi-identifiers provided for multiple attribute risk scoring.",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to invalid quasi-identifiers.",
                                    "ErrorType": "Selection Error"
                                }
                            elif "not found in dataset" in error_message:
                                error_response = {
                                    "Error": f"Selected columns not found in dataset: {error_message}",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to missing columns.",
                                    "ErrorType": "Data Error"
                                }
                            elif "must contain unique values" in error_message:
                                error_response = {
                                    "Error": "One or more quasi-identifiers have only one unique value.",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to non-unique ID values.",
                                    "ErrorType": "Data Error"
                                }
                            elif "appear to be numerical" in error_message:
                                error_response = {
                                    "Error": "Selected quasi-identifiers appear to be numerical with too many unique values.",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to unsuitable column types.",
                                    "ErrorType": "Data Error"
                                }
                            elif "no data remains" in error_message:
                                error_response = {
                                    "Error": "After removing missing values, no data remains.",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to insufficient data.",
                                    "ErrorType": "Data Error"
                                }
                            elif "More than 50% of data was removed" in error_message:
                                error_response = {
                                    "Error": "More than 50% of data was removed due to missing values.",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to poor data quality.",
                                    "ErrorType": "Data Quality Error"
                                }
                            elif "has only one unique value" in error_message:
                                error_response = {
                                    "Error": "One or more quasi-identifiers have only one unique value.",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to insufficient column variation.",
                                    "ErrorType": "Data Error"
                                }
                            elif "already a perfect identifier" in error_message:
                                error_response = {
                                    "Error": "One or more quasi-identifiers are already perfect identifiers.",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to perfect identification.",
                                    "ErrorType": "Data Error"
                                }
                            elif "causing division by zero" in error_message:
                                error_response = {
                                    "Error": "Unexpected data structure causing division by zero.",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to data structure issues.",
                                    "ErrorType": "Processing Error"
                                }
                            elif "task timed out" in error_message:
                                error_response = {
                                    "Error": "Multiple Attribute Risk task timed out. The dataset may be too large or complex.",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to timeout.",
                                    "ErrorType": "Timeout Error"
                                }
                            else:
                                error_response = {
                                    "Error": f"Processing error: {error_message}",
                                    "Multiple attribute risk scoring Visualization": "",
                                    "Graph interpretation": "No visualization available due to processing error.",
                                    "ErrorType": "Processing Error"
                                }

                            final_dict["Multiple attribute risk scoring"] = error_response
                            print(f"Error in Multiple attribute risk scoring: {error_message}")

        # k-Anonymity
        if request.form.get("k-anonymity") == "yes":
            k_qis = request.form.getlist("quasi identifiers for k-anonymity")

            # Validate that user has selected quasi-identifiers
            if not k_qis or (len(k_qis) == 1 and k_qis[0] == ''):
                final_dict["k-Anonymity"] = {
                    "Error": "No quasi-identifiers selected for k-anonymity calculation.",
                    "k-Anonymity Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected."
                }
            else:
                # Generate cache key for k-anonymity
                cache_key = generate_metric_cache_key(
                    file_name,
                    "kanon",
                    qis=k_qis
                )

                print(f"Privacy - k-Anonymity Generated cache key: {cache_key}")

                # Check if this calculation has been cached
                if cache_key in current_app.TEMP_RESULTS_CACHE:
                    print(f"Privacy - k-Anonymity Cache HIT for key: {cache_key}")
                    cached_entry = current_app.TEMP_RESULTS_CACHE[cache_key]
                    if is_metric_cache_valid(cached_entry):
                        print("Privacy - k-Anonymity Cache is VALID, using cached result")
                        final_dict["k-Anonymity"] = cached_entry['data']
                        # Reset expiration time when using cached result
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': cached_entry['data'],
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60)
                        }
                        print(f"Using cached k-Anonymity for key: {cache_key} (expiration reset)")
                    else:
                        print("Privacy - k-Anonymity Cache is EXPIRED, recalculating")
                        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
                        try:
                            result = compute_k_anonymity(k_qis, file)
                            final_dict["k-Anonymity"] = result
                            current_app.TEMP_RESULTS_CACHE[cache_key] = {
                                'data': result,
                                'timestamp': time.time(),
                                'expires_at': time.time() + (30 * 60)
                            }
                            print(f"Cached k-Anonymity for key: {cache_key}")
                        except Exception as e:
                            error_message = str(e)
                            if "Input DataFrame is empty" in error_message:
                                error_response = {
                                    "Error": "The uploaded dataset contains no data rows.",
                                    "k-Anonymity Visualization": "",
                                    "Graph interpretation": "No visualization available due to empty dataset."
                                }
                            elif "not found in the dataset" in error_message:
                                error_response = {
                                    "Error": f"Selected columns not found in dataset: {error_message}",
                                    "k-Anonymity Visualization": "",
                                    "Graph interpretation": "No visualization available due to missing columns."
                                }
                            elif "No data left after dropping rows with missing quasi-identifiers" in error_message:
                                error_response = {
                                    "Error": "After removing missing values, no data remains.",
                                    "k-Anonymity Visualization": "",
                                    "Graph interpretation": "No visualization available due to insufficient data."
                                }
                            elif "K anonymity task timed out" in error_message:
                                error_response = {
                                    "Error": "K-Anonymity task timed out. The dataset may be too large or complex."
                                }
                            else:
                                error_response = {
                                    "Error": f"Processing error: {error_message}",
                                    "k-Anonymity Visualization": "",
                                    "Graph interpretation": "No visualization available due to processing error."
                                }

                            final_dict["k-Anonymity"] = error_response
                            print(f"Error in k-Anonymity: {error_message}")
                else:
                    print(f"Privacy - k-Anonymity Cache MISS for key: {cache_key}")
                    try:
                        result = compute_k_anonymity(k_qis, file)
                        final_dict["k-Anonymity"] = result
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': result,
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60)
                        }
                        print(f"Cached k-Anonymity for key: {cache_key}")
                    except Exception as e:
                        error_message = str(e)
                        if "Input DataFrame is empty" in error_message:
                            error_response = {
                                "Error": "The uploaded dataset contains no data rows.",
                                "k-Anonymity Visualization": "",
                                "Graph interpretation": "No visualization available due to empty dataset."
                            }
                        elif "not found in the dataset" in error_message:
                            error_response = {
                                "Error": f"Selected columns not found in dataset: {error_message}",
                                "k-Anonymity Visualization": "",
                                "Graph interpretation": "No visualization available due to missing columns."
                            }
                        elif "No data left after dropping rows with missing quasi-identifiers" in error_message:
                            error_response = {
                                "Error": "After removing missing values, no data remains.",
                                "k-Anonymity Visualization": "",
                                "Graph interpretation": "No visualization available due to insufficient data."
                            }
                        elif "K anonymity task timed out" in error_message:
                            error_response = {
                                "Error": "K-Anonymity task timed out. The dataset may be too large or complex."
                            }
                        else:
                            error_response = {
                                "Error": f"Processing error: {error_message}",
                                "k-Anonymity Visualization": "",
                                "Graph interpretation": "No visualization available due to processing error."
                            }

                        final_dict["k-Anonymity"] = error_response
                        print(f"Error in k-Anonymity: {error_message}")

        # l-Diversity
        if request.form.get("l-diversity") == "yes":
            l_qis = request.form.getlist("quasi identifiers for l-diversity")
            l_sensitive = request.form.get("sensitive attribute for l-diversity")

            # Validate that user has selected quasi-identifiers
            if not l_qis or (len(l_qis) == 1 and l_qis[0] == ''):
                final_dict["l-Diversity"] = {
                    "Error": "No quasi-identifiers selected for l-diversity calculation.",
                    "l-Diversity Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected."
                }
            elif not l_sensitive or l_sensitive.strip() == '':
                final_dict["l-Diversity"] = {
                    "Error": "No sensitive attribute selected for l-diversity calculation.",
                    "l-Diversity Visualization": "",
                    "Graph interpretation": "No visualization available - no sensitive attribute selected."
                }
            else:
                # Generate cache key for l-diversity
                cache_key = generate_metric_cache_key(
                    file_name,
                    "ldiv",
                    qis=l_qis,
                    sensitive=l_sensitive
                )

                print(f"Privacy - l-Diversity Generated cache key: {cache_key}")

                # Check if this calculation has been cached
                if cache_key in current_app.TEMP_RESULTS_CACHE:
                    print(f"Privacy - l-Diversity Cache HIT for key: {cache_key}")
                    cached_entry = current_app.TEMP_RESULTS_CACHE[cache_key]
                    if is_metric_cache_valid(cached_entry):
                        print("Privacy - l-Diversity Cache is VALID, using cached result")
                        final_dict["l-Diversity"] = cached_entry['data']
                        # Reset expiration time when using cached result
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': cached_entry['data'],
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60)
                        }
                        print(f"Using cached l-Diversity for key: {cache_key} (expiration reset)")
                    else:
                        print("Privacy - l-Diversity Cache is EXPIRED, recalculating")
                        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
                        try:
                            result = compute_l_diversity(l_qis, l_sensitive, file)
                            final_dict["l-Diversity"] = result
                            current_app.TEMP_RESULTS_CACHE[cache_key] = {
                                'data': result,
                                'timestamp': time.time(),
                                'expires_at': time.time() + (30 * 60)
                            }
                            print(f"Cached l-Diversity for key: {cache_key}")
                        except Exception as e:
                            error_message = str(e)
                            if "Input DataFrame is empty" in error_message:
                                error_response = {
                                    "Error": "The uploaded dataset contains no data rows.",
                                    "l-Diversity Visualization": "",
                                    "Graph interpretation": "No visualization available due to empty dataset."
                                }
                            elif "not found in the dataset" in error_message:
                                error_response = {
                                    "Error": f"Selected columns not found in dataset: {error_message}",
                                    "l-Diversity Visualization": "",
                                    "Graph interpretation": "No visualization available due to missing columns."
                                }
                            elif "No data left after dropping rows with missing quasi-identifiers or sensitive values" in error_message:
                                error_response = {
                                    "Error": "After removing missing values, no data remains.",
                                    "l-Diversity Visualization": "",
                                    "Graph interpretation": "No visualization available due to insufficient data."
                                }
                            elif "L Diversity task timed out" in error_message:
                                error_response = {
                                    "Error": "L-Diversity task timed out. The dataset may be too large or complex."
                                }
                            else:
                                error_response = {
                                    "Error": f"Processing error: {error_message}",
                                    "l-Diversity Visualization": "",
                                    "Graph interpretation": "No visualization available due to processing error."
                                }

                            final_dict["l-Diversity"] = error_response
                            print(f"Error in l-Diversity: {error_message}")
                else:
                    print(f"Privacy - l-Diversity Cache MISS for key: {cache_key}")
                    try:
                        result = compute_l_diversity(l_qis, l_sensitive, file)
                        final_dict["l-Diversity"] = result
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': result,
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60)
                        }
                        print(f"Cached l-Diversity for key: {cache_key}")
                    except Exception as e:
                        error_message = str(e)
                        if "Input DataFrame is empty" in error_message:
                            error_response = {
                                "Error": "The uploaded dataset contains no data rows.",
                                "l-Diversity Visualization": "",
                                "Graph interpretation": "No visualization available due to empty dataset."
                            }
                        elif "not found in the dataset" in error_message:
                            error_response = {
                                "Error": f"Selected columns not found in dataset: {error_message}",
                                "l-Diversity Visualization": "",
                                "Graph interpretation": "No visualization available due to missing columns."
                            }
                        elif "No data left after dropping rows with missing quasi-identifiers or sensitive values" in error_message:
                            error_response = {
                                "Error": "After removing missing values, no data remains.",
                                "l-Diversity Visualization": "",
                                "Graph interpretation": "No visualization available due to insufficient data."
                            }
                        elif "L Diversity task timed out" in error_message:
                            error_response = {
                                "Error": "L-Diversity task timed out. The dataset may be too large or complex."
                            }
                        else:
                            error_response = {
                                "Error": f"Processing error: {error_message}",
                                "l-Diversity Visualization": "",
                                "Graph interpretation": "No visualization available due to processing error."
                            }

                        final_dict["l-Diversity"] = error_response
                        print(f"Error in l-Diversity: {error_message}")

        # t-Closeness
        if request.form.get("t-closeness") == "yes":
            t_qis = request.form.getlist("quasi identifiers for t-closeness")
            t_sensitive = request.form.get("sensitive attribute for t-closeness")

            # Validate that user has selected quasi-identifiers
            if not t_qis or (len(t_qis) == 1 and t_qis[0] == ''):
                final_dict["t-Closeness"] = {
                    "Error": "No quasi-identifiers selected for t-closeness calculation.",
                    "t-Closeness Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected."
                }
            elif not t_sensitive or t_sensitive.strip() == '':
                final_dict["t-Closeness"] = {
                    "Error": "No sensitive attribute selected for t-closeness calculation.",
                    "t-Closeness Visualization": "",
                    "Graph interpretation": "No visualization available - no sensitive attribute selected."
                }
            else:
                # Generate cache key for t-closeness
                cache_key = generate_metric_cache_key(
                    file_name,
                    "tclose",
                    qis=t_qis,
                    sensitive=t_sensitive
                )

                print(f"Privacy - t-Closeness Generated cache key: {cache_key}")

                # Check if this calculation has been cached
                if cache_key in current_app.TEMP_RESULTS_CACHE:
                    print(f"Privacy - t-Closeness Cache HIT for key: {cache_key}")
                    cached_entry = current_app.TEMP_RESULTS_CACHE[cache_key]
                    if is_metric_cache_valid(cached_entry):
                        print("Privacy - t-Closeness Cache is VALID, using cached result")
                        final_dict["t-Closeness"] = cached_entry['data']
                        # Reset expiration time when using cached result
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': cached_entry['data'],
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60)
                        }
                        print(f"Using cached t-Closeness for key: {cache_key} (expiration reset)")
                    else:
                        print("Privacy - t-Closeness Cache is EXPIRED, recalculating")
                        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
                        try:
                            result = compute_t_closeness(t_qis, t_sensitive, file)
                            final_dict["t-Closeness"] = result
                            current_app.TEMP_RESULTS_CACHE[cache_key] = {
                                'data': result,
                                'timestamp': time.time(),
                                'expires_at': time.time() + (30 * 60)
                            }
                            print(f"Cached t-Closeness for key: {cache_key}")
                        except Exception as e:
                            error_message = str(e)
                            if "Input DataFrame is empty" in error_message:
                                error_response = {
                                    "Error": "The uploaded dataset contains no data rows.",
                                    "t-Closeness Visualization": "",
                                    "Graph interpretation": "No visualization available due to empty dataset."
                                }
                            elif "not found in the dataset" in error_message:
                                error_response = {
                                    "Error": f"Selected columns not found in dataset: {error_message}",
                                    "t-Closeness Visualization": "",
                                    "Graph interpretation": "No visualization available due to missing columns."
                                }
                            elif "No data left after dropping rows with missing values" in error_message:
                                error_response = {
                                    "Error": "After removing missing values, no data remains.",
                                    "t-Closeness Visualization": "",
                                    "Graph interpretation": "No visualization available due to insufficient data."
                                }
                            elif "T Closeness task timed out" in error_message:
                                error_response = {
                                    "Error": "T-Closeness task timed out. The dataset may be too large or complex."
                                }
                            else:
                                error_response = {
                                    "Error": f"Processing error: {error_message}",
                                    "t-Closeness Visualization": "",
                                    "Graph interpretation": "No visualization available due to processing error."
                                }

                            final_dict["t-Closeness"] = error_response
                            print(f"Error in t-Closeness: {error_message}")
                else:
                    print(f"Privacy - t-Closeness Cache MISS for key: {cache_key}")
                    try:
                        result = compute_t_closeness(t_qis, t_sensitive, file)
                        final_dict["t-Closeness"] = result
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': result,
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60)
                        }
                        print(f"Cached t-Closeness for key: {cache_key}")
                    except Exception as e:
                        error_message = str(e)
                        if "Input DataFrame is empty" in error_message:
                            error_response = {
                                "Error": "The uploaded dataset contains no data rows.",
                                "t-Closeness Visualization": "",
                                "Graph interpretation": "No visualization available due to empty dataset."
                            }
                        elif "not found in the dataset" in error_message:
                            error_response = {
                                "Error": f"Selected columns not found in dataset: {error_message}",
                                "t-Closeness Visualization": "",
                                "Graph interpretation": "No visualization available due to missing columns."
                            }
                        elif "No data left after dropping rows with missing values" in error_message:
                            error_response = {
                                "Error": "After removing missing values, no data remains.",
                                "t-Closeness Visualization": "",
                                "Graph interpretation": "No visualization available due to insufficient data."
                            }
                        elif "T Closeness task timed out" in error_message:
                            error_response = {
                                "Error": "T-Closeness task timed out. The dataset may be too large or complex."
                            }
                        else:
                            error_response = {
                                "Error": f"Processing error: {error_message}",
                                "t-Closeness Visualization": "",
                                "Graph interpretation": "No visualization available due to processing error."
                            }

                        final_dict["t-Closeness"] = error_response
                        print(f"Error in t-Closeness: {error_message}")

        # Entropy Risk
        if request.form.get("entropy risk") == "yes":
            entropy_qis = request.form.getlist("quasi identifiers for entropy risk")

            # Validate that user has selected quasi-identifiers
            if not entropy_qis or (len(entropy_qis) == 1 and entropy_qis[0] == ''):
                final_dict["Entropy Risk"] = {
                    "Error": "No quasi-identifiers selected for entropy risk calculation.",
                    "Entropy Risk Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected."
                }
            else:
                # Generate cache key for entropy risk
                cache_key = generate_metric_cache_key(
                    file_name,
                    "entropy",
                    qis=entropy_qis
                )

                print(f"Privacy - Entropy Risk Generated cache key: {cache_key}")

                # Check if this calculation has been cached
                if cache_key in current_app.TEMP_RESULTS_CACHE:
                    print(f"Privacy - Entropy Risk Cache HIT for key: {cache_key}")
                    cached_entry = current_app.TEMP_RESULTS_CACHE[cache_key]
                    if is_metric_cache_valid(cached_entry):
                        print("Privacy - Entropy Risk Cache is VALID, using cached result")
                        final_dict["Entropy Risk"] = cached_entry['data']
                        # Reset expiration time when using cached result
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': cached_entry['data'],
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60)
                        }
                        print(f"Using cached Entropy Risk for key: {cache_key} (expiration reset)")
                    else:
                        print("Privacy - Entropy Risk Cache is EXPIRED, recalculating")
                        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
                        try:
                            result = compute_entropy_risk(entropy_qis, file)
                            final_dict["Entropy Risk"] = result
                            current_app.TEMP_RESULTS_CACHE[cache_key] = {
                                'data': result,
                                'timestamp': time.time(),
                                'expires_at': time.time() + (30 * 60)
                            }
                            print(f"Cached Entropy Risk for key: {cache_key}")
                        except Exception as e:
                            error_message = str(e)
                            if "Input DataFrame is empty" in error_message:
                                error_response = {
                                    "Error": "The uploaded dataset contains no data rows.",
                                    "Entropy Risk Visualization": "",
                                    "Graph interpretation": "No visualization available due to empty dataset."
                                }
                            elif "not found in the dataset" in error_message:
                                error_response = {
                                    "Error": f"Selected columns not found in dataset: {error_message}",
                                    "Entropy Risk Visualization": "",
                                    "Graph interpretation": "No visualization available due to missing columns."
                                }
                            elif "No data left after dropping rows with missing values" in error_message:
                                error_response = {
                                    "Error": "After removing missing values, no data remains.",
                                    "Entropy Risk Visualization": "",
                                    "Graph interpretation": "No visualization available due to insufficient data."
                                }
                            elif "Entropy Risk task timed out" in error_message:
                                error_response = {
                                    "Error": "Entropy Risk task timed out. The dataset may be too large or complex."
                                }
                            else:
                                error_response = {
                                    "Error": f"Processing error: {error_message}",
                                    "Entropy Risk Visualization": "",
                                    "Graph interpretation": "No visualization available due to processing error."
                                }

                            final_dict["Entropy Risk"] = error_response
                            print(f"Error in Entropy Risk: {error_message}")
                else:
                    print(f"Privacy - Entropy Risk Cache MISS for key: {cache_key}")
                    try:
                        result = compute_entropy_risk(entropy_qis, file)
                        final_dict["Entropy Risk"] = result
                        current_app.TEMP_RESULTS_CACHE[cache_key] = {
                            'data': result,
                            'timestamp': time.time(),
                            'expires_at': time.time() + (30 * 60)
                        }
                        print(f"Cached Entropy Risk for key: {cache_key}")
                    except Exception as e:
                        error_message = str(e)
                        if "Input DataFrame is empty" in error_message:
                            error_response = {
                                "Error": "The uploaded dataset contains no data rows.",
                                "Entropy Risk Visualization": "",
                                "Graph interpretation": "No visualization available due to empty dataset."
                            }
                        elif "not found in the dataset" in error_message:
                            error_response = {
                                "Error": f"Selected columns not found in dataset: {error_message}",
                                "Entropy Risk Visualization": "",
                                "Graph interpretation": "No visualization available due to missing columns."
                            }
                        elif "No data left after dropping rows with missing values" in error_message:
                            error_response = {
                                "Error": "After removing missing values, no data remains.",
                                "Entropy Risk Visualization": "",
                                "Graph interpretation": "No visualization available due to insufficient data."
                            }
                        elif "Entropy Risk task timed out" in error_message:
                            error_response = {
                                "Error": "Entropy Risk task timed out. The dataset may be too large or complex."
                            }
                        else:
                            error_response = {
                                "Error": f"Processing error: {error_message}",
                                "Entropy Risk Visualization": "",
                                "Graph interpretation": "No visualization available due to processing error."
                            }

                        final_dict["Entropy Risk"] = error_response
                        print(f"Error in Entropy Risk: {error_message}")

        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(
            f"Privacy Preservation Execution time: {execution_time:.2f} seconds"
        )
        return store_result("privacyPreservation", final_dict)

    return get_result_or_default("privacyPreservation", file_path, file_name)

# Helper function to check allowed file extensions


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config["CUSTOM_ALLOWED_EXTENSIONS"]


@main.route('/save_custom_metric', methods=['POST'])
def upload_metric():
    try:
        # Check if a file is included in the request
        if 'custom_dr_file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['custom_dr_file']

        # Check if a file was selected
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Validate file extension
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Only .py files are allowed'}), 400

        # Secure the filename to prevent path traversal attacks
        filename = secure_filename(file.filename)
        base, ext = os.path.splitext(filename)
        filename = f"{base}_{int(time.time())}{ext}"

        # Save the file to the custom_metrics directory
        file_path = os.path.join(current_app.config["CUSTOM_METRICS_FOLDER"], filename)
        file.save(file_path)

        # Store custom metric file info in session
        session['custom_metric_file_path'] = file_path
        session['custom_metric_file_name'] = filename

        return jsonify({'message': 'File uploaded successfully'}), 200

    except Exception as e:
        # Log the error for debugging
        metric_time_log.error(f"Error uploading file: {str(e)}")
        return jsonify({'error': 'An error occurred while uploading the file'}), 500


@main.route('/cancel-custom-metric', methods=['POST'])
def cancel_custom_metric():
    try:
        # Retrieve custom metric file info from session
        custom_metric_file_path = session.get('custom_metric_file_path')

        if not custom_metric_file_path or not os.path.exists(custom_metric_file_path):
            return jsonify({'message': 'No custom metric file to cancel'}), 200

        # Delete the file
        try:
            os.remove(custom_metric_file_path)
            metric_time_log.info(f"Successfully removed custom metric file: {custom_metric_file_path}")
        except Exception as e:
            metric_time_log.error(f"Failed to remove custom metric file {custom_metric_file_path}: {str(e)}")
            return jsonify({'error': f"Failed to remove custom metric file: {str(e)}"}), 500

        # Clear session variables
        session.pop('custom_metric_file_path', None)
        session.pop('custom_metric_file_name', None)

        return jsonify({'message': 'Custom metric file removed successfully'}), 200

    except Exception as e:
        metric_time_log.error(f"Error canceling custom metric: {str(e)}")
        return jsonify({'error': 'An error occurred while canceling the upload'}), 500


@main.route("/customMetrics", methods=["GET", "POST"])
def customMetrics():
    final_dict = {}

    # Retrieve data file info (for dataset)
    data_file_path = session.get("uploaded_file_path")
    data_file_name = session.get("uploaded_file_name")
    data_file_type = session.get("uploaded_file_type")
    file_info = (data_file_path, data_file_name, data_file_type)

    # Retrieve custom metric module info
    custom_metric_file_path = session.get("custom_metric_file_path")
    custom_metric_file_name = session.get("custom_metric_file_name")

    if request.method == "POST":
        metric_time_log.info("Custom Metric Evaluation Request Started")
        start_time = time.time()
        try:

            # Check if custom metric file is provided
            if not custom_metric_file_path or not os.path.exists(custom_metric_file_path):
                return jsonify({"error": "No custom metric file provided"}), 400
            if not custom_metric_file_name.endswith('.py'):
                return jsonify({"error": "Invalid custom metric file type. Only .py files are allowed"}), 400

            # Load dataset from data file
            df = read_file_parser(file_info)  # Assumes read_file is defined elsewhere

            final_dict["Custom Metric Evaluation"] = {}

            # Import the custom metric module
            module_name = custom_metric_file_name[:-3]  # Remove .py extension
            try:
                custom_metric_module = importlib.import_module(f'aidrin.custom_metrics.{module_name}')
            except ImportError as e:
                raise ImportError(f"Could not load module aidrin.custom_metrics.{module_name}: {str(e)}")

            # Find the class that inherits from BaseDRAgent
            custom_metric_class = None
            for name, obj in inspect.getmembers(custom_metric_module, inspect.isclass):
                if issubclass(obj, BaseDRAgent) and obj is not BaseDRAgent:
                    custom_metric_class = obj
                    break

            if custom_metric_class is None:
                return jsonify({"error": f"No class inheriting from BaseDRAgent found in module {module_name}"}), 400

            # Initialize the custom metric class with the dataset
            custom_metric_instance = custom_metric_class(dataset=df)

            # Call the metric method to get results
            metric_results = custom_metric_instance.metric()
            if not isinstance(metric_results, dict):
                return jsonify({"error": f"{custom_metric_class.__name__}.metric() must return a dictionary"}), 400

            # Store the results in the final_dict
            final_dict["Custom Metric Evaluation"] = metric_results

            # Clean up sys.modules to prevent memory leaks
            if f'aidrin.custom_metrics.{module_name}' in sys.modules:
                del sys.modules[f'aidrin.custom_metrics.{module_name}']

            if request.form.get("apply_remedy") == "yes":
                final_dict['Custom Metric Evaluation']['apply_remedy'] = "remedy applied to your dataset"

        except Exception as e:
            metric_time_log.error(f"Error: {str(e)}")
            return jsonify({"error": str(e)}), 200

        finally:
            # Safely remove the custom metric file
            if custom_metric_file_path and os.path.exists(custom_metric_file_path):
                try:
                    os.remove(custom_metric_file_path)
                    metric_time_log.info(f"Successfully removed custom metric file: {custom_metric_file_path}")
                except Exception as e:
                    metric_time_log.error(f"Failed to remove custom metric file {custom_metric_file_path}: {str(e)}")

            # Clear session variables
            session.pop('custom_metric_file_path', None)
            session.pop('custom_metric_file_name', None)

            # Clean up sys.modules to prevent memory leaks
            if module_name and f'aidrin.custom_metrics.{module_name}' in sys.modules:
                del sys.modules[f'aidrin.custom_metrics.{module_name}']

        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(
            f"Custom Metric Evaluation Execution time: {execution_time:.2f} seconds"
        )

        return store_result("customMetrics", final_dict)

    return get_result_or_default("customMetrics", data_file_path, data_file_name)


@main.route('/generate-template', methods=['POST'])
def generate_template():
    try:
        class_name = request.form.get('class_name')
        if not class_name:
            return jsonify({'error': 'No class name provided'}), 400

        # Basic validation
        if not class_name.isidentifier():
            return jsonify({'error': 'Invalid class name'}), 400

        filename = f"{class_name}.py"
        template = f"""from .base_dr import BaseDRAgent
from typing import Any


class {class_name}(BaseDRAgent):
    def __init__(self, dataset: Any, **kwargs):
        # Initialize the parent class with dataset and additional arguments
        super().__init__(dataset, **kwargs)

        # Ensure dataset is initialized
        self.dataset = dataset

    def metric(self) -> dict[str, Any]:
        \"\"\"
        Implement your custom metric logic here.
        Must return a dictionary of results.
        \"\"\"
        # Example implementation:
        return {{
            "metric_results": "metric not defined"
        }}

    def remedy(self) -> dict[str, Any]:
        \"\"\"
        Implement your custom remedy logic here.
        Must return a dictionary with the ai_ready_dataset.
        \"\"\"
        # Example implementation:
        return {{
            "ai_ready_dataset": "remedy not defined"
        }}

"""

        response = make_response(template)
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        response.mimetype = 'text/x-python'
        return response

    except Exception as e:
        metric_time_log.error(f"Error generating template: {str(e)}")
        return jsonify({'error': 'An error occurred while generating the template'}), 500


@main.route('/FAIR', methods=['GET', 'POST'])
def FAIR():
    start_time = time.time()
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
                    result = categorize_keys_fair(data_dict)
                except json.JSONDecodeError as e:
                    return jsonify({"error": f"Error parsing JSON: {str(e)}"}), 400
            else:
                return jsonify({"Error:", "Unknown metadata type"}), 400

            return store_result('FAIR', result)

        else:
            # check for data from POST request
            results_id = request.args.get('results_id')
            # if present, load data
            if results_id and results_id in current_app.TEMP_RESULTS_CACHE:
                entry = current_app.TEMP_RESULTS_CACHE.pop(results_id)  # Remove data after use
                data = entry['data']
                return jsonify(data)

            end_time = time.time()
            print(f"Execution time: {end_time - start_time} seconds")
            # Render the form for a GET request
            return render_template("metricTemplates/upload_meta.html")

    except Exception as e:
        return jsonify({"error": str(e)}), 400


# Summary Statistics Routes

@main.route('/summary_statistics', methods=['POST'])
def handle_summary_statistics():
    try:
        # Get the uploaded file
        uploaded_file_path = session.get('uploaded_file_path')
        if uploaded_file_path and os.path.exists(uploaded_file_path):
            # if data to be parsed, reroute to GET Request
            return redirect(url_for('get_summary_statistics'))
        # otherwise no file is uploaded, redirect back to file upload
        else:
            return render_template('upload_file.html')
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@main.route('/summary_statistics', methods=['GET'])
def get_summary_statistics():
    try:
        df, uploaded_file_path, uploaded_file_name = read_file()
        # Extract summary statistics
        summary_statistics = df.describe().applymap(
            lambda x: f"{x:.2e}" if abs(x) < 0.001 else round(x, 2)
        ).to_dict()

        # Calculate probability distributions
        histograms = summary_histograms(df)

        # Separate numerical and categorical columns
        numerical_columns = [
            col
            for col, dtype in df.dtypes.items()
            if pd.api.types.is_numeric_dtype(dtype)
        ]
        categorical_columns = [
            col
            for col, dtype in df.dtypes.items()
            if pd.api.types.is_object_dtype(dtype)
        ]
        all_features = numerical_columns + categorical_columns

        for v in summary_statistics.values():
            for old_key in v:
                if old_key in ["25%", "50%", "75%"]:
                    new_key = old_key.replace("%", "th percentile")
                    v[new_key] = v.pop(old_key)

        # Count the number of records
        records_count = len(df)

        # count the number of features
        feature_count = len(df.columns)

        response_data = {
            'success': True,
            'message': 'File uploaded successfully',
            'records_count': records_count,
            'features_count': feature_count,
            'categorical_features': list(categorical_columns),
            'numerical_features': list(numerical_columns),
            'all_features': all_features,
            'summary_statistics': summary_statistics,
            'histograms': histograms
        }
        return jsonify(response_data)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# Feature Set Route

@main.route('/check_and_update_task/<task_id>/<metric_name>', methods=['GET'])
def check_task_status(task_id, metric_name):
    """Check the status of an async task and return results if complete."""
    try:
        task_result = AsyncResult(task_id)

        if task_result.ready():
            if task_result.successful():
                result = task_result.get()

                # Store the result in cache for the frontend to retrieve
                cache_key = f"{task_id}_{metric_name}"
                current_app.TEMP_RESULTS_CACHE[cache_key] = {
                    'data': result,
                    'timestamp': time.time()
                }

                # Return a clean response with just what the frontend needs
                return jsonify({
                    'status': 'completed',
                    'result': result  # Return the entire result dictionary
                })
            else:
                error = str(task_result.info) if task_result.info else "Task failed"
                return jsonify({
                    'status': 'failed',
                    'error': error
                }), 500
        else:
            # Task is still running, return progress info if available
            progress_info = task_result.info if isinstance(task_result.info, dict) else {}
            current = progress_info.get('current', 0)
            total = progress_info.get('total', 100)
            status = progress_info.get('status', 'Processing...')

            return jsonify({
                'status': 'processing',
                'progress': {
                    'current': current,
                    'total': total,
                    'status': status
                }
            })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@main.route('/feature_set', methods=['POST'])
def extract_features():
    try:
        df, uploaded_file_path, uploaded_file_name = read_file()

        file_path = session.get("uploaded_file_path")
        file_name = session.get("uploaded_file_name")
        file_type = session.get("uploaded_file_type")
        file_info = (file_path, file_name, file_type)
        df = read_file_parser(file_info)

        # Separate numerical and categorical columns
        numerical_columns = [col for col, dtype in df.dtypes.items() if pd.api.types.is_numeric_dtype(dtype)]
        categorical_columns = [col for col, dtype in df.dtypes.items() if pd.api.types.is_object_dtype(dtype)]
        all_features = numerical_columns + categorical_columns

        # Filter features for Class Imbalance (30 or fewer unique values)
        class_imbalance_features = []
        for col in all_features:
            unique_count = df[col].nunique()
            if unique_count <= 30:
                class_imbalance_features.append(col)

        # Count the number of records
        records_count = len(df)

        # count the number of features
        feature_count = len(df.columns)

        response_data = {
            'success': True,
            'message': 'File uploaded successfully',
            'records_count': records_count,
            'features_count': feature_count,
            'categorical_features': list(categorical_columns),
            'numerical_features': list(numerical_columns),
            'all_features': all_features,
            'class_imbalance_features': class_imbalance_features,
        }

        return jsonify(response_data)

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# Functions

def read_file():

    uploaded_file_path = session.get('uploaded_file_path')
    uploaded_file_name = session.get('uploaded_file_name')
    uploaded_file_type = session.get('uploaded_file_type')

    if not uploaded_file_path and uploaded_file_name:
        return redirect(request.url)

    # Check if the file actually exists
    if uploaded_file_path and not os.path.exists(uploaded_file_path):
        # File doesn't exist, clear the session and redirect
        print(f"File not found: {uploaded_file_path}")
        session.pop('uploaded_file_path', None)
        session.pop('uploaded_file_name', None)
        session.pop('uploaded_file_type', None)
        return redirect(url_for('upload_file'))

    # default result
    readFile = None
    try:
        # csv
        if uploaded_file_type == ('.csv'):
            readFile = pd.read_csv(uploaded_file_path, index_col=False)
        # npz
        elif uploaded_file_type == ('.npz'):
            npz_data = np.load(uploaded_file_path, allow_pickle=True)

            data_dict = {}

            for key in npz_data.files:
                array = npz_data[key]

                # Check dimensionality
                if array.ndim == 1:
                    data_dict[key] = array
                else:
                    # Flatten if it's a 2D array with only 1 column
                    if array.ndim == 2 and array.shape[1] == 1:
                        data_dict[key] = array.flatten()
                    else:
                        # Otherwise, store the whole array as a column of objects (fallback)
                        data_dict[key] = [row for row in array]

            # Now create the DataFrame safely
            readFile = pd.DataFrame(data_dict)
        # excel
        elif uploaded_file_type == ('.xls, .xlsb, .xlsx, .xlsm'):
            readFile = pd.read_excel(uploaded_file_path)
    except Exception as e:
        print(f"Error reading file {uploaded_file_path}: {e}")
        # Clear session on error
        session.pop('uploaded_file_path', None)
        session.pop('uploaded_file_name', None)
        session.pop('uploaded_file_type', None)
        return redirect(url_for('upload_file'))

    return readFile, uploaded_file_path, uploaded_file_name


def manage_cache_size(max_cache_size=100):
    """
    Manage the cache size by removing oldest entries if cache exceeds max size.
    This prevents memory issues from cache growth.
    """
    if len(current_app.TEMP_RESULTS_CACHE) > max_cache_size:
        # Remove oldest entries (first 20% of cache)
        items_to_remove = int(max_cache_size * 0.2)
        keys_to_remove = list(current_app.TEMP_RESULTS_CACHE.keys())[:items_to_remove]
        for key in keys_to_remove:
            current_app.TEMP_RESULTS_CACHE.pop(key, None)
        print(f"Cache cleanup: Removed {len(keys_to_remove)} old entries")


def store_result(metric, final_dict):
    formatted_final_dict = format_dict_values(final_dict)
    # save results
    results_id = uuid.uuid4().hex

    # ISSUE: Cache size is RAM dependent, if the cache is too large, it may cause memory issues.
    # POTENTIAL SOLUTION: Use a database (doc.db?) to store results or iteratively parse the results.
    current_app.TEMP_RESULTS_CACHE[results_id] = {
        'data': formatted_final_dict,
    }
    return redirect(url_for(metric,
                            results_id=results_id,
                            return_type=request.args.get('returnType')))


def get_result_or_default(metric, uploaded_file_path, uploaded_file_name):
    # check for data from POST request
    results_id = request.args.get('results_id')
    return_type = request.args.get('return_type')
    formatted_final_dict = None
    # if present, load data
    if results_id and results_id in current_app.TEMP_RESULTS_CACHE:
        entry = current_app.TEMP_RESULTS_CACHE.pop(results_id)  # Remove data after use
        formatted_final_dict = entry['data']

    if return_type == 'json' and formatted_final_dict:
        return jsonify(formatted_final_dict)
    return render_template(
        'metricTemplates/'+metric+'.html',
        uploaded_file_path=uploaded_file_path,
        uploaded_file_name=uploaded_file_name,
        formatted_final_dict=formatted_final_dict
    )


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
            plt.figure(figsize=(6, 6), facecolor=colors['bg'])
            ax = plt.gca()
            ax.set_facecolor(colors['bg'])

            # Using seaborn's kdeplot to estimate the distribution
            sns.kdeplot(df[column], bw_adjust=0.5, ax=ax, color=colors['curve'])

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
            plt.savefig(img_buffer, format='png', bbox_inches='tight', pad_inches=0.1)
            img_buffer.seek(0)
            encoded_img = base64.b64encode(img_buffer.read()).decode('utf-8')

            line_graphs[f'{column}_{theme}'] = encoded_img
            plt.close()
            img_buffer.close()

    return line_graphs


# @app.route('/FAIRness', methods = ['GET', 'POST'])
# def FAIRness():
#     return cal_FAIRness()

# @app.route('/medical_image_readiness', methods = ['GET', 'POST'])
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
#             dicom_data = pydicom.dcmread(file, force = True)

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

#             return jsonify(final_dict), 200
#     return render_template('medical_image.html')


@main.route('/my_cache', methods=['GET'])
def my_cache():
    """Show cache information for the current user."""
    try:
        user_id = get_current_user_id()
        cache = current_app.TEMP_RESULTS_CACHE
        # Get user-specific cache keys
        user_cache_keys = [key for key in cache.keys() if key.startswith(f"user:{user_id}")]
        # Calculate cache statistics
        total_user_entries = len(user_cache_keys)
        global_cache_size = len(cache)
        user_cache_percentage = round((total_user_entries / global_cache_size * 100) if global_cache_size > 0 else 0, 2)
        cache_info = {
            'user_id': user_id,
            'total_user_entries': total_user_entries,
            'global_cache_size': global_cache_size,
            'user_cache_percentage': user_cache_percentage,
            'user_cache_keys': user_cache_keys
        }
        return render_template('my_cache.html', cache_info=cache_info)
    except Exception as e:
        return render_template('my_cache.html', cache_info=None, error=str(e))


@main.route('/clear_cache', methods=['POST'])
def clear_cache():
    """Clear all cache for the current user."""
    try:
        removed_count = clear_all_user_cache()
        return jsonify({
            'success': True,
            'message': f'Cache cleared successfully! Removed {removed_count} entries.',
            'removed_count': removed_count
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error clearing cache: {str(e)}'
        }), 500


def process_differential_privacy(file_name, feature_to_add_noise, epsilon, file, final_dict, current_app):
    """Helper function to process differential privacy with caching and error handling"""

    # Generate cache key for differential privacy
    cache_key = generate_metric_cache_key(
        file_name,
        "dp",
        features=feature_to_add_noise,
        epsilon=epsilon
    )

    print(f"Privacy - DP Generated cache key: {cache_key}")

    # Check if this calculation has been cached
    if cache_key in current_app.TEMP_RESULTS_CACHE:
        print(f"Privacy - DP Cache HIT for key: {cache_key}")
        cached_entry = current_app.TEMP_RESULTS_CACHE[cache_key]
        if is_metric_cache_valid(cached_entry):
            print("Privacy - DP Cache is VALID, using cached result")
            final_dict['DP Statistics'] = cached_entry['data']
            # Reset expiration time when using cached result
            current_app.TEMP_RESULTS_CACHE[cache_key] = {
                'data': cached_entry['data'],
                'timestamp': time.time(),
                'expires_at': time.time() + (30 * 60)
            }
            print(f"Using cached DP Statistics for key: {cache_key} (expiration reset)")
        else:
            print("Privacy - DP Cache is EXPIRED, recalculating")
            current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
            try:
                noisy_stat = return_noisy_stats(feature_to_add_noise, float(epsilon), file)
                final_dict['DP Statistics'] = noisy_stat
                current_app.TEMP_RESULTS_CACHE[cache_key] = {
                    'data': noisy_stat,
                    'timestamp': time.time(),
                    'expires_at': time.time() + (30 * 60)
                }
                print(f"Cached DP Statistics for key: {cache_key}")
            except Exception as e:
                error_message = str(e)

                if "Epsilon must be greater than 0" in error_message:
                    error_response = {
                        "Error": "Invalid epsilon value. Epsilon must be greater than 0.",
                        "DP Statistics Visualization": "",
                        "Graph interpretation": "No visualization available due to invalid parameters.",
                        "Mean of feature (before noise)": "N/A",
                        "Variance of feature (before noise)": "N/A",
                        "Mean of feature (after noise)": "N/A",
                        "Variance of feature (after noise)": "N/A",
                        "Noisy file saved": "Failed - Invalid parameters"
                    }
                elif "Dataset is empty" in error_message:
                    error_response = {
                        "Error": "Dataset is empty after removing null values or contains no valid data.",
                        "DP Statistics Visualization": "",
                        "Graph interpretation": "No visualization available - insufficient data.",
                        "Mean of feature (before noise)": "N/A",
                        "Variance of feature (before noise)": "N/A",
                        "Mean of feature (after noise)": "N/A",
                        "Variance of feature (after noise)": "N/A",
                        "Noisy file saved": "Failed - No data to process"
                    }
                else:
                    error_response = {
                        "Error": f"Processing error: {error_message}",
                        "DP Statistics Visualization": "",
                        "Graph interpretation": "No visualization available due to processing error.",
                        "Mean of feature (before noise)": "N/A",
                        "Variance of feature (before noise)": "N/A",
                        "Mean of feature (after noise)": "N/A",
                        "Variance of feature (after noise)": "N/A",
                        "Noisy file saved": "Failed - Processing error"
                    }

                final_dict['DP Statistics'] = error_response
                current_app.TEMP_RESULTS_CACHE[cache_key] = {
                    'data': error_response,
                    'timestamp': time.time(),
                    'expires_at': time.time() + (30 * 60)
                }
                print(f"Cached DP Statistics Error for key: {cache_key}")
    else:
        print(f"Privacy - DP Cache MISS for key: {cache_key}")
        try:
            noisy_stat = return_noisy_stats(feature_to_add_noise, float(epsilon), file)
            final_dict['DP Statistics'] = noisy_stat
            current_app.TEMP_RESULTS_CACHE[cache_key] = {
                'data': noisy_stat,
                'timestamp': time.time(),
                'expires_at': time.time() + (30 * 60)
            }
            print(f"Cached DP Statistics for key: {cache_key}")
        except Exception as e:
            error_message = str(e)

            if "Epsilon must be greater than 0" in error_message:
                error_response = {
                    "Error": "Invalid epsilon value. Epsilon must be greater than 0.",
                    "DP Statistics Visualization": "",
                    "Graph interpretation": "No visualization available due to invalid parameters.",
                    "Mean of feature (before noise)": "N/A",
                    "Variance of feature (before noise)": "N/A",
                    "Mean of feature (after noise)": "N/A",
                    "Variance of feature (after noise)": "N/A",
                    "Noisy file saved": "Failed - Invalid parameters"
                }
            elif "Dataset is empty" in error_message:
                error_response = {
                    "Error": "Dataset is empty after removing null values or contains no valid data.",
                    "DP Statistics Visualization": "",
                    "Graph interpretation": "No visualization available - insufficient data.",
                    "Mean of feature (before noise)": "N/A",
                    "Variance of feature (before noise)": "N/A",
                    "Mean of feature (after noise)": "N/A",
                    "Variance of feature (after noise)": "N/A",
                    "Noisy file saved": "Failed - No data to process"
                }
            else:
                error_response = {
                    "Error": f"Processing error: {error_message}",
                    "DP Statistics Visualization": "",
                    "Graph interpretation": "No visualization available due to processing error.",
                    "Mean of feature (before noise)": "N/A",
                    "Variance of feature (before noise)": "N/A",
                    "Mean of feature (after noise)": "N/A",
                    "Variance of feature (after noise)": "N/A",
                    "Noisy file saved": "Failed - Processing error"
                }

            final_dict['DP Statistics'] = error_response
            current_app.TEMP_RESULTS_CACHE[cache_key] = {
                'data': error_response,
                'timestamp': time.time(),
                'expires_at': time.time() + (30 * 60)
            }
            print(f"Cached DP Statistics Error for key: {cache_key}")


if __name__ == '__main__':
    from aidrin import create_app
    app = create_app()
    app.run(debug=True)
