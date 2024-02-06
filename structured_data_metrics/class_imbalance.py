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
        summ = np.vectorize(lambda p : pow(p - _e, 2))(_d).sum()
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
        A list with the i_m distribution.
        """
        min_i = np.zeros(_m)
        maj_i = np.ones((_K - _m - 1)) * (1 / _K)
        maj = np.array([1 - (_K - _m - 1) / _K])
        return np.concatenate((min_i, maj_i, maj)).tolist()
    
    def _dist_fn():
        """
        Selects the distance function according to the distance paramenter.
        
        Returns
        -------
        A distance function.
        """
        if distance == "EU":
            return _eu
        else:
            raise ValueError("Bad distance function parameter. " + \
                    "Should be one in EU, CH, KL, HE, TV, or CS")
    
    _, class_counts = np.unique(classes, return_counts=True)
    empirical_distribution = class_counts / class_counts.sum()
    K = len(class_counts)
    e = 1 / K
    m = _min_classes(empirical_distribution, e)
    i_m = _i_m(K, m)
    dfn = _dist_fn()
    dist_ed = dfn(empirical_distribution, e)
    return 0.0 if dist_ed == 00 else (dist_ed / dfn(i_m, e)) + (m - 1)

def class_distribution_plot(df, column):
    plot_res = {}
    try:
        # Get unique class labels
        class_labels = df[column].dropna().unique()

        # Calculate class frequencies
        class_counts = df[column].dropna().value_counts()

        # Set the figure size
        plt.figure(figsize=(8, 8))

        # Plotting a pie chart for each class
        patches, texts = plt.pie(class_counts, startangle=90)

 

        # Add percentages to the legend
        legend_labels = [f'{label} - {percentage:.1f}%' for label, percentage in zip(class_labels, class_counts / class_counts.sum() * 100)]
        plt.legend(legend_labels, loc="upper right")

        plt.title(f'Distribution of Each Class in {column}')
        plt.axis('equal')

        # Save the plot to a BytesIO buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
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

        res['Imbalance degree score'] = id
        res['Description'] = "The Imbalance Degree (ID) is a metric that quantifies class imbalance in datasets by comparing the observed class distribution to an idealized balanced state. A value of 0 indicates perfect balance, while higher values signify increased dissimilarity and greater imbalance. Calculated using a distance or similarity function, ID provides a concise measure for understanding and addressing challenges posed by uneven class representation in machine learning datasets."


    except Exception as e:
        # Handle errors and store the error message in the result
        res['Error'] = str(e)

    return res