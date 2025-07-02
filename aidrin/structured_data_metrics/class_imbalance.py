import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import io
import base64
from math import sqrt, log

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
            summ = np.vectorize(lambda p : pow(p - _e, 2))(_d).sum()
            return sqrt(summ)
        except Exception as e:
            print(f"Error in Euclidean distance calculation: {e}")
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
                print("Warning: No valid values for KL divergence calculation (all probabilities are zero)")
                return None
            print(_d)
            print(_e)
            print(np.sum(_d[mask] * np.log(_d[mask] / q[mask])))
            print()
            return np.sum(_d[mask] * np.log(_d[mask] / q[mask]))
        except Exception as e:
            print(f"Error in KL divergence calculation: {e}")
            return None
    def _he(_d, _e):
        # Hellinger distance: sqrt(0.5 * sum((sqrt(p) - sqrt(q))^2))
        try:
            q = np.full_like(_d, _e)
            return sqrt(0.5 * np.sum((np.sqrt(_d) - np.sqrt(q)) ** 2))
        except Exception as e:
            print(f"Error in Hellinger distance calculation: {e}")
            return None
    def _tv(_d, _e):
        # Total variation distance: 0.5 * sum(|p - q|)
        try:
            q = np.full_like(_d, _e)
            return 0.5 * np.sum(np.abs(_d - q))
        except Exception as e:
            print(f"Error in Total Variation distance calculation: {e}")
            return None
    def _cs(_d, _e):
        # Chi-square divergence: sum((p - q)^2 / q)
        try:
            q = np.full_like(_d, _e)
            return np.sum((( _d - q) ** 2) / q)
        except Exception as e:
            print(f"Error in Chi-squared distance calculation: {e}")
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
        Number of minority clases.
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
        try:
            # Handle edge cases
            if _m == 0:
                # No minority classes, return equiprobability
                return np.array([1/_K] * _K)
            elif _m == _K:
                # All classes are minority, return equiprobability
                return np.array([1/_K] * _K)
            
            # Standard case: m minority classes with zero probability
            min_i = np.zeros(_m)
            maj_i = np.ones((_K - _m - 1)) * (1 / _K)
            maj = np.array([1 - (_K - _m - 1) / _K])
            result = np.concatenate((min_i, maj_i, maj))
            
            # Ensure the distribution sums to 1
            if abs(np.sum(result) - 1.0) > 1e-10:
                # Normalize if needed
                result = result / np.sum(result)
            
            return result
        except Exception as e:
            print(f"Error in _i_m calculation: {e}")
            # Return equiprobability distribution as fallback
            return np.array([1/_K] * _K)
    
    def _dist_fn():
        """
        Selects the distance function according to the distance paramenter.
        
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
        print("Error: No classes found in the data")
        return None
    
    if len(class_counts) == 1:
        print("Warning: Only one class found, imbalance degree is 0")
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
            print(f"Warning: Distance calculation returned None for {distance} metric")
            return None
            
        # Avoid division by zero
        if dist_im == 0:
            print(f"Warning: Reference distance is zero for {distance} metric, cannot compute imbalance degree")
            return None
            
        result = 0.0 if dist_ed == 0 else (dist_ed / dist_im) + (m - 1)
        return result
    except Exception as e:
        print(f"Error in imbalance degree calculation for {distance} metric: {e}")
        return None

def class_distribution_plot(df, column):
    plot_res = {}
    try:
        # Get unique class labels
        class_labels = df[column].dropna().unique()

        # Calculate class frequencies
        class_counts = df[column].dropna().value_counts()
        class_labels_modified = [label[:9] + '...' if len(label) > 8 else label for label in class_counts.index]
        # Set the figure size
        fig, ax = plt.subplots(figsize=(8, 8))

        # Plotting a pie chart without labels
        wedges, _ = ax.pie(class_counts, startangle=90)

        # Create legend labels with class name and percentage only
        total = class_counts.sum()
        legend_labels = [f'{label}: {count/total:.1%}' for label, count in zip(class_labels_modified, class_counts)]
        ax.legend(wedges, legend_labels, title="Classes", loc="center left", bbox_to_anchor=(1, 0.5), fontsize=12)

        plt.title(f'Distribution of Each Class in {column}')
        plt.axis('equal')

        # Add total records as a text box below the chart
        plt.figtext(0.5, 0.01, f'Total records: {total}', ha='center', fontsize=12)

        # Save the plot to a BytesIO buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)

        # Encode the buffer to base64
        plot_base64 = base64.b64encode(buf.read()).decode('utf-8')

        # Close the plot and buffer to free up resources
        plt.close()
        buf.close()

        return plot_base64

    except Exception as e:
        # Handle errors and store the error message in the result
        return str(e)

#imbalance degree calculation with default distance metric to be Euclidean
def calc_imbalance_degree(df, column, dist_metric='EU'):
    res = {}

    try:
        # Calculate the Imbalance Degree
        classes = np.array(df[column].dropna())
        id = imbalance_degree(classes, dist_metric)

        if id is None:
            res['Error'] = f"Could not calculate imbalance degree using {dist_metric} distance metric. This may be due to invalid data or mathematical constraints."
        else:
            res['Imbalance Degree score'] = id
            res['Description'] = "The Imbalance Degree (ID) is a ratio that quantifies class imbalance by comparing the observed distribution to both uniform and perfectly skewed distributions. It's calculated as: (distance from empirical to uniform) / (distance from perfectly skewed to uniform) + (number of minority classes - 1). A value of 0 indicates perfect balance, while higher values indicate greater imbalance relative to the worst possible scenario for that number of minority classes."

    except Exception as e:
        # Handle errors and store the error message in the result
        res['Error'] = str(e)

    return res