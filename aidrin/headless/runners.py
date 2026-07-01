import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from aidrin.file_handling.file_parser import read_file
from aidrin.structured_data_metrics.add_noise import return_noisy_stats
from aidrin.structured_data_metrics.class_imbalance import calc_imbalance_degree
from aidrin.structured_data_metrics.completeness import completeness
from aidrin.structured_data_metrics.correlation_score import calc_correlations
from aidrin.structured_data_metrics.duplicity import duplicity
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

# Signal metrics to skip chart generation in headless mode
os.environ.setdefault("AIDRIN_HEADLESS", "1")

_EXCEL_TYPES = {".xls", ".xlsx", ".xlsm", ".xlsb"}
_EXCEL_KEY = ".xls, .xlsb, .xlsx, .xlsm"


class NullTask:
    def update_state(self, *args: Any, **kwargs: Any) -> None:
        return None


def _normalize_file_type(file_type: Optional[str], file_path: str) -> Optional[str]:
    if file_type:
        candidate = file_type.strip().lower()
        if candidate and not candidate.startswith(".") and candidate != _EXCEL_KEY:
            candidate = f".{candidate}"
    else:
        candidate = Path(file_path).suffix.lower()

    if candidate in _EXCEL_TYPES:
        return _EXCEL_KEY
    return candidate


def _build_file_info(
    file_path: str, file_type: Optional[str], file_name: Optional[str]
) -> tuple:
    normalized_type = _normalize_file_type(file_type, file_path)
    final_name = file_name or os.path.basename(file_path)
    return (file_path, final_name, normalized_type)


def _call_task(task: Any, *args: Any) -> Any:
    unwrapped = getattr(task, "__wrapped__", None)
    if unwrapped is None:
        return task(*args)
    try:
        return unwrapped(NullTask(), *args)
    except TypeError:
        return unwrapped(*args)


def run_completeness(file_path: str, file_type: Optional[str], file_name: Optional[str]) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    return _call_task(completeness, file_info)


def run_duplicity(file_path: str, file_type: Optional[str], file_name: Optional[str]) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    return _call_task(duplicity, file_info)


def run_outliers(file_path: str, file_type: Optional[str], file_name: Optional[str]) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    return _call_task(outliers, file_info)


def run_correlations(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    columns: List[str],
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    return _call_task(calc_correlations, columns, file_info)


def run_feature_relevance(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    cat_columns: List[str],
    num_columns: List[str],
    target_column: str,
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    df_json = _call_task(data_cleaning, cat_columns, num_columns, target_column, file_info)
    if isinstance(df_json, dict) and "Error" in df_json:
        return df_json

    correlations = _call_task(pearson_correlation, df_json, target_column)
    if isinstance(correlations, dict) and "Error" in correlations:
        return correlations

    feature_plot = _call_task(plot_features, correlations, target_column)
    if feature_plot is None:
        return {"Error": "Visualization generation failed"}

    return {
        "Pearson Correlation to Target": correlations,
        "Feature Relevance Visualization": feature_plot,
        "Description": (
            "With minimum data cleaning (drop missing values, onehot encode "
            "categorical features, labelencode target feature), the Pearson "
            "correlation coefficient is calculated for each feature against the "
            "target variable. A value of 1 indicates a perfect positive "
            "correlation, while a value of -1 indicates a perfect negative "
            "correlation."
        ),
    }


def run_class_imbalance(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    target_column: str,
    distance_metric: Optional[str],
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    data = read_file(file_info)
    distance_metric = distance_metric or "EU"
    ci_dict: Dict[str, Any] = {}

    try:
        imbalance_result = calc_imbalance_degree(
            data, target_column, dist_metric=distance_metric
        )
        if isinstance(imbalance_result, dict) and "Error" in imbalance_result:
            ci_dict["Error"] = imbalance_result["Error"]
            ci_dict["ErrorType"] = imbalance_result.get(
                "ErrorType", "Processing Error"
            )
            ci_dict["Class Imbalance Visualization"] = ""
            ci_dict["Description"] = f"Error: {imbalance_result['Error']}"
        else:
            ci_dict["Imbalance degree"] = imbalance_result
    except Exception as exc:
        error_msg = str(exc)
        ci_dict["Error"] = error_msg
        ci_dict["ErrorType"] = "Processing Error"
        ci_dict["Class Imbalance Visualization"] = ""
        ci_dict["Description"] = f"Error: {error_msg}"

    return ci_dict


def run_statistical_rates(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    y_true_column: str,
    sensitive_attribute_column: str,
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    result = _call_task(
        calculate_statistical_rates, y_true_column, sensitive_attribute_column, file_info
    )
    if isinstance(result, dict) and "Error" in result:
        return result
    result["Description"] = (
        "The result illustrates the statistical rates of various classes across different sensitive attributes. "
        "Each group in the result represents a specific sensitive attribute, and within each group, each key corresponds "
        "to a class, with the value indicating the proportion of that sensitive attribute within that particular class"
    )
    return result


def run_representation_rate(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    columns: List[str],
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    ratios = _call_task(calculate_representation_rate, columns, file_info)
    if isinstance(ratios, dict) and "Error" in ratios:
        return ratios
    visualization = _call_task(create_representation_rate_vis, columns, file_info)
    if isinstance(visualization, dict) and "Error" in visualization:
        return visualization

    return {
        "Probability ratios": ratios,
        "Representation Rate Visualization": visualization,
        "Description": (
            "Represent probability ratios that quantify the relative representation "
            "of different categories within the sensitive features, highlighting "
            "differences in representation rates between various groups. Higher "
            "values imply overrepresentation relative to another"
        ),
    }


def run_k_anonymity(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    quasi_identifiers: List[str],
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    return compute_k_anonymity(quasi_identifiers, file_info)


def run_l_diversity(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    quasi_identifiers: List[str],
    sensitive_column: str,
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    return compute_l_diversity(quasi_identifiers, sensitive_column, file_info)


def run_t_closeness(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    quasi_identifiers: List[str],
    sensitive_column: str,
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    return compute_t_closeness(quasi_identifiers, sensitive_column, file_info)


def run_entropy_risk(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    quasi_identifiers: List[str],
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    return compute_entropy_risk(quasi_identifiers, file_info)


def run_single_attribute_risk(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    id_column: str,
    eval_columns: List[str],
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    data = read_file(file_info)
    return generate_single_attribute_MM_risk_scores(data, id_column, eval_columns, NullTask())


def run_multiple_attribute_risk(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    id_column: str,
    eval_columns: List[str],
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    data = read_file(file_info)
    return generate_multiple_attribute_MM_risk_scores(data, id_column, eval_columns, NullTask())


def _dp_error_payload(error_message: str) -> Dict[str, Any]:
    if "Epsilon must be greater than 0" in error_message:
        return {
            "Error": "Invalid epsilon value. Epsilon must be greater than 0.",
            "DP Statistics Visualization": "",
            "Graph interpretation": "No visualization available due to invalid parameters.",
            "Mean of feature (before noise)": "N/A",
            "Variance of feature (before noise)": "N/A",
            "Mean of feature (after noise)": "N/A",
            "Variance of feature (after noise)": "N/A",
            "Noisy file saved": "Failed - Invalid parameters",
        }
    if "Dataset is empty" in error_message:
        return {
            "Error": "Dataset is empty after removing null values or contains no valid data.",
            "DP Statistics Visualization": "",
            "Graph interpretation": "No visualization available - insufficient data.",
            "Mean of feature (before noise)": "N/A",
            "Variance of feature (before noise)": "N/A",
            "Mean of feature (after noise)": "N/A",
            "Variance of feature (after noise)": "N/A",
            "Noisy file saved": "Failed - No data to process",
        }
    return {
        "Error": f"Processing error: {error_message}",
        "DP Statistics Visualization": "",
        "Graph interpretation": "No visualization available due to processing error.",
        "Mean of feature (before noise)": "N/A",
        "Variance of feature (before noise)": "N/A",
        "Mean of feature (after noise)": "N/A",
        "Variance of feature (after noise)": "N/A",
        "Noisy file saved": "Failed - Processing error",
    }


def run_differential_privacy(
    file_path: str,
    file_type: Optional[str],
    file_name: Optional[str],
    columns: List[str],
    epsilon: float,
) -> Dict[str, Any]:
    file_info = _build_file_info(file_path, file_type, file_name)
    data = read_file(file_info)
    try:
        return return_noisy_stats(columns, float(epsilon), data)
    except Exception as exc:
        return _dp_error_payload(str(exc))
