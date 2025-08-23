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
            _d = np.array(_d)
            summ = np.vectorize(lambda p: pow(p - _e, 2))(_d).sum()
            return sqrt(summ)
        except Exception:
            return None

    def _ch(_d, _e):
        # Chebyshev distance: max absolute difference
        try:
            _d = np.array(_d)
            return np.max(np.abs(_d - _e))
        except Exception:
            return None

    def _kl(_d, _e):
        # Kullback-Leibler divergence: sum(p * log(p/q)), handle 0s
        # _d: empirical, _e: equiprobability (scalar)
        try:
            _d = np.array(_d)
            q = np.full_like(_d, _e)
            # Add small epsilon to avoid log(0) issues
            epsilon = 1e-10
            _d_safe = _d + epsilon
            q_safe = q + epsilon
            # Normalize to ensure probabilities sum to 1
            _d_safe = _d_safe / _d_safe.sum()
            q_safe = q_safe / q_safe.sum()
            # Calculate KL divergence
            kl_div = np.sum(_d_safe * np.log(_d_safe / q_safe))
            return kl_div
        except Exception:
            return None

    def _he(_d, _e):
        # Hellinger distance: sqrt(0.5 * sum((sqrt(p) - sqrt(q))^2))
        try:
            _d = np.array(_d)
            q = np.full_like(_d, _e)
            return sqrt(0.5 * np.sum((np.sqrt(_d) - np.sqrt(q)) ** 2))
        except Exception:
            return None

    def _tv(_d, _e):
        # Total variation distance: 0.5 * sum(|p - q|)
        try:
            _d = np.array(_d)
            q = np.full_like(_d, _e)
            return 0.5 * np.sum(np.abs(_d - q))
        except Exception:
            return None

    def _cs(_d, _e):
        # Chi-square divergence: sum((p - q)^2 / q)
        try:
            _d = np.array(_d)
            q = np.full_like(_d, _e)
            # Add small epsilon to avoid division by zero
            epsilon = 1e-10
            q_safe = q + epsilon
            return np.sum(((_d - q) ** 2) / q_safe)
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
        return np.concatenate((min_i, maj_i, maj))

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
        # Validate input parameters
        if df is None or df.empty:
            raise ValueError("Dataset is empty or None")

        if column is None or column == "":
            raise ValueError("No target feature selected for visualization")

        if column not in df.columns:
            raise ValueError(f"Target feature '{column}' not found in the dataset")

        # Get data and handle NaN values
        column_data = df[column].dropna()
        if len(column_data) == 0:
            raise ValueError(f"No valid data found in column '{column}' after removing missing values")

        if len(column_data) < 2:
            raise ValueError(f"Column '{column}' has insufficient data for visualization (minimum 2 samples required)")

        # Calculate class frequencies
        class_counts = column_data.value_counts()

        # Check if we have any data to plot
        if len(class_counts) == 0:
            raise ValueError(f"No class data found in column '{column}'")

        # Check if we have multiple classes
        unique_classes = np.unique(column_data)
        if len(unique_classes) < 2:
            raise ValueError(f"Column '{column}' has only one class ({unique_classes[0]}). Visualization requires at least 2 different classes.")

        if len(unique_classes) > 50:
            raise ValueError(f"Column '{column}' has too many classes ({len(unique_classes)}). Visualization works best with fewer than 50 classes.")

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
        except Exception as e:
            raise Exception(f"Failed to create plot figure: {str(e)}")

        # Ensure we have valid data for pie chart
        if len(class_counts) == 0 or class_counts.sum() == 0:
            plt.close()
            raise ValueError("No valid data available for plotting")

        # Plotting a pie chart without labels
        try:
            wedges, _ = ax.pie(class_counts.values, startangle=90)
        except Exception as e:
            plt.close()
            raise Exception(f"Failed to create pie chart: {str(e)}")

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
                raise ValueError("Failed to encode plot image")
        except Exception as e:
            plt.close()
            buf.close()
            raise Exception(f"Failed to encode plot image: {str(e)}")

        # Close the plot and buffer to free up resources
        plt.close()
        buf.close()

        return plot_base64

    except SoftTimeLimitExceeded:
        raise Exception("Class Distribution Plot task timed out.")
    except ValueError as ve:
        # Re-raise validation errors
        raise ve
    except Exception as e:
        # Handle other unexpected errors
        raise Exception(f"Visualization error: {str(e)}")


# imbalance degree calculation with default distance metric to be Euclidean
def calc_imbalance_degree(df, column, dist_metric='EU'):
    res = {}

    try:
        # Validate input parameters
        if df is None or df.empty:
            raise ValueError("Dataset is empty or None")

        if column is None or column == "":
            raise ValueError("No target feature selected for class imbalance analysis")

        if column not in df.columns:
            raise ValueError(f"Target feature '{column}' not found in the dataset")

        # Check if the column has categorical data
        if df[column].dtype in ['int64', 'float64'] and df[column].nunique() > 100:
            raise ValueError(
                f"Column '{column}' appears to be numerical with too many unique values ({df[column].nunique()})."
                "Class imbalance analysis requires categorical data with fewer unique values."
            )

        # Calculate the Imbalance Degree
        classes = np.array(df[column].dropna())

        if len(classes) == 0:
            raise ValueError(f"No valid data found in column '{column}' after removing missing values")

        if len(classes) < 2:
            raise ValueError(f"Column '{column}' has insufficient data for class imbalance analysis (minimum 2 samples required)")

        # Check if we have multiple classes
        unique_classes = np.unique(classes)
        if len(unique_classes) < 2:
            raise ValueError(
                f"Column '{column}' has only one class ({unique_classes[0]})."
                "Class imbalance analysis requires at least 2 different classes."
            )

        if len(unique_classes) > 50:
            raise ValueError(
                f"Column '{column}' has too many classes ({len(unique_classes)}). "
                "Class imbalance analysis works best with fewer than 50 classes."
            )

        id = imbalance_degree(classes, dist_metric)

        if id is None:
            raise ValueError(
                f"Could not calculate imbalance degree using {dist_metric} "
                f"distance metric. This may be due to invalid data or "
                f"mathematical constraints."
            )
        else:
            res['Imbalance Degree score'] = id
            res['Description'] = (
                "The Imbalance Degree (ID) is a ratio that quantifies class "
                "imbalance by comparing the observed distribution to both "
                "uniform and perfectly skewed distributions. "
                "A value of 0 indicates perfect balance, while higher values "
                "indicate greater imbalance relative to the worst possible "
                "scenario for that number of minority classes."
            )

    except ValueError as ve:
        # Handle specific validation errors
        res["Error"] = str(ve)
        res["ErrorType"] = "Validation Error"
    except Exception as e:
        # Handle other unexpected errors
        res["Error"] = f"Processing error: {str(e)}"
        res["ErrorType"] = "Processing Error"

    return res
