import base64
import io
import warnings
from math import sqrt
from celery.exceptions import SoftTimeLimitExceeded
import numpy as np
# Configure matplotlib before importing pyplot
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend

import matplotlib.pyplot as plt  # noqa: E402


plt.ioff()  # Turn off interactive mode
warnings.filterwarnings('ignore')  # Suppress matplotlib warnings


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
            "Measuring the class-imbalance extent of multi-class problems,"
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
        try:
            summ = np.vectorize(lambda p: pow(p - _e, 2))(_d).sum()
            return sqrt(summ)
        except Exception:
            return None

    def _ch(_d, _e):
        # Chebyshev distance: max absolute difference
        return np.max(np.abs(_d - _e))

    def _kl(_d, _e):
        # Kullback-Leibler divergence: sum(p * log(p/q)), handle 0s
        # _d: empirical, _e: equiprobability (scalar)
        try:
            q = np.full_like(_d, _e)
            mask = (_d > 0) & (q > 0)
            if not np.any(mask):
                return None
            return np.sum(_d[mask] * np.log(_d[mask] / q[mask]))
        except Exception:
            return None

    def _he(_d, _e):
        # Hellinger distance: sqrt(0.5 * sum((sqrt(p) - sqrt(q))^2))
        try:
            q = np.full_like(_d, _e)
            return sqrt(0.5 * np.sum((np.sqrt(_d) - np.sqrt(q)) ** 2))
        except Exception:
            return None

    def _tv(_d, _e):
        # Total variation distance: 0.5 * sum(|p - q|)
        try:
            q = np.full_like(_d, _e)
            return 0.5 * np.sum(np.abs(_d - q))
        except Exception:
            return None

    def _cs(_d, _e):
        # Chi-square divergence: sum((p - q)^2 / q)
        try:
            q = np.full_like(_d, _e)
            return np.sum(((_d - q) ** 2) / q)
        except Exception:
            return None

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
        A numpy array with the i_m distribution.
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
        elif distance == "CH":
            return _ch
        elif distance == "KL":
            return _kl
        elif distance == "HE":
            return _he
        elif distance == "TV":
            return _tv
        elif distance == "CS":
            return _cs
        else:
            raise ValueError("Bad distance function parameter. Should be one in EU, CH, KL, HE, TV, or CS")

    _, class_counts = np.unique(classes, return_counts=True)

    # Validate input data
    if len(class_counts) == 0:
        return None

    if len(class_counts) == 1:
        return 0.0

    empirical_distribution = class_counts / class_counts.sum()
    K = len(class_counts)
    e = 1 / K
    m = _min_classes(empirical_distribution, e)
    i_m = _i_m(K, m)
    dfn = _dist_fn()

    try:
        dist_ed = dfn(empirical_distribution, e)
        dist_im = dfn(i_m, e)

        # Check if distance calculations returned None
        if dist_ed is None or dist_im is None:
            return None

        # Handle the case where empirical distribution is already uniform (perfect balance)
        if dist_ed == 0:
            return 0.0

        # Avoid division by zero
        if dist_im == 0:
            # If reference distance is 0, it means the reference distribution is uniform
            # This can happen when m=0 (no minority classes) or m=K (all classes are minority)
            # In both cases, the imbalance degree should be 0 (perfect balance)
            return 0.0

        result = (dist_ed / dist_im) + (m - 1)
        return result
    except Exception:
        return None


def class_distribution_plot(df, column):
    try:
        # Ensure column exists and has data
        if column not in df.columns:
            return ""

        # Get data and handle NaN values
        column_data = df[column].dropna()
        if len(column_data) == 0:
            return ""

        # Calculate class frequencies
        class_counts = column_data.value_counts()

        # Check if we have any data to plot
        if len(class_counts) == 0:
            return ""

        # Debug: Check if we have valid data
        if class_counts.sum() == 0:
            return ""

        # Debug: Print some info about the data
        print(f"Class distribution plot - Column: {column}, Unique values: {len(class_counts)}, Total: {class_counts.sum()}")

        # Convert labels to strings and handle truncation safely
        class_labels_modified = []
        for label in class_counts.index:
            label_str = str(label)
            if len(label_str) > 8:
                class_labels_modified.append(label_str[:9] + '...')
            else:
                class_labels_modified.append(label_str)
        # Set the figure size
        try:
            fig, ax = plt.subplots(figsize=(8, 8))
        except Exception:
            return ""

        # Ensure we have valid data for pie chart
        if len(class_counts) == 0 or class_counts.sum() == 0:
            plt.close()
            return ""

        # Plotting a pie chart without labels
        try:
            wedges, _ = ax.pie(class_counts.values, startangle=90)
        except Exception:
            plt.close()
            return ""

        # Create legend labels with class name and percentage only
        total = class_counts.sum()
        legend_labels = []
        for label, count in zip(class_labels_modified, class_counts):
            percentage = (count / total) * 100
            legend_labels.append(f'{label}: {percentage:.1f}%')

        ax.legend(wedges, legend_labels, title="Classes", loc="center left", bbox_to_anchor=(1, 0.5), fontsize=12)

        plt.title(f'Distribution of Each Class in {column}')
        plt.axis('equal')

        # Add total records as a text box below the chart
        plt.figtext(0.5, 0.01, f'Total records: {total}', ha='center', fontsize=12)

        # Save the plot to a BytesIO buffer
        buf = io.BytesIO()
        plt.tight_layout() 
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=300)
        buf.seek(0)

        # Encode the buffer to base64
        try:
            plot_base64 = base64.b64encode(buf.read()).decode('utf-8')
            if not plot_base64:
                plt.close()
                buf.close()
                return ""
        except Exception:
            plt.close()
            buf.close()
            return ""

        # Close the plot and buffer to free up resources
        plt.close()
        buf.close()

        return plot_base64
    except SoftTimeLimitExceeded:
        raise Exception("Class Distribution Plot task timed out.")
    except Exception:
        # Handle errors and return empty string for visualization
        return ""


# imbalance degree calculation with default distance metric to be Euclidean
def calc_imbalance_degree(df, column, dist_metric='EU'):
    res = {}

    try:
        # Calculate the Imbalance Degree
        classes = np.array(df[column].dropna())
        id = imbalance_degree(classes, dist_metric)

        if id is None:
            res['Error'] = (
                f"Could not calculate imbalance degree using {dist_metric} "
                f"distance metric. This may be due to invalid data or "
                f"mathematical constraints."
            )
        else:
            res['Imbalance Degree score'] = id
            res['Description'] = (
                "The Imbalance Degree (ID) is a ratio that quantifies class "
                "imbalance by comparing the observed distribution to both "
                "uniform and perfectly skewed distributions. It's calculated "
                "as: (distance from empirical to uniform) / (distance from "
                "perfectly skewed to uniform) + (number of minority classes - 1). "
                "A value of 0 indicates perfect balance, while higher values "
                "indicate greater imbalance relative to the worst possible "
                "scenario for that number of minority classes."
            )

    except Exception as e:
        # Handle errors and store the error message in the result
        res["Error"] = str(e)

    return res
