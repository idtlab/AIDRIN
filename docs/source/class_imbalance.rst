Class Imbalance Metrics Guide
============================

Comprehensive Guide to Quantifying and Assessing Class Distribution Imbalance in Machine Learning Datasets

.. contents:: Quick Navigation
   :local:

What is Class Imbalance?
-----------------------

Class imbalance represents a fundamental challenge in machine learning where the distribution of class labels exhibits significant skewness, with certain classes being substantially more prevalent than others. This phenomenon can introduce systematic biases in model training, leading to suboptimal generalization performance, particularly for underrepresented classes. Systematic quantification of imbalance severity enables informed decisions regarding data preprocessing strategies and algorithm selection.

Distance Metrics for Imbalance Degree Calculation
-----------------------------------------------

The **Imbalance Degree** constitutes a sophisticated ratio-based metric that systematically compares observed class distributions against both idealized balanced (uniform) distributions and perfectly skewed reference distributions. The mathematical formulation is:

**ID = (distance from empirical to uniform) / (distance from perfectly skewed to uniform) + (number of minority classes - 1)**

This formulation yields a normalized measure where zero indicates perfect balance and higher values signify progressively greater imbalance relative to the theoretical worst-case scenario for the given number of minority classes.

Total Variation Distance (TVD)
-----------------------------

.. math::

   TV(p, u) = 0.5 \times \sum_{i} |p_{i} - u_{i}|

(where u_{i} = 1/K for K classes)

**Mathematical Foundation:** Total variation distance measures the maximum difference in probability that can be assigned to any event by two probability distributions. It's equivalent to half the L1 norm of the difference between distributions.

**Interpretation:** Represents the total "mass" of probability that needs to be redistributed to transform one distribution into another. 0 indicates identical distributions (perfect balance), while 1 indicates maximally different distributions.

**Properties:** Bounded between [0,1], symmetric, and satisfies the triangle inequality. It's a true metric that provides a natural scale for comparing distributions.

**When to use:** Excellent default choice for most applications. Particularly useful when you want a robust, interpretable measure that's not overly sensitive to outliers or extreme values.

**Advantages:** Intuitive interpretation, bounded range, robust to noise, computationally efficient, and widely understood in statistics.

**Limitations:** May not capture subtle differences in distributions with many classes, and treats all deviations equally regardless of magnitude.

**Real-world analogy:** Think of it as measuring how much "work" is needed to redistribute resources evenly across all classes.

Euclidean Distance
-----------------

.. math::

   EU(p, u) = \sqrt{\sum_{i} (p_{i} - u_{i})^{2}}

**Mathematical Foundation:** Euclidean distance is the straight-line distance between two points in n-dimensional space. For probability distributions, it measures the geometric distance between the distribution vectors.

**Interpretation:** Represents the "as-the-crow-flies" distance between distributions. The squared terms mean that larger deviations are penalized more heavily than smaller ones, making it sensitive to outliers.

**Properties:** Always non-negative, symmetric, and satisfies the triangle inequality. However, it's not bounded to [0,1] and can exceed 1 for highly imbalanced distributions with many classes.

**When to use:** Ideal when you want to emphasize large imbalances and are less concerned about small deviations. Useful in scenarios where you want to detect extreme class imbalances quickly.

**Advantages:** Familiar geometric interpretation, sensitive to large deviations, computationally efficient, and widely used in machine learning.

**Limitations:** Unbounded range can make interpretation difficult, overly sensitive to outliers, and may not provide consistent scale across different numbers of classes.

**Real-world analogy:** Like measuring the straight-line distance between two cities on a map - it's the shortest possible path, but may not reflect the actual "cost" of getting from one to the other.

Chebyshev Distance
------------------

.. math::

   CH(p, u) = \max_{i} |p_{i} - u_{i}|

**Mathematical Foundation:** Chebyshev distance (also known as L∞ norm or maximum norm) measures the maximum absolute difference between corresponding elements of two vectors. It represents the worst-case scenario in terms of individual class deviations.

**Interpretation:** Identifies the single class with the largest deviation from perfect balance. This metric focuses on the "worst offender" rather than the overall distribution pattern.

**Properties:** Bounded between [0,1], symmetric, and satisfies the triangle inequality. It's a true metric that provides a conservative estimate of distribution difference.

**When to use:** Particularly useful when you're concerned about individual class fairness or when the worst-case scenario is more important than average behavior. Common in fairness-aware machine learning.

**Advantages:** Easy to interpret, bounded range, robust to the number of classes, and directly identifies problematic classes. Useful for regulatory compliance where maximum deviation matters.

**Limitations:** Ignores the overall distribution pattern, may miss systematic biases across multiple classes, and doesn't distinguish between different types of imbalance patterns.

**Real-world analogy:** Like a quality control inspector who only cares about the worst defect found, regardless of how many other defects exist.

Hellinger Distance
------------------

.. math::

   HE(p, u) = \sqrt{0.5 \times \sum_{i} (\sqrt{p_{i}} - \sqrt{u_{i}})^{2}}

**Mathematical Foundation:** Hellinger distance is based on the square root of probabilities, making it sensitive to relative rather than absolute differences. It's derived from the Bhattacharyya coefficient and measures the overlap between probability distributions.

**Interpretation:** Measures the "geometric" difference between distributions by comparing their square roots. This transformation makes the metric more sensitive to differences in rare classes while being less affected by dominant classes.

**Properties:** Bounded between [0,1], symmetric, and satisfies the triangle inequality. It's a true metric that provides a balanced view of distribution differences.

**When to use:** Excellent choice when you have rare classes or when you want to give equal weight to relative differences regardless of absolute class sizes. Particularly useful in domains with long-tailed distributions.

**Advantages:** Bounded range, symmetric, robust to outliers, and provides balanced sensitivity across different class frequencies. Mathematically well-founded in information theory.

**Limitations:** Less intuitive interpretation compared to L1/L2, computationally slightly more expensive due to square root operations, and may not be as familiar to practitioners.

**Real-world analogy:** Like comparing the "shapes" of two distributions rather than their absolute values - similar to how a magnifying glass can reveal details that are invisible to the naked eye.

Kullback-Leibler Divergence (KL)
--------------------------------

.. math::

   KL(p || u) = \sum_{i} p_{i} \log(p_{i} / u_{i})

**Mathematical Foundation:** KL divergence measures the relative entropy between two probability distributions. It quantifies the information loss when approximating one distribution with another, based on information theory principles.

**Interpretation:** Represents the expected logarithmic difference between the true distribution and the approximating distribution. Zero indicates identical distributions, while higher values indicate greater information loss.

**Properties:** Non-negative, asymmetric (KL(p||q) ≠ KL(q||p)), and not bounded above. It's not a true metric but provides a theoretically sound measure of distribution difference.

**When to use:** Appropriate when you need a theoretically grounded measure based on information theory, particularly in machine learning contexts where information loss is a key concern.

**Advantages:** Strong theoretical foundation in information theory, widely used in machine learning, and provides meaningful interpretation in terms of information content.

**Limitations:** Asymmetric nature requires careful interpretation, unbounded range makes comparison difficult, and numerical instability with zero probabilities requires special handling.

**Real-world analogy:** Like measuring how much information is lost when compressing a detailed map into a simplified version - some details are inevitably lost in the process.

Chi-Squared Distance
--------------------

.. math::

   CS(p, u) = \sum_{i} (p_{i} - u_{i})^{2} / u_{i}

**Mathematical Foundation:** Chi-squared distance is derived from the chi-squared test statistic, which measures the discrepancy between observed and expected frequencies. It's a weighted sum of squared differences, where each term is normalized by the expected frequency.

**Interpretation:** Measures the statistical significance of deviations from expected frequencies. The weighting by expected frequencies means that deviations in rare classes are penalized more heavily than deviations in common classes.

**Properties:** Non-negative, symmetric, and not bounded above. It's not a true metric but provides a statistically principled measure of distribution difference.

**When to use:** Particularly suitable when you want to emphasize the importance of rare classes or when you need a measure that aligns with traditional statistical testing procedures.

**Advantages:** Well-established in statistical literature, provides interpretable p-values when used in hypothesis testing, and naturally emphasizes rare class deviations.

**Limitations:** Unbounded range, numerical instability with very small expected frequencies, and may overemphasize rare class deviations in some contexts.

**Real-world analogy:** Like a quality control system that pays extra attention to rare defects because they might indicate systematic problems in the manufacturing process.

Summary Table
------------

+------------------------+--------------------------------+-----------+-----------+------------------+------------------+
| Metric                 | Formula                        | Range     | Symmetric?| Robust to Zeros?| Interpretation   |
+========================+================================+===========+===========+==================+==================+
| Total Variation        | 0.5 ∑|p_i-u_i|                | [0,1]     | Yes       | Yes              | Simple, intuitive|
| Distance (TVD)         |                                |           |           |                  |                  |
+------------------------+--------------------------------+-----------+-----------+------------------+------------------+
| Euclidean Distance     | sqrt(∑(p_i-u_i)²)             | [0,∞)     | Yes       | Yes              | Penalizes large  |
|                        |                                |           |           |                  | deviations        |
+------------------------+--------------------------------+-----------+-----------+------------------+------------------+
| Chebyshev              | max|p_i-u_i|                   | [0,1]     | Yes       | Yes              | Focuses on worst |
|                        |                                |           |           |                  | class            |
+------------------------+--------------------------------+-----------+-----------+------------------+------------------+
| Hellinger              | sqrt(0.5 ∑(√p_i-√u_i)²)      | [0,1]     | Yes       | Yes              | Geometric        |
|                        |                                |           |           |                  | difference       |
+------------------------+--------------------------------+-----------+-----------+------------------+------------------+
| KL                     | ∑ p_i log(p_i/u_i)            | [0,∞)     | No        | No               | Information loss |
+------------------------+--------------------------------+-----------+-----------+------------------+------------------+
| Chi-Squared            | ∑(p_i-u_i)²/u_i               | [0,∞)     | Yes       | No               | Statistical test |
+------------------------+--------------------------------+-----------+-----------+------------------+------------------+

References
----------

- J. Ortigosa-Hernández, I. Inza, and J. A. Lozano, "Measuring the class-imbalance extent of multi-class problems," Pattern Recognit. Lett., 2017.
- A Generalization of the Chebyshev Distance and Its Application to Pattern Recognition
- Kullback, S., & Leibler, R. A. (1951). "On Information and Sufficiency." Annals of Mathematical Statistics, 22(1), 79–86.
- Hellinger, E. (1909). "Neue Begründung der Theorie quadratischer Formen von unendlichvielen Veränderlichen." Journal für die reine und angewandte Mathematik, 136, 210–271.
- Le Cam, L. (1973). "Convergence of estimates under dimensionality restrictions." Annals of Statistics, 1(1), 38–53.
- Pearson, K. (1900). "On the criterion that a given system of deviations from the probable in the case of a correlated system of variables is such that it can be reasonably supposed to have arisen from random sampling." Philosophical Magazine, 50(302), 157–175.
- Wikipedia: Distance (mathematics)
