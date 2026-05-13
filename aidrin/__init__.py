from aidrin._version import __version__


def _eager_celery():
    """Return a minimal always-eager Celery app for standalone (non-web) use.

    The app is created lazily and cached so that a plain ``import aidrin``
    does not spin up Celery infrastructure.
    """
    if not hasattr(_eager_celery, "_app"):
        from celery import Celery
        app = Celery("aidrin_standalone")
        app.conf.update(task_always_eager=True, task_eager_propagates=True)
        app.set_default()
        _eager_celery._app = app
    return _eager_celery._app


# ---------------------------------------------------------------------------
# Data Quality
# ---------------------------------------------------------------------------

def calculate_completeness(file_info):
    """Evaluate completeness (missing-value rates) for each column.

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)`` — same format used throughout
        the rest of the library (e.g. ``("/data/adult.csv", "adult.csv", ".csv")``).

    Returns
    -------
    dict
        ``{"Completeness scores": {col: float}, "Overall Completeness": float,
        "Completeness Visualization": base64_str}``
    """
    _eager_celery()
    from aidrin.structured_data_metrics.completeness import completeness
    return completeness.apply(args=(file_info,)).get()


def calculate_duplicates(file_info):
    """Measure the proportion of duplicate rows in the dataset.

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)``

    Returns
    -------
    dict
        ``{"Duplicity scores": {"Overall duplicity of the dataset": float}}``
    """
    _eager_celery()
    from aidrin.structured_data_metrics.duplicity import duplicity
    return duplicity.apply(args=(file_info,)).get()


def calculate_outliers(file_info):
    """Detect outliers in numerical columns using the IQR method.

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)``

    Returns
    -------
    dict
        ``{"Outlier scores": {col: float, "Overall outlier score": float},
        "Outliers Visualization": base64_str}``
    """
    _eager_celery()
    from aidrin.structured_data_metrics.outliers import outliers
    return outliers.apply(args=(file_info,)).get()


# ---------------------------------------------------------------------------
# Fairness / Bias
# ---------------------------------------------------------------------------

def calculate_class_distribution(column, file_info):
    """Quantify class imbalance for a categorical target column.

    Computes the Imbalance Degree score and a pie-chart visualisation.

    Parameters
    ----------
    column : str
        Target column name.
    file_info : tuple
        ``(file_path, file_name, file_type)``

    Returns
    -------
    dict
        ``{"Imbalance Degree score": float, "Description": str,
        "Class Distribution Visualization": base64_str}``
        or ``{"Error": str}`` on validation failure.
    """
    _eager_celery()
    from aidrin.file_handling.file_parser import read_file
    from aidrin.structured_data_metrics.class_imbalance import (
        calc_imbalance_degree,
        class_distribution_plot,
    )
    df = read_file(file_info)
    result = calc_imbalance_degree(df, column)
    if "Error" not in result:
        try:
            result["Class Distribution Visualization"] = class_distribution_plot(df, column)
        except Exception as e:
            result["Class Distribution Visualization Error"] = str(e)
    return result


def calculate_representation_rate(columns, file_info):
    """Calculate pairwise representation rates for sensitive attribute columns.

    Parameters
    ----------
    columns : list of str
        Column names to analyse.
    file_info : tuple
        ``(file_path, file_name, file_type)``

    Returns
    -------
    dict
        Probability ratios for each pair of attribute values per column.
    """
    _eager_celery()
    from aidrin.structured_data_metrics.representation_rate import (
        calculate_representation_rate as _fn,
    )
    return _fn.apply(args=(columns, file_info)).get()


def calculate_statistical_rates(sensitive_attribute_column, y_true_column, file_info):
    """Compute class proportions per sensitive attribute group (TSD scores).

    Parameters
    ----------
    sensitive_attribute_column : str
        Column defining demographic groups.
    y_true_column : str
        Column containing class labels.
    file_info : tuple
        ``(file_path, file_name, file_type)``

    Returns
    -------
    dict
        ``{"Statistical Rates": dict, "TSD scores": dict,
        "Statistical Rate Visualization": base64_str}``
    """
    _eager_celery()
    from aidrin.structured_data_metrics.statistical_rate import (
        calculate_statistical_rates as _fn,
    )
    return _fn.apply(args=(y_true_column, sensitive_attribute_column, file_info)).get()


# ---------------------------------------------------------------------------
# Impact on AI
# ---------------------------------------------------------------------------

def calculate_correlations(columns, file_info):
    """Compute pairwise correlations (Pearson/Spearman + Theil's U).

    Parameters
    ----------
    columns : list of str
        Columns to include in the correlation analysis.
    file_info : tuple
        ``(file_path, file_name, file_type)``

    Returns
    -------
    dict
        Numerical and categorical correlation scores plus a heatmap visualisation.
    """
    _eager_celery()
    from aidrin.structured_data_metrics.correlation_score import calc_correlations
    return calc_correlations.apply(args=(columns, file_info)).get()


def calculate_feature_relevance(file_info, target_col, cat_cols=None, num_cols=None):
    """Assess feature relevance relative to a target column.

    Categorical features are one-hot encoded; Pearson correlation is then
    computed between each feature and the target.

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)``
    target_col : str
        Target column name.
    cat_cols : list of str, optional
        Categorical column names. Inferred from the data when omitted.
    num_cols : list of str, optional
        Numerical column names. Inferred from the data when omitted.

    Returns
    -------
    dict
        Feature importance scores and a bar-chart visualisation.
    """
    _eager_celery()
    import pandas as pd
    from aidrin.file_handling.file_parser import read_file
    from aidrin.structured_data_metrics.feature_relevance import (
        data_cleaning,
        pearson_correlation,
        plot_features,
    )

    if cat_cols is None or num_cols is None:
        df = read_file(file_info)
        if cat_cols is None:
            cat_cols = [
                c for c, d in df.dtypes.items()
                if pd.api.types.is_string_dtype(d) and c != target_col
            ]
        if num_cols is None:
            num_cols = [
                c for c, d in df.dtypes.items()
                if pd.api.types.is_numeric_dtype(d) and c != target_col
            ]

    df_json = data_cleaning.apply(args=(cat_cols, num_cols, target_col, file_info)).get()
    if isinstance(df_json, dict) and "Error" in df_json:
        return df_json

    correlations = pearson_correlation.apply(args=(df_json, target_col)).get()
    if isinstance(correlations, dict) and "Error" in correlations:
        return correlations

    visualization = plot_features.apply(args=(correlations, target_col)).get()
    return {
        "Feature Relevance scores": correlations,
        "Feature Relevance Visualization": visualization,
    }


# ---------------------------------------------------------------------------
# Privacy / Data Governance
# ---------------------------------------------------------------------------

def compute_k_anonymity(quasi_identifiers, file_info):
    """Measure k-anonymity for the given quasi-identifier columns.

    Parameters
    ----------
    quasi_identifiers : list of str
        Columns that together form the quasi-identifier.
    file_info : tuple or pd.DataFrame
        ``(file_path, file_name, file_type)`` tuple **or** a DataFrame directly.

    Returns
    -------
    dict
        ``{"k-Value": int, "descriptive_statistics": dict,
        "k-Anonymity Visualization": base64_str}``
    """
    from aidrin.structured_data_metrics.privacy_measure import (
        compute_k_anonymity as _fn,
    )
    return _fn(quasi_identifiers, file_info)


def compute_l_diversity(quasi_identifiers, sensitive_column, file_info):
    """Quantify l-diversity within groups defined by quasi-identifiers.

    Parameters
    ----------
    quasi_identifiers : list of str
    sensitive_column : str
    file_info : tuple or pd.DataFrame

    Returns
    -------
    dict
        ``{"l-Value": int, "descriptive_statistics": dict,
        "l-Diversity Visualization": base64_str}``
    """
    from aidrin.structured_data_metrics.privacy_measure import (
        compute_l_diversity as _fn,
    )
    return _fn(quasi_identifiers, sensitive_column, file_info)


def compute_t_closeness(quasi_identifiers, sensitive_column, file_info):
    """Measure t-closeness between group and global sensitive attribute distributions.

    Parameters
    ----------
    quasi_identifiers : list of str
    sensitive_column : str
    file_info : tuple or pd.DataFrame

    Returns
    -------
    dict
        ``{"t-Value": float, "descriptive_statistics": dict,
        "t-Closeness Visualization": base64_str}``
    """
    from aidrin.structured_data_metrics.privacy_measure import (
        compute_t_closeness as _fn,
    )
    return _fn(quasi_identifiers, sensitive_column, file_info)


def compute_entropy_risk(quasi_identifiers, file_info):
    """Calculate entropy-based re-identification risk for quasi-identifier columns.

    Parameters
    ----------
    quasi_identifiers : list of str
    file_info : tuple or pd.DataFrame

    Returns
    -------
    dict
        ``{"Entropy-Value": float, "descriptive_statistics": dict,
        "Entropy Risk Visualization": base64_str}``
    """
    from aidrin.structured_data_metrics.privacy_measure import (
        compute_entropy_risk as _fn,
    )
    return _fn(quasi_identifiers, file_info)


__all__ = [
    "__version__",
    # Data Quality
    "calculate_completeness",
    "calculate_duplicates",
    "calculate_outliers",
    # Fairness / Bias
    "calculate_class_distribution",
    "calculate_representation_rate",
    "calculate_statistical_rates",
    # Impact on AI
    "calculate_correlations",
    "calculate_feature_relevance",
    # Privacy / Data Governance
    "compute_k_anonymity",
    "compute_l_diversity",
    "compute_t_closeness",
    "compute_entropy_risk",
]
