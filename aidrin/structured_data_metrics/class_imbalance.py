import base64
import io
from math import sqrt

import matplotlib.pyplot as plt
import numpy as np
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


def imbalance_degree(classes, distance="EU"):
    """
    Calculates the imbalance degree [1] of a multi-class dataset.
    This metric is an alternative for the well known imbalance ratio, which
    is only suitable for binary classification problems.

    Parameters
    ----------
    classes : list of int.
        List of classes (targets) of each instance of the dataset.
    distance : string (default: EU).
        distance or similarity function identifier. It can take the following
        values:
            - EU: Euclidean distance.
            - CH: Chebyshev distance.
            - KL: Kullback Leibler divergence.
            - HE: Hellinger distance.
            - TV: Total variation distance.
            - CS: Chi-square divergence.

    References
    ----------
    .. [1] J. Ortigosa-Hernández, I. Inza, and J. A. Lozano,
            “Measuring the class-imbalance extent of multi-class problems,”
            Pattern Recognit. Lett., 2017.
    """

    def _eu(_d, _e):
        """
        Euclidean distance from empirical distribution
        to equiprobability distribution.

        Parameters
        ----------
        _d : list of float.
            Empirical distribution of class probabilities.
        _e : float.
            Equiprobability term (1/K, where K is the number of classes).

        Returns
        -------
        distance value.
        """
        summ = np.vectorize(lambda p: pow(p - _e, 2))(_d).sum()
        return sqrt(summ)

    def _min_classes(_d, _e):
        """
        Calculates the number of minority classes. We call minority class to
        those classes with a probability lower than the equiprobability term.

        Parameters
        ----------
        _d : list of float.
            Empirical distribution of class probabilities.
        _e : float.
            Equiprobability term (1/K, where K is the number of classes).

        Returns
        -------
        Number of minority classes.
        """
        return len(_d[_d < _e])

    def _i_m(_K, _m):
        """
        Calculates the distribution showing exactly m minority classes with the
        highest distance to the equiprobability term. This distribution is
        always the same for all distance functions proposed, and is explained
        in [1].

        Parameters
        ----------
        _K : int.
            The number of classes (targets).
        _m : int.
            The number of minority classes. We call minority class to
            those classes with a probability lower than the equiprobability
            term.

        Returns
        -------
        A list with the i_m distribution.
        """
        min_i = np.zeros(_m)
        maj_i = np.ones(_K - _m - 1) * (1 / _K)
        maj = np.array([1 - (_K - _m - 1) / _K])
        return np.concatenate((min_i, maj_i, maj)).tolist()

    def _dist_fn():
        """
        Selects the distance function according to the distance parameter.

        Returns
        -------
        A distance function.
        """
        if distance == "EU":
            return _eu
        else:
            raise ValueError(
                "Bad distance function parameter. "
                + "Should be one in EU, CH, KL, HE, TV, or CS"
            )

    _, class_counts = np.unique(classes, return_counts=True)
    empirical_distribution = class_counts / class_counts.sum()
    K = len(class_counts)
    e = 1 / K
    m = _min_classes(empirical_distribution, e)
    i_m = _i_m(K, m)
    dfn = _dist_fn()
    dist_ed = dfn(empirical_distribution, e)
    return 0.0 if dist_ed == 00 else (dist_ed / dfn(i_m, e)) + (m - 1)


@shared_task(bind=True, ignore_result=False)
def class_distribution_plot(
    self: Task, column: str, file_info: dict
):
    """
    Generates a pie chart showing the distribution of each class in a specified column.

    Args:
        column (str): Column to analyze.
        file_info (dict): Info to read the file into a DataFrame.
        return_base64 (bool): If True, return chart as Base64 PNG string (for Flask/prod).
                              If False, return matplotlib Figure object (for local/PyPI use).

    Returns:
        str | matplotlib.figure.Figure: Base64 string or Figure object.
    """
    try:
        df = read_file(file_info)
        if column not in df.columns:
            raise ValueError(f"Column '{column}' not found in the dataset.")

        class_counts = df[column].dropna().value_counts()
        class_labels = class_counts.index.tolist()

        # Shorten labels > 8 characters
        class_labels_modified = [
            str(label)[:9] + "..." if len(str(label)) > 8 else str(label)
            for label in class_labels
        ]

        # Create the pie chart
        plt.figure(figsize=(8, 8))
        patches, texts, _ = plt.pie(
            class_counts,
            labels=class_labels_modified,
            startangle=90,
            autopct=lambda p: f"{p:.1f}%" if p >= 10 else None,
        )

        for text in texts:
            text.set_fontsize(12)

        plt.title(f"Distribution of Each Class in '{column}'")
        plt.axis("equal")
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        plot_base64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()
        plt.close()
        return plot_base64

    except SoftTimeLimitExceeded:
        raise Exception("Class Distribution Plot task timed out.")
    except Exception as e:
        return f"Error: {str(e)}"

# imbalance degree calculation with default distance metric to be Euclidean


@shared_task(bind=True, ignore_result=False)
def calculate_imbalance_degree(self: Task, column, file_info, dist_metric="EU"):
    df = read_file(file_info)
    res = {}

    try:
        # Calculate the Imbalance Degree
        classes = np.array(df[column].dropna())
        id = imbalance_degree(classes, dist_metric)

        res["Imbalance degree score"] = id
        res["Description"] = (
            "The Imbalance Degree (ID) is a metric that quantifies class imbalance in "
            "datasets by comparing the observed class distribution to an idealized balanced "
            "state. A value of 0 indicates perfect balance, while higher values signify increased "
            "dissimilarity and greater imbalance. Calculated using a distance or similarity function,"
            " ID provides a concise measure for understanding and addressing challenges posed by uneven "
            "class representation in machine learning datasets."
        )

    except (TimeoutError, SoftTimeLimitExceeded):
        raise Exception("Calculate Imbalance Degree task timed out.")
    except Exception as e:
        # Handle errors and store the error message in the result
        res["Error"] = str(e)

    return res


def calculate_class_distribution(column: str, file_info: dict, dist_metric: str = "EU"):
    """
    Analyzes class distribution and imbalance degree for a given column in a dataset.

    Args:
        column (str): Column name to analyze.
        file_info (dict): Information to read the file into a DataFrame.
        dist_metric (str): Distance metric for imbalance degree calculation (default "EU" = Euclidean).

    Returns:
        dict: {
            'imbalance_degree_score': float,
            'imbalance_description': str,
            'class_distribution_plot': matplotlib.figure.Figure,
        }

    Raises:
        ValueError: If the column is not found in the dataset.
    """
    df = read_file(file_info)
    if column not in df.columns:
        raise ValueError(f"Column '{column}' not found in dataset.")

    class_counts = df[column].dropna().value_counts()
    class_labels = class_counts.index.tolist()

    # Shorten long labels
    class_labels_modified = [
        str(label)[:9] + "..." if len(str(label)) > 8 else str(label)
        for label in class_labels
    ]

    # Calculate imbalance degree
    classes = np.array(df[column].dropna())
    imbalance_score = imbalance_degree(classes, dist_metric)

    description = (
        "The Imbalance Degree (ID) quantifies class imbalance in datasets by comparing "
        "the observed class distribution to an idealized balanced state. A value of 0 "
        "indicates perfect balance; higher values signify increased imbalance. "
        "Calculated using a distance or similarity function."
    )

    # Create pie chart figure
    fig, ax = plt.subplots(figsize=(8, 8))
    patches, texts, _ = ax.pie(
        class_counts,
        labels=class_labels_modified,
        startangle=90,
        autopct=lambda p: f"{p:.1f}%" if p >= 10 else None,
    )
    for text in texts:
        text.set_fontsize(12)

    ax.set_title(f"Distribution of Each Class in '{column}'")
    ax.axis("equal")
    plt.tight_layout()
    plt.show()

    return {
        "imbalance_degree_score": imbalance_score,
        "imbalance_description": description,
    }
