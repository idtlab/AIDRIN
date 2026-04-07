import json
import logging
import time

from celery.result import AsyncResult
from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    session,
)
from aidrin.file_handling.file_parser import read_file
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
from aidrin.structured_data_metrics.hipaa_compliance import detect_hipaa_identifiers
from aidrin.structured_data_metrics.outliers import outliers
from aidrin.structured_data_metrics.privacy_measure import (
    calculate_multiple_attribute_risk_score,
    calculate_single_attribute_risk_score,
    compute_entropy_risk,
    compute_k_anonymity,
    compute_l_diversity,
    compute_t_closeness,
)
from aidrin.structured_data_metrics.representation_rate import (
    calculate_representation_rate,
    create_representation_rate_vis,
)
from aidrin.structured_data_metrics.statistical_rate import calculate_statistical_rates
from web.routes.utils import (
    ensure_json_serializable,
    format_dict_values,
    generate_metric_cache_key,
    get_result_or_default,
    is_metric_cache_valid,
    store_result,
)

metrics_bp = Blueprint("metrics", __name__)

metric_time_log = logging.getLogger("metric")


# ---------------------------------------------------------------------------
# Data Quality
# ---------------------------------------------------------------------------

@metrics_bp.route("/data-quality", methods=["GET", "POST"])
def data_quality():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)

    if request.method == "POST":
        start_time = time.time()
        metric_time_log.info("Data quality Request Started")
        try:
            if request.form.get("completeness") == "yes":
                t0 = time.time()
                compl_dict = completeness(file_info)
                compl_dict["Description"] = (
                    "Indicate the proportion of available data for each feature, "
                    "with values closer to 1 indicating high completeness, and values near "
                    "0 indicating low completeness. If the visualization is empty, it means "
                    "that all features are complete."
                )
                final_dict["Completeness"] = compl_dict
                metric_time_log.info("Completeness took %.2f seconds", time.time() - t0)

            if request.form.get("outliers") == "yes":
                t0 = time.time()
                out_dict = outliers(file_info)
                out_dict["Description"] = (
                    "Outlier scores are calculated for numerical columns using the Interquartile"
                    " Range (IQR) method, where a score of 1 indicates that all data points in a "
                    "column are identified as outliers, a score of 0 signifies no outliers are detected"
                )
                final_dict["Outliers"] = out_dict
                metric_time_log.info("Outliers took %.2f seconds", time.time() - t0)

            if request.form.get("duplicity") == "yes":
                t0 = time.time()
                dup_dict = duplicity(file_info)
                dup_dict["Description"] = (
                    "A value of 0 indicates no duplicates, and a value closer to 1 signifies a higher "
                    "proportion of duplicated data points in the dataset"
                )
                final_dict["Duplicity"] = dup_dict
                metric_time_log.info("Duplicity took %.2f seconds", time.time() - t0)

        except Exception as e:
            metric_time_log.error(f"Error: {e}")
            return jsonify({"error": str(e)}), 200

        metric_time_log.info(
            f"Data Quality Execution time: {time.time() - start_time:.2f} seconds"
        )
        return store_result("metrics.data_quality", final_dict)

    return get_result_or_default("metrics.data_quality", file_path, file_name)


# ---------------------------------------------------------------------------
# Fairness
# ---------------------------------------------------------------------------

@metrics_bp.route("/fairness", methods=["GET", "POST"])
def fairness():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)
    file = read_file(file_info)

    if request.method == "POST":
        start_time = time.time()

        if (
            request.form.get("representation rate") == "yes"
            and request.form.get("features for representation rate") is not None
        ):
            rep_dict = {}
            list_of_cols = [
                item.strip()
                for item in request.form.get("features for representation rate").split(", ")
            ]
            rep_dict["Probability ratios"] = calculate_representation_rate(list_of_cols, file_info)
            rep_dict["Representation Rate Visualization"] = create_representation_rate_vis(
                list_of_cols, file_info
            )
            rep_dict["Description"] = (
                "Represent probability ratios that quantify the relative representation "
                "of different categories within the sensitive features, highlighting "
                "differences in representation rates between various groups. Higher "
                "values imply overrepresentation relative to another"
            )
            final_dict["Representation Rate"] = rep_dict

        if (
            request.form.get("statistical rate") == "yes"
            and request.form.get("features for statistical rate") is not None
            and request.form.get("target for statistical rate") is not None
        ):
            try:
                t0 = time.time()
                y_true = request.form.get("target for statistical rate")
                sensitive_attribute_column = request.form.get("features for statistical rate")
                sr_dict = calculate_statistical_rates(y_true, sensitive_attribute_column, file_info)
                sr_dict["Description"] = (
                    "The graph illustrates the statistical rates of various classes across different "
                    "sensitive attributes. Each group in the graph represents a specific sensitive "
                    "attribute, and within each group, each bar corresponds to a class, with the height "
                    "indicating the proportion of that sensitive attribute within that particular class"
                )
                final_dict["Statistical Rate"] = sr_dict
                metric_time_log.info(
                    "Statistical Rate analysis took %.2f seconds", time.time() - t0
                )
            except Exception as e:
                metric_time_log.error("Error during Statistical Rate analysis: %s", e)
                final_dict["Statistical Rate"] = {"Error": str(e)}

        if request.form.get("conditional demographic disparity") == "yes":
            t0 = time.time()
            target = request.form.get("target for conditional demographic disparity")
            sensitive = request.form.get("sensitive for conditional demographic disparity")
            accepted_value = request.form.get("target value for conditional demographic disparity")
            try:
                cdd_result = conditional_demographic_disparity.delay(
                    file[target].to_list(), file[sensitive].to_list(), accepted_value
                )
                cdd_dict = cdd_result.get(timeout=60)
            except Exception as e:
                metric_time_log.error("Error during Conditional Demographic Disparity analysis: %s", e)
                final_dict["Conditional Demographic Disparity"] = {"Error": str(e)}
                cdd_dict = None
            if cdd_dict is not None:
                cdd_dict["Description"] = (
                    "The conditional demographic disparity metric evaluates the distribution "
                    "of outcomes categorized as positive and negative across various sensitive groups. "
                    "The user specifies which outcome category is considered \"positive\" for the analysis, "
                    "with all other outcome categories classified as \"negative\". The metric calculates the "
                    "proportion of outcomes classified as \"positive\" and \"negative\" within each sensitive group."
                    " A resulting disparity value of True indicates that within a specific sensitive group, "
                    "the proportion of outcomes classified as \"negative\" exceeds the proportion classified as"
                    " \"positive\". This metric provides insights into potential disparities in outcome distribution "
                    "across sensitive groups based on the user-defined positive outcome criterion."
                )
                final_dict["Conditional Demographic Disparity"] = cdd_dict
                metric_time_log.info(
                    "Conditional Demographic Disparity took %.2f seconds", time.time() - t0
                )

        print(f"Execution time: {time.time() - start_time} seconds")
        return store_result("metrics.fairness", final_dict)

    return get_result_or_default("metrics.fairness", file_path, file_name)



# ---------------------------------------------------------------------------
# Correlation Analysis
# ---------------------------------------------------------------------------

@metrics_bp.route("/correlation-analysis", methods=["GET", "POST"])
def correlation_analysis():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")

    if request.method == "POST":
        metric_time_log.info("Correlation Analysis Request Started")
        start_time = time.time()
        try:
            if request.form.get("correlations") == "yes":
                t0 = time.time()
                cat_cols = [
                    col.strip()
                    for col in request.form.get("categorical features", "").split(",")
                    if col.strip()
                ]
                num_cols = [
                    col.strip()
                    for col in request.form.get("numerical features", "").split(",")
                    if col.strip()
                ]
                columns = cat_cols + num_cols
                file_info = (file_path, file_name, file_type)

                correlations_result = calc_correlations.delay(columns, file_info)
                corr_dict = correlations_result.get()
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
                metric_time_log.info("Correlations took %.2f seconds", time.time() - t0)
                print(f"Execution time: {time.time() - start_time} seconds")
                return store_result("metrics.correlation_analysis", final_dict)
            else:
                return jsonify({"message": "No correlation analysis selected"}), 200
        except Exception as e:
            metric_time_log.error(f"Error: {e}")
            return jsonify({"error": str(e)}), 200

    return get_result_or_default("metrics.correlation_analysis", file_path, file_name)


# ---------------------------------------------------------------------------
# Feature Relevance
# ---------------------------------------------------------------------------

@metrics_bp.route("/feature-relevance", methods=["GET", "POST"])
def feature_relevance():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")

    if request.method == "POST":
        start_time = time.time()
        if request.form.get("feature relevancy") == "yes":
            cat_cols = [
                col.strip()
                for col in request.form.get("categorical features", "").split(",")
                if col.strip()
            ]
            num_cols = [
                col.strip()
                for col in request.form.get("numerical features", "").split(",")
                if col.strip()
            ]
            target = request.form.get("target for feature relevance")

            try:
                if target in cat_cols or target in num_cols:
                    return jsonify({"trigger": "correlationError"}), 200
                file_info = (file_path, file_name, file_type)
                data_cleaning_result = data_cleaning.delay(cat_cols, num_cols, target, file_info)
                df_json = data_cleaning_result.get()

                if isinstance(df_json, dict) and "Error" in df_json:
                    return jsonify({"trigger": "correlationError", "error": df_json["Error"]}), 200
                if df_json is None:
                    return jsonify({"trigger": "correlationError", "error": "Data cleaning failed"}), 200
            except Exception as e:
                return jsonify({"trigger": "correlationError", "error": str(e)}), 200

            try:
                pearson_corr_result = pearson_correlation.delay(df_json, target)
                correlations = pearson_corr_result.get()

                if isinstance(correlations, dict) and "Error" in correlations:
                    return jsonify({"trigger": "correlationError", "error": correlations["Error"]}), 200
                if not correlations:
                    return jsonify(
                        {"trigger": "correlationError", "error": "No valid correlations could be calculated"}
                    ), 200
            except Exception as e:
                return jsonify({"trigger": "correlationError", "error": str(e)}), 200

            try:
                plot_features_result = plot_features.delay(correlations, target)
                f_plot = plot_features_result.get()
                if f_plot is None:
                    return jsonify({"trigger": "correlationError", "error": "Visualization generation failed"}), 200
            except Exception as e:
                return jsonify(
                    {"trigger": "correlationError", "error": f"Plot generation failed: {str(e)}"}
                ), 200

            f_dict = {
                "Pearson Correlation to Target": correlations,
                "Feature Relevance Visualization": f_plot,
                "Description": (
                    "With minimum data cleaning (drop missing values, onehot encode "
                    "categorical features, labelencode target feature), the Pearson "
                    "correlation coefficient is calculated for each feature against the "
                    "target variable. A value of 1 indicates a perfect positive "
                    "correlation, while a value of -1 indicates a perfect negative "
                    "correlation."
                ),
            }
            final_dict["Feature Relevance"] = f_dict
            print(f"Execution time: {time.time() - start_time} seconds")
            return store_result("metrics.feature_relevance", final_dict)
        else:
            return jsonify({"message": "No feature relevance analysis selected"}), 200

    return get_result_or_default("metrics.feature_relevance", file_path, file_name)


# ---------------------------------------------------------------------------
# Class Imbalance
# ---------------------------------------------------------------------------

@metrics_bp.route("/class-imbalance", methods=["GET", "POST"])
def class_imbalance():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)
    file = read_file(file_info)

    if request.method == "POST":
        start_time = time.time()
        if request.form.get("class imbalance") == "yes":
            classes = request.form.get("target features for class imbalance")
            dist_metric = request.form.get("distance metric for class imbalance") or "EU"

            cache_key = generate_metric_cache_key(
                file_name, "classimbalance", classes=classes, dist_metric=dist_metric
            )

            cached_entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)
            if cached_entry and is_metric_cache_valid(cached_entry):
                final_dict["Class Imbalance"] = cached_entry["data"]
                current_app.TEMP_RESULTS_CACHE[cache_key] = {
                    "data": cached_entry["data"],
                    "timestamp": time.time(),
                    "expires_at": time.time() + (30 * 60),
                }
            else:
                if cached_entry:
                    current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
                ci_dict = _compute_class_imbalance(file, classes, dist_metric)
                final_dict["Class Imbalance"] = ci_dict
                current_app.TEMP_RESULTS_CACHE[cache_key] = {
                    "data": ci_dict,
                    "timestamp": time.time(),
                    "expires_at": time.time() + (30 * 60),
                }

        print(f"Execution time: {time.time() - start_time} seconds")
        return store_result("metrics.class_imbalance", final_dict)

    return get_result_or_default("metrics.class_imbalance", file_path, file_name)


def _compute_class_imbalance(file, classes, dist_metric):
    ci_dict = {}
    try:
        ci_dict["Class Imbalance Visualization"] = class_distribution_plot(file, classes)
        ci_dict["Description"] = (
            "The chart displays the distribution of classes within the "
            "specified feature, providing a visual representation of the "
            "relative proportions of each class."
        )
        imbalance_result = calc_imbalance_degree(file, classes, dist_metric=dist_metric)
        if "Error" in imbalance_result:
            ci_dict["Error"] = imbalance_result["Error"]
            ci_dict["ErrorType"] = imbalance_result.get("ErrorType", "Processing Error")
            ci_dict["Class Imbalance Visualization"] = ""
            ci_dict["Description"] = f"Error: {imbalance_result['Error']}"
        else:
            ci_dict["Imbalance degree"] = imbalance_result
    except Exception as e:
        ci_dict["Error"] = str(e)
        ci_dict["ErrorType"] = "Processing Error"
        ci_dict["Class Imbalance Visualization"] = ""
        ci_dict["Description"] = f"Error: {str(e)}"
    return ci_dict


# ---------------------------------------------------------------------------
# Privacy Preservation
# ---------------------------------------------------------------------------

@metrics_bp.route("/privacy-preservation", methods=["GET", "POST"])
def privacy_preservation():
    final_dict = {}
    file_path = session.get("uploaded_file_path")
    file_name = session.get("uploaded_file_name")
    file_type = session.get("uploaded_file_type")
    file_info = (file_path, file_name, file_type)
    file = read_file(file_info)

    if request.method == "POST":
        start_time = time.time()
        metric_time_log.info("Privacy Preservation Request Started")

        if request.form.get("differential privacy") == "yes":
            numerical_features_raw = request.form.get("numerical features to add noise")
            if not numerical_features_raw or not numerical_features_raw.strip():
                final_dict["DP Statistics"] = _dp_error(
                    "No numerical features selected for differential privacy."
                )
            else:
                feature_to_add_noise = [f.strip() for f in numerical_features_raw.split(",") if f.strip()]
                if not feature_to_add_noise:
                    final_dict["DP Statistics"] = _dp_error("Invalid numerical features selected.")
                else:
                    epsilon_raw = request.form.get("privacy budget")
                    epsilon = 0.1
                    if epsilon_raw and epsilon_raw.strip():
                        try:
                            epsilon = float(epsilon_raw)
                            if epsilon <= 0:
                                final_dict["DP Statistics"] = _dp_error(
                                    "Invalid epsilon value. Epsilon must be greater than 0."
                                )
                            else:
                                _process_differential_privacy(
                                    file_name, feature_to_add_noise, epsilon, file, final_dict
                                )
                        except ValueError:
                            final_dict["DP Statistics"] = _dp_error("Invalid epsilon value format.")
                    else:
                        _process_differential_privacy(
                            file_name, feature_to_add_noise, epsilon, file, final_dict
                        )

        if request.form.get("single attribute risk score") == "yes":
            id_feature = request.form.get("id feature to measure single attribute risk score")
            eval_features = request.form.getlist(
                "quasi identifiers to measure single attribute risk score"
            )
            if not eval_features or (len(eval_features) == 1 and eval_features[0] == ""):
                final_dict["Single attribute risk scoring"] = {
                    "Error": "No quasi-identifiers selected for single attribute risk scoring.",
                    "Single attribute risk scoring Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                    "ErrorType": "Selection Error",
                }
            else:
                cache_key = generate_metric_cache_key(
                    file_name, "single", id_feature=id_feature, qis=eval_features
                )
                _run_cached_async_task(
                    cache_key,
                    calculate_single_attribute_risk_score,
                    final_dict,
                    "Single attribute risk scoring",
                    file.to_json(),
                    id_feature,
                    eval_features,
                )

        if request.form.get("multiple attribute risk score") == "yes":
            id_feature = request.form.get("id feature to measure multiple attribute risk score")
            eval_features = request.form.getlist(
                "quasi identifiers to measure multiple attribute risk score"
            )
            if not eval_features or (len(eval_features) == 1 and eval_features[0] == ""):
                final_dict["Multiple attribute risk scoring"] = {
                    "Error": "No quasi-identifiers selected for multiple attribute risk scoring.",
                    "Multiple attribute risk scoring Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                    "ErrorType": "Selection Error",
                }
            elif not id_feature or not id_feature.strip():
                final_dict["Multiple attribute risk scoring"] = {
                    "Error": "No ID feature selected for multiple attribute risk scoring.",
                    "Multiple attribute risk scoring Visualization": "",
                    "Graph interpretation": "No visualization available - no ID feature selected.",
                    "ErrorType": "Selection Error",
                }
            else:
                cache_key = generate_metric_cache_key(
                    file_name, "multiple", id_feature=id_feature, qis=eval_features
                )
                _run_cached_async_task(
                    cache_key,
                    calculate_multiple_attribute_risk_score,
                    final_dict,
                    "Multiple attribute risk scoring",
                    file.to_json(),
                    id_feature,
                    eval_features,
                )

        if request.form.get("k-anonymity") == "yes":
            k_qis = request.form.getlist("quasi identifiers for k-anonymity")
            if not k_qis or (len(k_qis) == 1 and k_qis[0] == ""):
                final_dict["k-Anonymity"] = {
                    "Error": "No quasi-identifiers selected for k-anonymity calculation.",
                    "k-Anonymity Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                }
            else:
                cache_key = generate_metric_cache_key(file_name, "kanon", qis=k_qis)
                _run_cached_sync_task(
                    cache_key, compute_k_anonymity, final_dict, "k-Anonymity", k_qis, file
                )

        if request.form.get("l-diversity") == "yes":
            l_qis = request.form.getlist("quasi identifiers for l-diversity")
            l_sensitive = request.form.get("sensitive attribute for l-diversity")
            if not l_qis or (len(l_qis) == 1 and l_qis[0] == ""):
                final_dict["l-Diversity"] = {
                    "Error": "No quasi-identifiers selected for l-diversity calculation.",
                    "l-Diversity Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                }
            elif not l_sensitive or not l_sensitive.strip():
                final_dict["l-Diversity"] = {
                    "Error": "No sensitive attribute selected for l-diversity calculation.",
                    "l-Diversity Visualization": "",
                    "Graph interpretation": "No visualization available - no sensitive attribute selected.",
                }
            else:
                cache_key = generate_metric_cache_key(
                    file_name, "ldiv", qis=l_qis, sensitive=l_sensitive
                )
                _run_cached_sync_task(
                    cache_key, compute_l_diversity, final_dict, "l-Diversity",
                    l_qis, l_sensitive, file
                )

        if request.form.get("t-closeness") == "yes":
            t_qis = request.form.getlist("quasi identifiers for t-closeness")
            t_sensitive = request.form.get("sensitive attribute for t-closeness")
            if not t_qis or (len(t_qis) == 1 and t_qis[0] == ""):
                final_dict["t-Closeness"] = {
                    "Error": "No quasi-identifiers selected for t-closeness calculation.",
                    "t-Closeness Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                }
            elif not t_sensitive or not t_sensitive.strip():
                final_dict["t-Closeness"] = {
                    "Error": "No sensitive attribute selected for t-closeness calculation.",
                    "t-Closeness Visualization": "",
                    "Graph interpretation": "No visualization available - no sensitive attribute selected.",
                }
            else:
                cache_key = generate_metric_cache_key(
                    file_name, "tclose", qis=t_qis, sensitive=t_sensitive
                )
                _run_cached_sync_task(
                    cache_key, compute_t_closeness, final_dict, "t-Closeness",
                    t_qis, t_sensitive, file
                )

        if request.form.get("entropy risk") == "yes":
            entropy_qis = request.form.getlist("quasi identifiers for entropy risk")
            if not entropy_qis or (len(entropy_qis) == 1 and entropy_qis[0] == ""):
                final_dict["Entropy Risk"] = {
                    "Error": "No quasi-identifiers selected for entropy risk calculation.",
                    "Entropy Risk Visualization": "",
                    "Graph interpretation": "No visualization available - no quasi-identifiers selected.",
                }
            else:
                cache_key = generate_metric_cache_key(file_name, "entropy", qis=entropy_qis)
                _run_cached_sync_task(
                    cache_key, compute_entropy_risk, final_dict, "Entropy Risk",
                    entropy_qis, file
                )

        metric_time_log.info(
            f"Privacy Preservation Execution time: {time.time() - start_time:.2f} seconds"
        )
        return store_result("metrics.privacy_preservation", final_dict)

    return get_result_or_default("metrics.privacy_preservation", file_path, file_name)


# ---------------------------------------------------------------------------
# HIPAA Compliance
# ---------------------------------------------------------------------------

@metrics_bp.route("/hipaa-compliance", methods=["GET", "POST"])
def hipaa_compliance():
    final_dict = {}
    data_file_path = session.get("uploaded_file_path")
    data_file_name = session.get("uploaded_file_name")
    data_file_type = session.get("uploaded_file_type")
    file_info = (data_file_path, data_file_name, data_file_type)

    if request.method == "POST":
        metric_time_log.info("HIPAA Compliance Evaluation Request Started")
        start_time = time.time()
        try:
            df = read_file(file_info)
            selected_columns = request.form.getlist("HIPAA identifiers for HIPAA compliance")
            detected_hipaa = detect_hipaa_identifiers(df, selected_columns)

            final_dict["HIPAA Compliance Evaluation"] = {
                "Detected HIPAA Identifiers": detected_hipaa,
                "Description": (
                    "This metric performs a high-precision audit of the dataset to identify Protected "
                    "Health Information (PHI). It uses a hybrid approach: using pre-compiled regular "
                    "expressions for fixed-format identifiers (SSNs, emails, medical IDs, URLs, "
                    "phone/fax numbers, VIN numbers and IP addresses) and the pgeocode GeoNames "
                    "database to validate global postal codes."
                ),
            }
            final_dict = ensure_json_serializable(final_dict)

        except Exception as e:
            metric_time_log.error(f"Error: {str(e)}")
            return jsonify({"error": str(e)}), 500

        metric_time_log.info(
            f"HIPAA Compliance Evaluation Execution time: {time.time() - start_time:.2f} seconds"
        )
        return store_result("metrics.hipaa_compliance", final_dict)

    return get_result_or_default("metrics.hipaa_compliance", data_file_path, data_file_name)


# ---------------------------------------------------------------------------
# FAIR Assessment
# ---------------------------------------------------------------------------

@metrics_bp.route("/fair-assessment", methods=["GET", "POST"])
def fair_assessment():
    start_time = time.time()
    try:
        if request.method == "POST":
            if "metadata" not in request.files:
                return jsonify({"error": "No 'metadata' field found in form data"}), 400

            file = request.files["metadata"]
            if file.filename == "":
                return jsonify({"error": "No selected file"}), 400
            if not file.filename.endswith(".json"):
                return jsonify({"error": "Invalid file format. Please upload a JSON file."}), 400

            json_data = file.read()
            data_dict = json.loads(json_data.decode("utf-8"))

            if request.form.get("metadata type") == "DCAT":
                try:
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
                return jsonify({"Error:": "Unknown metadata type"}), 400

            return store_result("metrics.fair_assessment", result)

        else:
            results_id = request.args.get("results_id")
            if results_id and results_id in current_app.TEMP_RESULTS_CACHE:
                entry = current_app.TEMP_RESULTS_CACHE.pop(results_id)
                return jsonify(entry["data"])

            print(f"Execution time: {time.time() - start_time} seconds")
            return render_template("metricTemplates/upload_meta.html")

    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ---------------------------------------------------------------------------
# Async task status polling
# ---------------------------------------------------------------------------

@metrics_bp.route("/check-and-update-task/<task_id>/<metric_name>", methods=["GET"])
def check_task_status(task_id, metric_name):
    try:
        task_result = AsyncResult(task_id)

        if task_result.ready():
            if task_result.successful():
                result = task_result.get()
                cache_key = f"{task_id}_{metric_name}"
                current_app.TEMP_RESULTS_CACHE[cache_key] = {
                    "data": result,
                    "timestamp": time.time(),
                }
                return jsonify({"status": "completed", "result": result})
            else:
                error = str(task_result.info) if task_result.info else "Task failed"
                return jsonify({"status": "failed", "error": error}), 500
        else:
            progress_info = (
                task_result.info if isinstance(task_result.info, dict) else {}
            )
            return jsonify(
                {
                    "status": "processing",
                    "progress": {
                        "current": progress_info.get("current", 0),
                        "total": progress_info.get("total", 100),
                        "status": progress_info.get("status", "Processing..."),
                    },
                }
            )
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _dp_error(message):
    return {
        "Error": message,
        "DP Statistics Visualization": "",
        "Graph interpretation": "No visualization available due to invalid parameters.",
        "Mean of feature (before noise)": "N/A",
        "Variance of feature (before noise)": "N/A",
        "Mean of feature (after noise)": "N/A",
        "Variance of feature (after noise)": "N/A",
        "Noisy file saved": "Failed - Invalid parameters",
    }


def _process_differential_privacy(file_name, features, epsilon, file, final_dict):
    cache_key = generate_metric_cache_key(
        file_name, "dp", features=features, epsilon=epsilon
    )
    cached_entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)

    if cached_entry and is_metric_cache_valid(cached_entry):
        final_dict["DP Statistics"] = cached_entry["data"]
        current_app.TEMP_RESULTS_CACHE[cache_key] = {
            "data": cached_entry["data"],
            "timestamp": time.time(),
            "expires_at": time.time() + (30 * 60),
        }
        return

    if cached_entry:
        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)

    try:
        noisy_stat = return_noisy_stats(features, float(epsilon), file)
        final_dict["DP Statistics"] = noisy_stat
    except Exception as e:
        error_message = str(e)
        if "Epsilon must be greater than 0" in error_message:
            noisy_stat = _dp_error("Invalid epsilon value. Epsilon must be greater than 0.")
        elif "Dataset is empty" in error_message:
            noisy_stat = {
                "Error": "Dataset is empty after removing null values or contains no valid data.",
                "DP Statistics Visualization": "",
                "Graph interpretation": "No visualization available - insufficient data.",
                "Mean of feature (before noise)": "N/A",
                "Variance of feature (before noise)": "N/A",
                "Mean of feature (after noise)": "N/A",
                "Variance of feature (after noise)": "N/A",
                "Noisy file saved": "Failed - No data to process",
            }
        else:
            noisy_stat = {
                "Error": f"Processing error: {error_message}",
                "DP Statistics Visualization": "",
                "Graph interpretation": "No visualization available due to processing error.",
                "Mean of feature (before noise)": "N/A",
                "Variance of feature (before noise)": "N/A",
                "Mean of feature (after noise)": "N/A",
                "Variance of feature (after noise)": "N/A",
                "Noisy file saved": "Failed - Processing error",
            }
        final_dict["DP Statistics"] = noisy_stat

    current_app.TEMP_RESULTS_CACHE[cache_key] = {
        "data": final_dict["DP Statistics"],
        "timestamp": time.time(),
        "expires_at": time.time() + (30 * 60),
    }


def _run_cached_async_task(cache_key, task_fn, final_dict, result_key, *task_args):
    """Run an async Celery task with cache check/store pattern."""
    cached_entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)
    if cached_entry and is_metric_cache_valid(cached_entry):
        final_dict[result_key] = cached_entry["data"]
        current_app.TEMP_RESULTS_CACHE[cache_key] = {
            "data": cached_entry["data"],
            "timestamp": time.time(),
            "expires_at": time.time() + (30 * 60),
        }
        return

    if cached_entry:
        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)

    try:
        task = task_fn.delay(*task_args)
        result_data = {
            "task_id": task.id,
            "status": "processing",
            "message": f"{result_key} is being processed asynchronously. Please check back later.",
            "is_async": True,
            "cache_key": cache_key,
        }
        final_dict[result_key] = result_data
        current_app.TEMP_RESULTS_CACHE[cache_key] = {
            "data": result_data,
            "timestamp": time.time(),
            "expires_at": time.time() + (30 * 60),
            "task_id": task.id,
        }
    except Exception as e:
        final_dict[result_key] = {
            "Error": f"Processing error: {str(e)}",
            f"{result_key} Visualization": "",
            "Graph interpretation": "No visualization available due to processing error.",
            "ErrorType": "Processing Error",
        }


def _run_cached_sync_task(cache_key, task_fn, final_dict, result_key, *task_args):
    """Run a synchronous metric function with cache check/store pattern."""
    cached_entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)
    if cached_entry and is_metric_cache_valid(cached_entry):
        final_dict[result_key] = cached_entry["data"]
        current_app.TEMP_RESULTS_CACHE[cache_key] = {
            "data": cached_entry["data"],
            "timestamp": time.time(),
            "expires_at": time.time() + (30 * 60),
        }
        return

    if cached_entry:
        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)

    try:
        result = task_fn(*task_args)
        final_dict[result_key] = result
        current_app.TEMP_RESULTS_CACHE[cache_key] = {
            "data": result,
            "timestamp": time.time(),
            "expires_at": time.time() + (30 * 60),
        }
    except Exception as e:
        final_dict[result_key] = {
            "Error": f"Processing error: {str(e)}",
            f"{result_key} Visualization": "",
            "Graph interpretation": "No visualization available due to processing error.",
        }
