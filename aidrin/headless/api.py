import base64
import os
import re
import sys
import time
import importlib.util
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional

from .config import HeadlessConfig
from .runners import (
    run_class_imbalance,
    run_completeness,
    run_correlations,
    run_differential_privacy,
    run_duplicity,
    run_entropy_risk,
    run_feature_relevance,
    run_k_anonymity,
    run_l_diversity,
    run_multiple_attribute_risk,
    run_outliers,
    run_representation_rate,
    run_single_attribute_risk,
    run_statistical_rates,
    run_t_closeness,
)


METRIC_REGISTRY: Dict[str, Dict[str, Any]] = {
    "completeness": {
        "category": "data-quality",
        "description": "Column completeness scores and overall completeness.",
        "runner": run_completeness,
        "required_args": [],
    },
    "duplicity": {
        "category": "data-quality",
        "description": "Dataset duplicates ratio.",
        "runner": run_duplicity,
        "required_args": [],
    },
    "outliers": {
        "category": "data-quality",
        "description": "Outlier proportions for numerical columns.",
        "runner": run_outliers,
        "required_args": [],
    },
    "correlations": {
        "category": "impact-of-data-on-AI",
        "description": "Categorical and numerical correlation matrices.",
        "runner": run_correlations,
        "required_args": ["columns"],
    },
    "feature_relevance": {
        "category": "impact-of-data-on-AI",
        "description": "Feature relevance to target.",
        "runner": run_feature_relevance,
        "required_args": ["cat-columns", "num-columns", "target-column"],
    },
    "class_imbalance": {
        "category": "fairness-and-bias",
        "description": "Class imbalance degree.",
        "runner": run_class_imbalance,
        "required_args": ["target-column"],
    },
    "statistical_rates": {
        "category": "fairness-and-bias",
        "description": "Statistical rates across sensitive groups.",
        "runner": run_statistical_rates,
        "required_args": ["y-true-column", "sensitive-attribute-column"],
    },
    "representation_rate": {
        "category": "fairness-and-bias",
        "description": "Representation rate ratios for categorical values.",
        "runner": run_representation_rate,
        "required_args": ["columns"],
    },
    "k_anonymity": {
        "category": "data-governance",
        "description": "k-anonymity score.",
        "runner": run_k_anonymity,
        "required_args": ["quasi-identifiers"],
    },
    "l_diversity": {
        "category": "data-governance",
        "description": "l-diversity score.",
        "runner": run_l_diversity,
        "required_args": ["quasi-identifiers", "sensitive-column"],
    },
    "t_closeness": {
        "category": "data-governance",
        "description": "t-closeness score.",
        "runner": run_t_closeness,
        "required_args": ["quasi-identifiers", "sensitive-column"],
    },
    "entropy_risk": {
        "category": "data-governance",
        "description": "Entropy risk score.",
        "runner": run_entropy_risk,
        "required_args": ["quasi-identifiers"],
    },
    "single_attribute_risk": {
        "category": "data-governance",
        "description": "Single attribute Markov-model risk scores.",
        "runner": run_single_attribute_risk,
        "required_args": ["id-column", "eval-columns"],
    },
    "multiple_attribute_risk": {
        "category": "data-governance",
        "description": "Multiple attribute Markov-model risk scores.",
        "runner": run_multiple_attribute_risk,
        "required_args": ["id-column", "eval-columns"],
    },
    "differential_privacy": {
        "category": "data-governance",
        "description": "Differentially private noise statistics for selected columns.",
        "runner": run_differential_privacy,
        "required_args": ["columns", "epsilon"],
    },
}


def _sanitize(obj: Any) -> Any:
    """Recursively convert numpy scalars/arrays to native Python types."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _normalize_list(value: Optional[Any]) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value).strip()]


def list_custom_metrics(custom_dir: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Return metadata for custom modules, split into metrics and remedies."""
    target_dir = custom_dir or os.path.join(os.getcwd(), "aidrin/custom_metrics")
    if not os.path.isdir(target_dir):
        return {"custom_metrics": [], "custom_remedies": []}

    metrics: List[Dict[str, Any]] = []
    remedies: List[Dict[str, Any]] = []
    for filename in os.listdir(target_dir):
        if (
            not filename.endswith(".py")
            or filename in {"__init__.py", "base_dr.py"}
            or filename.startswith("_")
        ):
            continue
        name = filename[:-3]
        display_name = name.replace("_", "-")
        metrics.append({
            "name": display_name,
            "description": "Custom metric defined in aidrin/custom_metrics. Run with: aidrin run custom <name> <file> metric",
            "required_args": [],
        })
        remedies.append({
            "name": display_name,
            "description": "Custom remedy defined in aidrin/custom_metrics. Run with: aidrin run custom <name> <file> remedy",
            "required_args": [],
        })
    return {"custom_metrics": metrics, "custom_remedies": remedies}


def list_available_metrics(category: Optional[str] = None) -> List[Dict[str, Any]]:
    results = {}

    for name, meta in METRIC_REGISTRY.items():
        metric_category = meta["category"]

        # Filter by category if requested
        if category and metric_category != category:
            continue

        # Initialize the category list if it doesn't exist
        if metric_category not in results:
            results[metric_category] = []

        arg_map = {
            "cat-columns": "categorical-columns",
            "num-columns": "numerical-columns",
            "y-true-column": "target-column",
        }
        raw_args = list(meta.get("required_args", []))
        display_args = [arg_map.get(arg, arg) for arg in raw_args]

        results[metric_category].append({
            "name": name.replace("_", "-"),
            "description": meta["description"],
            "required_args": display_args
        })

    # Append custom metrics under their own category unless filtered out
    custom = list_custom_metrics()
    if (category is None or category == "custom_metrics") and custom["custom_metrics"]:
        results["custom_metrics"] = custom["custom_metrics"]
    if (category is None or category == "custom_remedies") and custom["custom_remedies"]:
        results["custom_remedies"] = custom["custom_remedies"]

    return results


def get_metric_info(name: str) -> Dict[str, Any]:
    metric = METRIC_REGISTRY.get(name)
    if not metric:
        raise ValueError(f"Unknown metric: {name}")
    return {
        "name": name,
        "category": metric["category"],
        "description": metric["description"],
        "required_args": list(metric.get("required_args", [])),
    }


def _safe_slug(value: str) -> str:
    value = value.strip().lower().replace(" ", "_")
    value = re.sub(r"[^a-z0-9_.-]+", "_", value)
    return value.strip("_") or "image"


def _strip_visualizations(result: Any) -> Any:
    """Recursively strip visualization (and descriptive-only) data from results."""
    EXCLUDED_KEYS = {
        "visualization",
        "graph interpretation",
        "plot_data",
        "histogram_data",
        "descriptive_statistics",
        "plot",
    }

    if isinstance(result, dict):
        return {
            k: _strip_visualizations(v)
            for k, v in result.items()
            if not (isinstance(k, str) and any(key in k.lower() for key in EXCLUDED_KEYS))
        }

    # Handle lists (e.g., if a metric returns a list of dictionaries)
    if isinstance(result, list):
        return [_strip_visualizations(item) for item in result]

    return result


def _log_progress(message: str, verbose: bool) -> None:
    """Print progress message if verbose mode is enabled."""
    if verbose:
        sys.stderr.write(f"[aidrin] {message}\n")
        sys.stderr.flush()


def _maybe_save_images(
    metric_name: str,
    result: Any,
    save_images: bool,
    image_dir: Optional[str],
) -> Any:
    if not save_images or not isinstance(result, dict):
        return result

    target_dir = image_dir or os.path.join("/tmp", "aidrin_images")
    os.makedirs(target_dir, exist_ok=True)

    updated: Dict[str, Any] = {}
    for key, value in result.items():
        if (
            isinstance(key, str)
            and isinstance(value, str)
            and "visualization" in key.lower()
            and value.strip()
        ):
            filename = f"{_safe_slug(metric_name)}_{_safe_slug(key)}.png"
            path = os.path.join(target_dir, filename)
            try:
                with open(path, "wb") as handle:
                    handle.write(base64.b64decode(value))
                updated[key] = path
            except Exception:
                updated[key] = value
        else:
            updated[key] = value
    return updated


def run_metric(
    metric_name: str,
    file_path: str,
    file_type: Optional[str] = None,
    file_name: Optional[str] = None,
    save_images: bool = True,
    image_dir: Optional[str] = None,
    verbose: bool = False,
    strip_visualizations: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    metric_key = metric_name.strip().lower()
    metric = METRIC_REGISTRY.get(metric_key)
    if not metric:
        # Try resolving as a custom metric
        try:
            _log_progress(f"Running custom metric: {metric_key}...", verbose)
            start_time = time.time()
            result = run_custom_metric_logic(metric_key, file_path, **kwargs)
            result = _maybe_save_images(metric_key, result, save_images, image_dir)
            if strip_visualizations:
                result = _strip_visualizations(result)
            elapsed = time.time() - start_time
            _log_progress(f"  {metric_key} completed in {elapsed:.2f}s", verbose)
            return _sanitize(result)
        except FileNotFoundError:
            raise ValueError(f"Unknown metric: {metric_name}") from None

    _log_progress(f"Running {metric_key}...", verbose)
    start_time = time.time()

    if metric_key in {"completeness", "duplicity", "outliers"}:
        result = metric["runner"](file_path, file_type, file_name)
        result = _maybe_save_images(metric_key, result, save_images, image_dir)
        if strip_visualizations:
            result = _strip_visualizations(result)
        elapsed = time.time() - start_time
        _log_progress(f"  {metric_key} completed in {elapsed:.2f}s", verbose)
        return _sanitize(result)

    def _finalize(result: Dict[str, Any]) -> Dict[str, Any]:
        """Apply post-processing: save images, strip visualizations, sanitize types."""
        result = _maybe_save_images(metric_key, result, save_images, image_dir)
        if strip_visualizations:
            result = _strip_visualizations(result)
        elapsed = time.time() - start_time
        _log_progress(f"  {metric_key} completed in {elapsed:.2f}s", verbose)
        return _sanitize(result)

    if metric_key == "correlations":
        columns = _normalize_list(kwargs.get("columns"))
        if not columns:
            raise ValueError("columns is required for correlations")
        result = metric["runner"](file_path, file_type, file_name, columns)
        return _finalize(result)

    if metric_key == "feature_relevance":
        cat_columns = _normalize_list(kwargs.get("cat_columns")) or []
        num_columns = _normalize_list(kwargs.get("num_columns")) or []
        target_column = kwargs.get("target_column")
        if not target_column:
            raise ValueError("target_column is required for feature_relevance")
        if not cat_columns and not num_columns:
            raise ValueError("cat_columns or num_columns must be provided")
        result = metric["runner"](
            file_path, file_type, file_name, cat_columns, num_columns, target_column
        )
        return _finalize(result)

    if metric_key == "class_imbalance":
        target_column = kwargs.get("target_column")
        if not target_column:
            raise ValueError("target_column is required for class_imbalance")
        distance_metric = kwargs.get("distance_metric")
        result = metric["runner"](
            file_path, file_type, file_name, target_column, distance_metric
        )
        return _finalize(result)

    if metric_key == "statistical_rates":
        y_true_column = kwargs.get("y_true_column") or kwargs.get("target_column")
        sensitive_attribute_column = (
            kwargs.get("sensitive_attribute_column") or kwargs.get("sensitive_column")
        )
        if not y_true_column or not sensitive_attribute_column:
            raise ValueError(
                "y_true_column and sensitive_attribute_column are required for statistical_rates"
            )
        result = metric["runner"](
            file_path,
            file_type,
            file_name,
            y_true_column,
            sensitive_attribute_column,
        )
        return _finalize(result)

    if metric_key == "representation_rate":
        columns = _normalize_list(kwargs.get("columns"))
        if not columns:
            raise ValueError("columns is required for representation_rate")
        result = metric["runner"](file_path, file_type, file_name, columns)
        return _finalize(result)

    if metric_key in {"k_anonymity", "entropy_risk"}:
        quasi_identifiers = _normalize_list(kwargs.get("quasi_identifiers"))
        if not quasi_identifiers:
            raise ValueError("quasi_identifiers is required")
        result = metric["runner"](file_path, file_type, file_name, quasi_identifiers)
        return _finalize(result)

    if metric_key in {"l_diversity", "t_closeness"}:
        quasi_identifiers = _normalize_list(kwargs.get("quasi_identifiers"))
        sensitive_column = kwargs.get("sensitive_column")
        if not quasi_identifiers or not sensitive_column:
            raise ValueError("quasi_identifiers and sensitive_column are required")
        result = metric["runner"](
            file_path, file_type, file_name, quasi_identifiers, sensitive_column
        )
        return _finalize(result)

    if metric_key in {"single_attribute_risk", "multiple_attribute_risk"}:
        id_column = kwargs.get("id_column")
        eval_columns = _normalize_list(kwargs.get("eval_columns"))
        if not id_column or not eval_columns:
            raise ValueError("id_column and eval_columns are required")
        result = metric["runner"](
            file_path, file_type, file_name, id_column, eval_columns
        )
        return _finalize(result)

    if metric_key == "differential_privacy":
        columns = _normalize_list(kwargs.get("columns"))
        epsilon = kwargs.get("epsilon")
        if not columns or epsilon is None:
            raise ValueError("columns and epsilon are required for differential_privacy")
        result = metric["runner"](file_path, file_type, file_name, columns, epsilon)
        return _finalize(result)

    raise ValueError(f"Unsupported metric: {metric_name}")


def run_batch_metrics(
    config: Any,
    verbose: bool = False,
    strip_visualizations: bool = False,
) -> Dict[str, Any]:
    if isinstance(config, dict):
        config_obj = HeadlessConfig.from_dict(config)
    elif isinstance(config, HeadlessConfig):
        config_obj = config
    else:
        raise ValueError("config must be a HeadlessConfig or dict")

    metrics = config_obj.metrics or []
    if not metrics:
        raise ValueError("metrics must be provided for batch runs")

    _log_progress(f"Running {len(metrics)} metrics on {config_obj.file_path}", verbose)

    payload = {
        "columns": config_obj.columns,
        "target_column": config_obj.target_column,
        "quasi_identifiers": config_obj.quasi_identifiers,
        "sensitive_column": config_obj.sensitive_column,
        "epsilon": config_obj.epsilon,
        "id_column": config_obj.id_column,
        "eval_columns": config_obj.eval_columns,
        "distance_metric": config_obj.distance_metric,
        "cat_columns": config_obj.cat_columns,
        "num_columns": config_obj.num_columns,
        "y_true_column": config_obj.y_true_column,
        "sensitive_attribute_column": config_obj.sensitive_attribute_column,
        "save_images": bool(config_obj.save_images) if config_obj.save_images is not None else True,
        "image_dir": config_obj.image_dir,
        "verbose": verbose,
        "strip_visualizations": strip_visualizations,
    }

    results: Dict[str, Any] = {}
    for metric_name in metrics:
        results[metric_name] = run_metric(
            metric_name,
            config_obj.file_path,
            file_type=config_obj.file_type,
            file_name=config_obj.file_name,
            **payload,
        )
    return results


def run_data_quality(
    file_path: str,
    file_type: Optional[str] = None,
    file_name: Optional[str] = None,
    verbose: bool = False,
    strip_visualizations: bool = True,
) -> Dict[str, Any]:
    """Run fast data quality metrics (completeness, duplicity, outliers).

    This is the recommended function for quick data quality assessment.
    Visualizations are stripped by default for faster output.
    """
    return run_batch_metrics(
        HeadlessConfig(
            file_path=file_path,
            file_type=file_type,
            file_name=file_name,
            metrics=["completeness", "duplicity", "outliers"],
            save_images=False,
        ),
        verbose=verbose,
        strip_visualizations=strip_visualizations,
    )


# Alias for backwards compatibility
run_all_data_quality = run_data_quality


def run_privacy_assessment(
    file_path: str,
    file_type: Optional[str] = None,
    file_name: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    config = HeadlessConfig(
        file_path=file_path,
        file_type=file_type,
        file_name=file_name,
        metrics=[
            "k_anonymity",
            "l_diversity",
            "t_closeness",
            "entropy_risk",
            "single_attribute_risk",
            "multiple_attribute_risk",
            "differential_privacy",
        ],
    )
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return run_batch_metrics(config)


def generate_metric_template(metric_name: str, target_dir: str) -> str:
    """Creates the directory and the .py file with the CustomDR template."""
    # 1. Prepare directory
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
        # Create __init__.py so the folder is a searchable python package
        with open(os.path.join(target_dir, "__init__.py"), "w") as f:
            f.write("# Aidrin Custom Metrics Package\n")

    # 2. Sanitize filename (e.g., "My Metric!!" -> "my_metric.py")
    clean_name = metric_name.strip().lower().replace(" ", "_")
    clean_name = re.sub(r"[^a-z0-9_]+", "", clean_name)
    file_path = os.path.join(target_dir, f"{clean_name}.py")

    if os.path.exists(file_path):
        raise FileExistsError(f"A metric file named '{clean_name}.py' already exists in {target_dir}. Edit that file or choose a different name.")

    # 3. The Class Template
    content = """from aidrin.custom_metrics.base_dr import BaseDRAgent
from typing import Any
from typing import Dict, Union, Any
import pandas as pd

class CustomDR(BaseDRAgent):
    def __init__(self, dataset: Any, **kwargs):
        super().__init__(dataset, **kwargs)

    def metric(self, **kwargs):
        \"\"\"
        Implement your custom metric logic here.
        \"\"\"

        # IMPLEMENT YOUR METRIC LOGIC BELOW
        # Example: Calculating the total number of missing cells in the entire DataFrame

        # df: pd.DataFrame = self.dataset
        # return {
        #     "total_missing_cells": df.isna().sum().to_dict()
        # }

        return {"message": "Placeholder metric. Implement your logic here."}

    def remedy(self, **kwargs) -> pd.DataFrame:
        \"\"\"
        Apply remediation steps to the dataset and return a pandas DataFrame.
        \"\"\"

        # df: pd.DataFrame = self.dataset.copy()
        # TODO: implement remediation logic and return the modified DataFrame
        # Example:
        # df = df.fillna(0)
        # return df

        return self.dataset
    """

    with open(file_path, "w") as f:
        f.write(content)

    return file_path


def _find_script_in_dir(directory: str, stem: str) -> Optional[str]:
    """Return the path to <stem>.py in directory, case-insensitively."""
    target = f"{stem}.py".lower()
    try:
        for entry in os.listdir(directory):
            if entry.lower() == target:
                return os.path.join(directory, entry)
    except FileNotFoundError:
        pass
    return None


def _resolve_custom_script(metric_name: str) -> str:
    """Resolve a custom metric name or path to an absolute .py file path.

    Resolution order:
    1. If metric_name ends with .py or contains a path separator — treat as a direct path.
    2. Check the current working directory for <name>.py (case-insensitive).
    3. Fall back to aidrin/custom_metrics/<name>.py inside the current working directory.
    """
    if metric_name.endswith(".py") or os.sep in metric_name or "/" in metric_name:
        path = os.path.abspath(metric_name)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Custom metric file not found: {metric_name}")
        return path

    clean_name = _safe_slug(metric_name)
    cwd = os.getcwd()

    path = _find_script_in_dir(cwd, clean_name)
    if path:
        return path

    path = _find_script_in_dir(os.path.join(cwd, "aidrin", "custom_metrics"), clean_name)
    if path:
        return path

    raise FileNotFoundError(
        f"Custom metric '{clean_name}' not found in the current directory or aidrin/custom_metrics/. "
        f"Pass a full path (e.g. aidrin run custom /path/to/{clean_name}.py ...) "
        f"or run from the directory containing {clean_name}.py."
    )


def run_custom_metric_logic(metric_name: str, file_path: str, **kwargs) -> Dict[str, Any]:
    """
    Dynamically loads and executes a CustomDR class from any directory.
    """
    script_path = _resolve_custom_script(metric_name)
    clean_name = os.path.splitext(os.path.basename(script_path))[0]

    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Custom metric file not found at: {script_path}")

    # 1. Dynamic Import
    spec = importlib.util.spec_from_file_location(clean_name, script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "CustomDR"):
        raise AttributeError(f"Class 'CustomDR' not found in {script_path}")

    # 2. Load Dataset
    # You can expand this to support parquet/json as needed
    _log_progress(f"Loading dataset: {file_path}", kwargs.get("verbose", False))
    df = pd.read_csv(file_path)

    # 3. Instantiate and Run
    agent = module.CustomDR(dataset=df, **kwargs)

    _log_progress(f"Executing custom metric: {metric_name}", kwargs.get("verbose", False))
    results = agent.metric(**kwargs)

    if not isinstance(results, dict):
        raise TypeError(
            f"metric() in '{script_path}' must return a dict, got {type(results).__name__}"
        )

    return results


def run_custom_metric_remedy(metric_name: str, file_path: str, *, output_dir: Optional[str] = None, **kwargs) -> str:
    """Execute `remedy` on a custom metric and save the returned DataFrame as CSV."""
    script_path = _resolve_custom_script(metric_name)
    clean_name = os.path.splitext(os.path.basename(script_path))[0]

    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Custom metric file not found at: {script_path}")

    spec = importlib.util.spec_from_file_location(clean_name, script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "CustomDR"):
        raise AttributeError(f"Class 'CustomDR' not found in {script_path}")

    _log_progress(f"Loading dataset for remedy: {file_path}", kwargs.get("verbose", False))
    df = pd.read_csv(file_path)

    agent = module.CustomDR(dataset=df, **kwargs)
    if not hasattr(agent, "remedy"):
        raise AttributeError("CustomDR must implement a remedy method returning a pandas DataFrame")

    _log_progress(f"Executing remedy for custom metric: {metric_name}", kwargs.get("verbose", False))
    remedied = agent.remedy(**kwargs)

    if not isinstance(remedied, pd.DataFrame):
        raise TypeError("remedy() must return a pandas DataFrame")

    target_dir = output_dir or os.path.join(os.path.dirname(script_path), "remedy_data")
    os.makedirs(target_dir, exist_ok=True)
    filename = f"{clean_name}_remedy.csv"
    output_path = os.path.join(target_dir, filename)
    remedied.to_csv(output_path, index=False)

    return output_path
