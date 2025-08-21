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

import pandas as pd
import redis
from celery.result import AsyncResult, TimeoutError
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
    filter_file,
    parse_file,
    read_file,
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
    generate_multiple_attribute_MM_risk_scores,
    generate_single_attribute_MM_risk_scores,
)
from aidrin.structured_data_metrics.representation_rate import (
    calculate_representation_rate,
    create_representation_rate_vis,
)
from aidrin.structured_data_metrics.statistical_rate import calculate_statistical_rates
from aidrin.structured_data_metrics.summary_statistics import summary_histograms
# Setup #####
main = Blueprint("main", __name__)  # register main blueprint
# initialize Redis client for result storage
redis_client = redis.StrictRedis(host="localhost", port=6379, db=0)
# Logging ###
setup_logging()  # sets log config
file_upload_time_log = logging.getLogger("file_upload")  # file upload related logs
metric_time_log = logging.getLogger("metric")  # metric parsing related logs


# Simple Routes ########


@main.route("/images/<path:filename>")
def serve_image(filename):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, "images"), filename)


@main.route("/")
def homepage():
    return render_template("homepage.html")


@main.route("/publications", methods=["GET"])
def publications():
    return render_template("publications.html")


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


# Result Polling #####


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


# Uploading, Retrieving, Clearing File Routes ############


@main.route("/upload_file", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        # Log file processing request
        file_upload_time_log.info("File upload initiated")

        file = request.files["file"]

        if file:
            clear_file()
            # create name and add to folder
            displayName = file.filename
            file_name = f"{uuid.uuid4().hex}_{file.filename}"
            file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], file_name)
            file_type = request.form.get("fileTypeSelector")
            print(f"Saving file to {file_path}")
            # save file
            file.save(file_path)
            # store the file path in the session
            session["uploaded_file_name"] = displayName
            session["uploaded_file_path"] = file_path
            session["uploaded_file_type"] = file_type
            print("fileType POST: %s", request.form.get("fileTypeSelector"))

            return redirect(url_for("upload_file"))

    file_name = session.get("uploaded_file_name")
    file_path = session.get("uploaded_file_path")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)
    # handling hierarchical data
    file_preview = None
    current_checked_keys = None
    if file_type == ".json" or file_type == ".h5":
        minimize_preview = request.args.get("minimize_preview") == "true"
        if minimize_preview:
            session["minimize_preview"] = "true"
        if "original_file_path" in session:
            original_file_path = session.get("original_file_path")
            original_file_info = (original_file_path, file_name, file_type)
            file_preview = parse_file(original_file_info)
            current_checked_keys = parse_file(file_info)
        else:
            file_preview = parse_file(file_info)

    file_upload_time_log.info("upload file: %s", session.get("uploaded_file_path"))
    # log uploaded file
    if file_name and file_path:
        file_upload_time_log.info("File Uploaded. Type: %s", file_type)

    return render_template(
        "upload_file.html",
        uploaded_file_path=file_path,
        uploaded_file_name=file_name,
        supported_file_types=SUPPORTED_FILE_TYPES,
        file_type=file_type,
        file_preview=file_preview,
        current_checked_keys=current_checked_keys,
    )


@main.route("/retrieve_uploaded_file", methods=["GET"])
def retrieve_uploaded_file():
    file_upload_time_log.info("Retrieving File")

    uploaded_file_path = session.get("uploaded_file_path")
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


@main.route("/clear", methods=["POST"])
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


# Clear stale file session data before each request


@main.before_app_request
def clear_stale_file_session():
    file_path = session.get("uploaded_file_path")
    if file_path:
        if not os.path.exists(file_path):
            # Only clear session if the file was expected but is missing
            session.clear()


@main.route("/filter_file", methods=["POST"])
def refine_file():
    try:
        kept_keys = request.json.get("keys")  # list

        file_name = session.get("uploaded_file_name")
        file_type = session.get("uploaded_file_type")

        if "original_file_path" not in session:
            # set original file to allow user to change selections
            session["original_file_path"] = session.get("uploaded_file_path")
            file_path = session.get("uploaded_file_path")
            file_info = (file_path, file_name, file_type)
            new_file_path = filter_file(file_info, kept_keys)

            session["uploaded_file_path"] = new_file_path
            file_upload_time_log.info("filter_file: %s", session["uploaded_file_path"])
        else:
            # use original file to keep original groups
            file_path = session.get("original_file_path")
            file_info = (file_path, file_name, file_type)
            new_file_path = filter_file(file_info, kept_keys)

            # remove current filtered file
            uploaded_file = session.get("uploaded_file_path")
            if uploaded_file and os.path.exists(uploaded_file):
                os.remove(uploaded_file)
            # set working path to new path
            session["uploaded_file_path"] = new_file_path
            file_upload_time_log.info("filter_file: %s", session["uploaded_file_path"])
        return jsonify({"success": True})
    except Exception as e:
        file_upload_time_log.info(f"Error: {e}")
        return jsonify({"error": str(e)}), 400


# Metric Page Routes ###########


@main.route("/dataQuality", methods=["GET", "POST"])
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
                completeness_result = completeness.delay(file_info)
                compl_dict = completeness_result.get()
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
                outliers_result = outliers.delay(file_info)
                out_dict = outliers_result.get()
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
                duplicity_result = duplicity.delay(file_info)
                dup_dict = duplicity_result.get()
                dup_dict["Description"] = (
                    "A value of 0 indicates no duplicates, and a value closer to 1 signifies a higher "
                    "proportion of duplicated data points in the dataset"
                )
                final_dict["Duplicity"] = dup_dict
                metric_time_log.info(
                    "Duplicity took %.2f seconds", time.time() - start_time_duplicity
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


@main.route("/fairness", methods=["GET", "POST"])
def fairness():
    final_dict = {}
    # get file info
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)
    file = read_file(file_info)

    if request.method == "POST":
        metric_time_log.info("Fairness Request Started")
        start_time = time.time()
        try:
            # check for parameters
            # Representation Rate
            if (
                request.form.get("representation rate") == "yes"
                and request.form.get("features for representation rate") is not None
            ):
                start_time_repRate = time.time()
                # convert the string values a list
                rep_dict = {}
                list_of_cols = [
                    item.strip()
                    for item in request.form.get(
                        "features for representation rate"
                    ).split(",")
                ]
                rep_rate_result = calculate_representation_rate.delay(
                    list_of_cols, file_info
                )
                rep_dict["Probability ratios"] = rep_rate_result.get()
                rep_rate_vis_result = create_representation_rate_vis.delay(
                    list_of_cols, file_info
                )
                rep_dict["Representation Rate Visualization"] = (
                    rep_rate_vis_result.get()
                )
                rep_dict["Description"] = (
                    "Represent probability ratios that quantify the relative representation of "
                    "different categories within the sensitive features, highlighting differences "
                    "in representation rates between various groups. Higher values imply overrepresentation "
                    "relative to another"
                )
                final_dict["Representation Rate"] = rep_dict
                metric_time_log.info(
                    "Representation Rate took %.2f seconds",
                    time.time() - start_time_repRate,
                )
            # statistical rate
            if (
                request.form.get("statistical rate") == "yes"
                and request.form.get("features for statistical rate") is not None
                and request.form.get("target for statistical rate") is not None
            ):
                try:
                    start_time_statRate = time.time()
                    y_true = request.form.get("target for statistical rate")
                    sensitive_attribute_column = request.form.get(
                        "features for statistical rate"
                    )

                    print("Inputs:", y_true, sensitive_attribute_column)
                    # This function never completes (loads numpy in which is not supported)?
                    stat_rate_result = calculate_statistical_rates.delay(
                        y_true, sensitive_attribute_column, file_info
                    )
                    sr_dict = stat_rate_result.get()

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
                    "The conditional demographic disparity metric evaluates the distribution "
                    "of outcomes categorized as positive and negative across various sensitive groups. "
                    'The user specifies which outcome category is considered "positive" for the analysis, '
                    'with all other outcome categories classified as "negative". The metric calculates the '
                    'proportion of outcomes classified as "positive" and "negative" within each sensitive group.'
                    " A resulting disparity value of True indicates that within a specific sensitive group, "
                    'the proportion of outcomes classified as "negative" exceeds the proportion classified as'
                    ' "positive". This metric provides insights into potential disparities in outcome distribution '
                    "across sensitive groups based on the user-defined positive outcome criterion."
                )
                final_dict["Conditional Demographic Disparity"] = cdd_dict
                metric_time_log.info(
                    "Conditional Demographic Disparity took %.2f seconds",
                    time.time() - start_time_condDemoDisp,
                )
        except Exception as e:
            metric_time_log.error(f"Error: {e}")
            return jsonify({"error": str(e)}), 200
        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(f"Fairness Execution time: {execution_time:.2f} seconds")

        return store_result("fairness", final_dict)

    return get_result_or_default("fairness", file_path, file_name)


@main.route("/correlationAnalysis", methods=["GET", "POST"])
def correlationAnalysis():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)

    if request.method == "POST":
        metric_time_log.info("Correlation Analysis Request Started")
        start_time = time.time()
        try:
            # check for parameters
            # correlations

            if request.form.get("correlations") == "yes":
                start_time_correlations = time.time()
                columns = request.form.getlist("all features for data transformation")
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
        metric_time_log.info(
            f"Correlation Analysis Execution time: {execution_time:.2f} seconds"
        )

        return store_result("correlationAnalysis", final_dict)

    return get_result_or_default("correlationAnalysis", file_path, file_name)


@main.route("/featureRelevance", methods=["GET", "POST"])
def featureRelevance():
    final_dict = {}

    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)

    if request.method == "POST":
        metric_time_log.info("Feature Relevance Request Started")
        start_time = time.time()
        try:
            # check for parameters
            # feature relevancy
            if request.form.get("feature relevancy") == "yes":
                # Get raw input from form and sanitize
                raw_cat_cols = request.form.get(
                    "categorical features for feature relevancy", ""
                )
                raw_num_cols = request.form.get(
                    "numerical features for feature relevancy", ""
                )

                # Clean each list by removing empty strings and whitespace-only entries
                cat_cols = [
                    col.strip() for col in raw_cat_cols.split(",") if col.strip()
                ]
                num_cols = [
                    col.strip() for col in raw_num_cols.split(",") if col.strip()
                ]

                print(cat_cols)
                print(num_cols)

                target = request.form.get("target for feature relevance")

                try:
                    print("Calling data_cleaning with:", cat_cols, num_cols, target)
                    if target in cat_cols or target in num_cols:
                        print("Error: Target is same as feature")
                        return jsonify({"trigger": "correlationError"}), 200
                    data_cleaning_result = data_cleaning.delay(
                        cat_cols, num_cols, target, file_info
                    )
                    df_json = data_cleaning_result.get()  # json serialized
                    print(
                        "Data cleaning returned df with shape:",
                        (
                            pd.DataFrame.from_dict(df_json).shape
                            if df_json is not None
                            else "None"
                        ),
                    )
                except Exception as e:
                    print("Error occurred during data cleaning:", e)
                    df_json = None

                # Generate Pearson correlation
                pearson_corr_result = pearson_correlation.delay(df_json, target)
                correlations = pearson_corr_result.get()
                # don't let the user check the same target and feature
                if correlations is None:
                    print("Error: Correlations is None")
                    return jsonify({"trigger": "correlationError"}), 200
                plot_features_result = plot_features.delay(correlations, target)
                f_plot = plot_features_result.get()
                f_dict = {}

                f_dict["Pearson Correlation to Target"] = correlations
                f_dict["Feature Relevance Visualization"] = f_plot
                f_dict["Description"] = (
                    "With minimum data cleaning (drop missing values, onehot encode categorical "
                    "features, labelencode target feature), the Pearson correlation coefficient is"
                    " calculated for each feature against the target variable. A value of 1 indicates a "
                    "perfect positive correlation, while a value of -1 indicates a perfect negative correlation."
                )
                final_dict["Feature Relevance"] = f_dict
        except Exception as e:
            metric_time_log.error(f"Error: {e}")
            return jsonify({"error": str(e)}), 200
        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(
            f"Feature Relevance Execution time: {execution_time:.2f} seconds"
        )

        return store_result("featureRelevance", final_dict)

    return get_result_or_default("featureRelevance", file_path, file_name)


@main.route("/classImbalance", methods=["GET", "POST"])
def classImbalance():
    final_dict = {}

    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)

    if request.method == "POST":
        metric_time_log.info("Class Imbalance Request Started")
        start_time = time.time()
        try:
            # check for parameters
            if request.form.get("class imbalance") == "yes":
                ci_dict = {}
                classes = request.form.get("features for class imbalance")
                # known display issue
                class_distrib_plot_result = class_distribution_plot.delay(
                    classes, file_info
                )
                ci_dict["Class Imbalance Visualization"] = (
                    class_distrib_plot_result.get()
                )
                ci_dict["Description"] = (
                    "The chart displays the distribution of classes within the specified feature, "
                    "providing a visual representation of the relative proportions of each class."
                )
                calc_imbalance_degree_result = calc_imbalance_degree.delay(
                    classes, file_info, dist_metric="EU"
                )  # By default the distance metric is euclidean distance
                ci_dict["Imbalance degree score"] = calc_imbalance_degree_result.get()
                final_dict["Class Imbalance"] = ci_dict
        except Exception as e:
            metric_time_log.error(f"Error: {e}")
            return jsonify({"error": str(e)}), 200
        end_time = time.time()
        execution_time = end_time - start_time
        metric_time_log.info(
            f"Class Imbalance Execution time: {execution_time:.2f} seconds"
        )

        return store_result("classImbalance", final_dict)

    return get_result_or_default("classImbalance", file_path, file_name)


@main.route("/privacyPreservation", methods=["GET", "POST"])
def privacyPreservation():
    final_dict = {}

    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)

    if request.method == "POST":
        metric_time_log.info("Privacy Preservation Request Started")
        start_time = time.time()
        try:
            # check for parameters
            # differential privacy
            if request.form.get("differential privacy") == "yes":
                start_time_diffPrivacy = time.time()
                feature_to_add_noise = request.form.get(
                    "numerical features to add noise"
                ).split(",")
                epsilon = request.form.get("privacy budget")
                if epsilon is None or epsilon == "":
                    epsilon = 0.1  # Assign a default value for epsilon
                noisy_stat_results = return_noisy_stats.delay(
                    feature_to_add_noise, float(epsilon), file_info
                )
                noisy_stat = noisy_stat_results.get()
                final_dict["DP Statistics"] = noisy_stat
                metric_time_log.info(
                    "Differential privacy took %.2f seconds",
                    time.time() - start_time_diffPrivacy,
                )

            # single attribute risk scores using markov model
            if request.form.get("single attribute risk score") == "yes":
                start_time_oneAttributeRisk = time.time()
                id_feature = request.form.get(
                    "id feature to measure single attribute risk score"
                )
                eval_features = request.form.getlist(
                    "quasi identifiers to measure single attribute risk score"
                )
                print("Single Attribute Risk Score - ID Feature:", id_feature)
                print("Single Attribute Risk Score - Eval Features:", eval_features)
                print(
                    "Single Attribute Risk Score - Eval Features Type:",
                    type(eval_features),
                )
                print(
                    "Single Attribute Risk Score - Form data keys:",
                    list(request.form.keys()),
                )
                print(
                    "Single Attribute Risk Score - All form data:", dict(request.form)
                )

                # Validate that user has selected quasi-identifiers
                if not eval_features or (
                    len(eval_features) == 1 and eval_features[0] == ""
                ):
                    final_dict["Single attribute risk scoring"] = {
                        "Error": "No quasi-identifiers selected. Please select at least one quasi-identifier "
                        "for single attribute risk scoring.",
                        "Single attribute risk scoring Visualization": "",
                        "Description": "No quasi-identifiers were selected for analysis.",
                        "Graph interpretation": "Please select quasi-identifiers and try again.",
                    }
                else:
                    single_attribute_result = (
                        generate_single_attribute_MM_risk_scores.delay(
                            id_feature, eval_features, file_info
                        )
                    )
                    final_dict["Single attribute risk scoring"] = (
                        single_attribute_result.get()
                    )
                metric_time_log.info(
                    "Single attribute risk took %2f seconds",
                    time.time() - start_time_oneAttributeRisk,
                )
            # multpiple attribute risk score using markov model
            if request.form.get("multiple attribute risk score") == "yes":
                start_time_multAttributeRisk = time.time()
                id_feature = request.form.get(
                    "id feature to measure multiple attribute risk score"
                )
                eval_features = request.form.getlist(
                    "quasi identifiers to measure multiple attribute risk score"
                )
                print("Multiple Attribute Risk Score - ID Feature:", id_feature)
                print("Multiple Attribute Risk Score - Eval Features:", eval_features)
                print(
                    "Multiple Attribute Risk Score - Eval Features Type:",
                    type(eval_features),
                )
                print(
                    "Multiple Attribute Risk Score - Form data keys:",
                    list(request.form.keys()),
                )
                print(
                    "Multiple Attribute Risk Score - All form data:", dict(request.form)
                )

                # Validate that user has selected quasi-identifiers
                if not eval_features or (
                    len(eval_features) == 1 and eval_features[0] == ""
                ):
                    final_dict["Multiple attribute risk scoring"] = {
                        "Error": "No quasi-identifiers selected. Please select at least one quasi-identifier "
                        "for multiple attribute risk scoring.",
                        "Multiple attribute risk scoring Visualization": "",
                        "Description": "No quasi-identifiers were selected for analysis.",
                        "Graph interpretation": "Please select quasi-identifiers and try again.",
                    }
                else:
                    multiple_attribute_result = (
                        generate_multiple_attribute_MM_risk_scores.delay(
                            id_feature, eval_features, file_info
                        )
                    )
                    final_dict["Multiple attribute risk scoring"] = (
                        multiple_attribute_result.get()
                    )
                metric_time_log.info(
                    "Differential privacy took %.2f seconds",
                    time.time() - start_time_multAttributeRisk,
                )
            # k-Anonymity
            if request.form.get("k-anonymity") == "yes":
                k_qis = request.form.getlist("quasi identifiers for k-anonymity")
                k_anonymity_result = compute_k_anonymity.delay(k_qis, file_info)
                final_dict["k-Anonymity"] = k_anonymity_result.get()

            # l-Diversity
            if request.form.get("l-diversity") == "yes":
                l_qis = request.form.getlist("quasi identifiers for l-diversity")
                l_sensitive = request.form.get("sensitive attribute for l-diversity")
                l_diversity_result = compute_l_diversity.delay(
                    l_qis, l_sensitive, file_info
                )
                final_dict["l-Diversity"] = l_diversity_result.get()

            # t-Closeness
            if request.form.get("t-closeness") == "yes":
                t_qis = request.form.getlist("quasi identifiers for t-closeness")
                t_sensitive = request.form.get("sensitive attribute for t-closeness")
                t_closeness_result = compute_t_closeness.delay(
                    t_qis, t_sensitive, file_info
                )
                final_dict["t-Closeness"] = t_closeness_result.get()

            # Entropy Risk
            if request.form.get("entropy risk") == "yes":
                entropy_qis = request.form.getlist("quasi identifiers for entropy risk")
                entropy_risk_result = compute_entropy_risk.delay(entropy_qis, file_info)
                final_dict["Entropy Risk"] = entropy_risk_result.get()
        except Exception as e:
            metric_time_log.error(f"Error: {e}")
            return jsonify({"error": str(e)}), 200
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
            df = read_file(file_info)  # Assumes read_file is defined elsewhere

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
                final_dict['Custom Metric Evaluation']['apply_remedy'] = data_file_path

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
"""

        response = make_response(template)
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        response.mimetype = 'text/x-python'
        return response

    except Exception as e:
        metric_time_log.error(f"Error generating template: {str(e)}")
        return jsonify({'error': 'An error occurred while generating the template'}), 500


@main.route("/FAIR", methods=["GET", "POST"])
def FAIR():
    start_time = time.time()
    try:
        if request.method == "POST":
            metric_time_log.info("FAIR Request Started")

            # Check if the 'metadata' field exists in the form data
            if "metadata" not in request.files:
                return jsonify({"error": "No 'metadata' field found in form data"}), 400

            # Get the uploaded file
            file = request.files["metadata"]

            if file.filename == "":
                return jsonify({"error": "No selected file"}), 400
            if not file.filename.endswith(".json"):
                return (
                    jsonify(
                        {"error": "Invalid file format. Please upload a JSON file."}
                    ),
                    400,
                )

            json_data = file.read()
            data_dict = json.loads(json_data.decode("utf-8"))
            if request.form.get("metadata type") == "DCAT":
                # Read and parse the JSON data
                try:
                    data_dict = json.loads(json_data.decode("utf-8"))
                    extract_json_result = extract_keys_and_values.delay(data_dict)
                    extracted_json = extract_json_result.get()
                    fair_dict_result = categorize_metadata.delay(
                        extracted_json, data_dict
                    )
                    fair_dict = fair_dict_result.get()
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

            return store_result("FAIR", result)

        else:
            # check for data from POST request
            results_id = request.args.get("results_id")
            # if present, load data
            if results_id:
                redis_key = f"results:{results_id}"
                cached_result = redis_client.get(redis_key)
                if cached_result:
                    try:
                        data = json.loads(cached_result.decode("utf-8"))
                        return jsonify(data)
                    except json.JSONDecodeError:
                        return jsonify({"error": "Corrupted data in Redis"}), 500

            end_time = time.time()
            metric_time_log.info(
                f"FAIR Execution time: {end_time - start_time} seconds"
            )
            # Render the form for a GET request
            return render_template("metricTemplates/upload_meta.html")

    except Exception as e:
        return jsonify({"error": str(e)}), 400


# Summary Statistics Routes #####


@main.route("/summary_statistics", methods=["POST"])
def handle_summary_statistics():
    try:
        # Get the uploaded file
        uploaded_file_path = session.get("uploaded_file_path")
        if uploaded_file_path and os.path.exists(uploaded_file_path):
            # if data to be parsed, reroute to GET Request
            return redirect(url_for("get_summary_stastistics"))
        # otherwise no file is uploaded, redirect back to file upload
        else:
            return render_template("upload_file.html")
    except Exception as e:
        metric_time_log.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 200


@main.route("/summary_statistics", methods=["GET"])
def get_summary_stastistics():
    try:
        metric_time_log.info("Summary Statistics Request Started")
        start_time = time.time()
        file_path = session.get("uploaded_file_path")
        file_name = session.get("uploaded_file_name")
        file_type = session.get("uploaded_file_type")
        file_info = (file_path, file_name, file_type)
        df = read_file(file_info)
        # Extract summary statistics
        summary_statistics = (
            df.describe()
            .applymap(lambda x: f"{x:.2e}" if abs(x) < 0.01 else round(x, 2))
            .to_dict()
        )

        # Calculate probability distributions
        result = summary_histograms.delay(file_info)
        histograms = result.get()

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
            "success": True,
            "message": "File uploaded successfully",
            "records_count": records_count,
            "features_count": feature_count,
            "categorical_features": list(categorical_columns),
            "numerical_features": list(numerical_columns),
            "all_features": all_features,
            "summary_statistics": summary_statistics,
            "histograms": histograms,
        }
        end_time = time.time()
        metric_time_log.info(
            f"Summary Statistics Execution time: {end_time - start_time:.2f} seconds"
        )
        return jsonify(response_data)
    except Exception as e:
        metric_time_log.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 200


# Feature Set Route #####


@main.route("/feature_set", methods=["POST"])
def extract_features():
    try:
        metric_time_log.info("Feature Set Request Started")
        start_time = time.time()

        file_path = session.get("uploaded_file_path")
        file_name = session.get("uploaded_file_name")
        file_type = session.get("uploaded_file_type")
        file_info = (file_path, file_name, file_type)
        df = read_file(file_info)

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

        # Count the number of records
        records_count = len(df)

        # count the number of features
        feature_count = len(df.columns)

        response_data = {
            "success": True,
            "message": "File uploaded successfully",
            "records_count": records_count,
            "features_count": feature_count,
            "categorical_features": list(categorical_columns),
            "numerical_features": list(numerical_columns),
            "all_features": all_features,
        }
        end_time = time.time()
        metric_time_log.info(
            f"Feature Set Execution time: {end_time - start_time:.2f} seconds"
        )
        return jsonify(response_data)

    except Exception as e:
        metric_time_log.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 200


# Functions #####


def store_result(metric, final_dict):
    formatted_final_dict = format_dict_values(final_dict)

    # save results
    results_id = uuid.uuid4().hex  # unique id
    # Serialize the data as JSON
    redis_client.setex(
        name=f"results:{results_id}",
        time=600,  # expires in 10 minutes
        value=json.dumps(formatted_final_dict),
    )
    return redirect(
        url_for(
            metric, results_id=results_id, return_type=request.args.get("returnType")
        )
    )


def get_result_or_default(metric, uploaded_file_path, uploaded_file_name):
    # check for data from POST request
    results_id = request.args.get("results_id")
    return_type = request.args.get("return_type")
    formatted_final_dict = None

    # if present, load data from database
    data_json = redis_client.get(f"results:{results_id}")

    if data_json is not None:
        formatted_final_dict = json.loads(data_json)
    if return_type == "json" and formatted_final_dict:
        return jsonify(formatted_final_dict)
    return render_template(
        "metricTemplates/" + metric + ".html",
        uploaded_file_path=uploaded_file_path,
        uploaded_file_name=uploaded_file_name,
        formatted_final_dict=formatted_final_dict,
    )


def format_dict_values(d):
    formatted_dict = {}

    for key, value in d.items():
        if isinstance(value, dict):
            formatted_dict[key] = format_dict_values(value)
        elif isinstance(value, (int, float)):
            # Format numerical values to two decimal places
            formatted_dict[key] = round(value, 2)
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
if __name__ == "__main__":
    current_app.run(debug=True)
