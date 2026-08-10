.. _python_api:

Library Usage
=============

AIDRIN exposes **two** Python surfaces, and which one you want depends on the
job:

**The functional API** (``aidrin``) gives you one call per metric, each taking a
``file_info`` tuple and returning a dictionary of scores plus a visualisation.
This is the surface documented on this page, and it is what the web interface
uses internally. Reach for it in notebooks and exploratory scripts.

**The headless API** (``aidrin.headless``) is a registry-driven runner:
``run_metric()``, ``run_data_quality()``, and ``run_batch_metrics()`` with a
YAML config. It shares its metric registry with the command line, so anything
``aidrin run`` can do is available programmatically under the same names.
Reach for it in pipelines and batch jobs. See :ref:`cli_usage` for details.

Both ship in the same package; there is nothing extra to install.

.. note::

   Installing from PyPI is simpler than cloning the repository, but a release
   may lag behind the latest changes on GitHub. To get unreleased work, clone
   and ``pip install -e .`` as described in :ref:`cli_installation`.

   Note that the package depends on Flask, Celery and Redis even when you only
   want the library, so a plain ``pip install aidrin`` pulls in the server
   stack.

Installation
~~~~~~~~~~~~

Install AIDRIN with:

.. code-block:: bash

   pip install aidrin

To pin a specific release:

.. code-block:: bash

   pip install aidrin==<version>

Replace ``<version>`` with the version you want from the `PyPI page <https://pypi.org/project/aidrin/>`_.

Verify the installation:

.. code-block:: python

   import aidrin
   print(aidrin.__version__)

This displays the installed version, for example ``2026.07.1``.

Using AIDRIN Functions
~~~~~~~~~~~~~~~~~~~~~~

AIDRIN provides functions for data readiness and privacy analysis on datasets (e.g., CSV files). Below, we outline the key functions, their purpose, and what they return, using a sample dataset (``adult.csv``) as an example. You can download this dataset from the `UCI Machine Learning Repository <https://archive.ics.uci.edu/ml/datasets/adult>`_.
You can find sample datasets in the `examples/sample_data` directory of the repository, or download them directly from the web interface's **Sample Data** panel on the inspector page.

Setting Up File Information
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Most functions require a ``file_info`` tuple with the file path, name, and type:

.. code-block:: python

   file_path = "path/to/adult.csv"
   file_name = "adult.csv"
   file_type = ".csv"
   file_info = (file_path, file_name, file_type)

Available Functions
~~~~~~~~~~~~~~~~~~~

Below are AIDRIN's primary functions, their usage, and the type of output they return.

calculate_completeness
^^^^^^^^^^^^^^^^^^^^^^

Evaluates dataset completeness by checking for missing values.

**Usage**:

.. code-block:: python

   from aidrin import calculate_completeness
   result = calculate_completeness(file_info)

**Returns**: A dictionary with per-column completeness scores, an overall completeness score (1 for no missing values, 0 for all missing), and a horizontal bar chart of the per-column scores.

.. note::

   **HDF5 fill value handling**: HDF5 datasets encode missing data as a numeric
   sentinel (the *fill value*) rather than as a blank cell.  When reading an
   ``.h5`` file AIDRIN automatically translates these sentinels to ``NaN``
   before computing completeness, so the score reflects true data availability
   rather than always reporting 100%.

   Sentinels are collected from the following sources, in priority order:

   1. **User-supplied**: pass ``fill_values=[v1, v2, …]`` to ``hdf5Reader``
      at construction time to declare domain-specific sentinels explicitly.
   2. **_FillValue attribute**: the NetCDF/CF convention used by virtually
      all climate, oceanography, and atmospheric HDF5 files.
   3. **missing_value attribute**: the older NetCDF convention; may be a
      scalar or an array of multiple sentinels.
   4. **HDF5 native fill value**: the value stored in the dataset's own
      metadata (``dataset.fillvalue``).  When this equals the dtype default
      (``0`` / ``0.0``) and no fill-value attributes are present, it is treated
      as valid data because zero is a legitimate measurement in many scientific
      datasets (e.g. counts, indices). Set a ``_FillValue`` attribute to an
      unambiguous sentinel when zero represents missing data.

calculate_correlations
^^^^^^^^^^^^^^^^^^^^^^

Calculates correlations between specified columns (numerical or categorical). You can specify the columns interested in analysis using the `columns` parameter.

**Usage**:

.. code-block:: python

   from aidrin import calculate_correlations
   result = calculate_correlations(columns=['age', 'education.num'], file_info=file_info)

**Returns**: A dictionary with numerical correlation scores (automatically choosing Pearson's or Spearman's coefficient based on a normality check) and categorical correlation analysis using Theil's U statistic. It will also return a visualization (heatmap) of the correlations, and the selected numerical method is exposed under ``Correlations Analysis Numerical -> Method``.

calculate_class_distribution
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Analyzes class distribution in a specified column to quantify imbalance. The `column` parameter specifies the target column for analysis. It uses imbalance degree scoring to assess class balance. It measures the Euclidean distance between the actual class distribution and a perfectly balanced distribution.

**Usage**:

.. code-block:: python

   from aidrin import calculate_class_distribution
   result = calculate_class_distribution(column='income', file_info=file_info)

**Returns**: A dictionary with an imbalance degree score and a pie chart visualization of the class distribution.

calculate_duplicates
^^^^^^^^^^^^^^^^^^^^

Detects duplicate rows in the dataset.

**Usage**:

.. code-block:: python

   from aidrin import calculate_duplicates
   result = calculate_duplicates(file_info=file_info)

**Returns**: A dictionary with the proportion of duplicate rows (0 for no duplicates).

calculate_feature_relevance
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Assesses feature relevance relative to a given target column. Categorical features are encoded using one-hot encoding, and numerical features are used as-is. Then the Pearson correlation coefficient is calculated between each feature and the target column.

**Usage**:

.. code-block:: python

   from aidrin import calculate_feature_relevance
   result = calculate_feature_relevance(file_info=file_info, target_col='income')

**Returns**: A dictionary with feature importance scores for the target column. A bar chart visualization of feature importances is also provided.

calculate_outliers
^^^^^^^^^^^^^^^^^^

Identifies outliers in numerical columns using the Interquartile Range (IQR) method. This method calculates the first (Q1) and third (Q3) quartiles, computes the IQR (Q3 - Q1), and defines outliers as values below `Q1 - 1.5 * IQR` or above `Q3 + 1.5 * IQR`. The proportion of outliers is calculated for each numerical column, and an overall outlier score is derived by averaging the individual column scores. This is calculated for each numerical column.

**Usage**:

.. code-block:: python

   from aidrin import calculate_outliers
   result = calculate_outliers(file_info=file_info)

**Returns**: A dictionary with outlier scores for each numerical column and an overall score. A bar chart visualization of outlier scores is also provided.

calculate_custom_outliers
^^^^^^^^^^^^^^^^^^^^^^^^^

Identifies values that fail user-defined valid-value criteria for a selected target. Each rule describes expected valid values; values that do not satisfy the rule are flagged as outliers. Rules can check numeric ranges, regular expression matches, missing values, or nested criteria combined with ``and``, ``or``, and ``not``. This is useful when domain-specific validity rules are more appropriate than the default IQR outlier method.

**Usage**:

.. code-block:: python

   from aidrin import calculate_custom_outliers

   file_info = ("/path/to/data.csv", "data.csv", ".csv")
   rules = [
       {
           "id": "valid-temperature",
           "name": "Valid temperature range",
           "target": "temperature",
           "target_type": "column",
           "criteria": {
               "op": "and",
               "conditions": [
                   {"type": "range", "min": -50, "max": 60},
                   {"type": "regex", "pattern": r"^-?\d+(\.\d+)?$"},
               ],
           },
           "allow_missing": False,
       }
   ]
   result = calculate_custom_outliers(
       file_info=file_info,
       rules=rules,
       max_outliers=100,
       scan_limit=None,
       stop_after_outliers=False,
   )

**Returns**: A dictionary with per-rule summaries, a compact outlier preview, CSV export rows, and per-rule errors when a target cannot be evaluated. HDF5 datasets are scanned in blocks so large native datasets do not need to be loaded fully into memory.

calculate_statistical_rates
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Computes statistical rates (e.g., proportions) for groups across classes. The `sensitive_attribute_column` parameter specifies the sensitive attribute for analysis, while the `y_true_column` parameter indicates class labels.

**Usage**:

.. code-block:: python

   from aidrin import calculate_statistical_rates
   result = calculate_statistical_rates(sensitive_attribute_column='sex', y_true_column='income', file_info=file_info)

**Returns**: A dictionary with group proportions, and a visualization (bar chart) of the proportions subdivided by class labels.

compute_k_anonymity
^^^^^^^^^^^^^^^^^^^

Measures k-anonymity for specified quasi-identifier columns. It calculates the minimum k value across all equivalence classes formed by the quasi-identifiers. The risk score is derived from the minimum k value, where a higher k indicates lower re-identification risk.

**Usage**:

.. code-block:: python

   from aidrin import compute_k_anonymity
   result = compute_k_anonymity(quasi_identifiers=['sex', 'race'], file_info=file_info)

**Returns**: A dictionary with the minimum k-anonymity value, descriptive statistics, histogram data, and a visualization (histogram).

compute_l_diversity
^^^^^^^^^^^^^^^^^^^

Quantifies l-diversity for a sensitive attribute within groups defined by quasi-identifiers. It measures the diversity of sensitive attribute values in each group, with a higher l-diversity indicating better protection against attribute disclosure.

**Usage**:

.. code-block:: python

   from aidrin import compute_l_diversity
   result = compute_l_diversity(quasi_identifiers=['sex'], sensitive_column='race', file_info=file_info)

**Returns**: A dictionary with the l-diversity value, descriptive statistics, histogram data, and a visualization (histogram).

compute_t_closeness
^^^^^^^^^^^^^^^^^^^

Measures t-closeness for a sensitive attribute relative to its overall distribution. It quantifies the similarity between the distribution of a sensitive attribute in a group and its distribution in the overall dataset. A lower t-closeness value indicates better protection against attribute disclosure.

**Usage**:

.. code-block:: python

   from aidrin import compute_t_closeness
   result = compute_t_closeness(quasi_identifiers=['sex'], sensitive_column='sex', file_info=file_info)

**Returns**: A dictionary with the t-closeness value, descriptive statistics, histogram data, and a visualization (histogram).

compute_entropy_risk
^^^^^^^^^^^^^^^^^^^^

Calculates entropy risk for quasi-identifier columns. It measures the uncertainty in identifying individuals based on the quasi-identifiers. A higher entropy value indicates greater uncertainty and lower re-identification risk.

**Usage**:

.. code-block:: python

   from aidrin import compute_entropy_risk
   result = compute_entropy_risk(quasi_identifiers=['sex'], file_info=file_info)

**Returns**: A dictionary with the entropy risk value, descriptive statistics, histogram data, and a visualization (bar chart).

calculate_row_level_completeness
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Computes the percentage of rows whose *required* columns are all non-null.

**Usage**:

.. code-block:: python

   from aidrin import calculate_row_level_completeness
   result = calculate_row_level_completeness(
       required_columns=['age', 'income'], file_info=file_info
   )

**Returns**: A dictionary with the percentage of complete rows, alongside the complete and total row counts.

calculate_duplicity_by_features
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Identifies duplicate rows by comparing only the selected feature columns, rather than the whole row.

**Usage**:

.. code-block:: python

   from aidrin import calculate_duplicity_by_features
   result = calculate_duplicity_by_features(
       features=['age', 'zipcode'], file_info=file_info
   )

**Returns**: A dictionary with the duplicate row count and percentage, plus the largest duplicate groups with their feature values and row counts.

calculate_feature_coverage_ratio
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Computes the percentage of features whose non-null rate meets or exceeds a threshold.

**Usage**:

.. code-block:: python

   from aidrin import calculate_feature_coverage_ratio
   result = calculate_feature_coverage_ratio(threshold=0.9, file_info=file_info)

**Returns**: A dictionary with the percentage of features meeting the threshold, the covered and total feature counts, and a histogram of per-feature non-null rates with the threshold marked.

calculate_temporal_completeness
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Computes the percentage of expected time intervals present between the earliest and latest timestamps, at a chosen frequency.

**Usage**:

.. code-block:: python

   from aidrin import calculate_temporal_completeness
   result = calculate_temporal_completeness(
       timestamp_column='timestamp', frequency='D', file_info=file_info
   )

``frequency`` is one of ``ms``, ``s``, ``min``, ``h``, ``D``, ``W``, ``ME``, ``QE``, ``YE``.

**Returns**: A dictionary with the percentage of intervals present, the expected and present counts, and a timeline chart of present versus missing intervals.

calculate_null_count_trend
^^^^^^^^^^^^^^^^^^^^^^^^^^

Counts null cells per batch, grouped by a batch column, to spot quality regressions across batches.

**Usage**:

.. code-block:: python

   from aidrin import calculate_null_count_trend
   result = calculate_null_count_trend(
       batch_column='zipcode', target_columns=[], file_info=file_info
   )

Pass an empty ``target_columns`` to sum nulls across all other columns.

**Returns**: A dictionary with null counts per batch, and a chart of the trend.

calculate_representation_rate
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Computes pairwise representation ratios for sensitive attribute columns. For each column, it emits ``P(value_a) / P(value_b)`` for every unordered pair of distinct values; a ratio above 1 means ``value_a`` is over-represented.

**Usage**:

.. code-block:: python

   from aidrin import calculate_representation_rate
   result = calculate_representation_rate(
       columns=['sex', 'race'], file_info=file_info
   )

**Returns**: A dictionary of pairwise ratios per column. The chart is produced separately and is not part of this return value.

calculate_constant_feature_count
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Counts columns that have a single distinct value. Null counts as a value: an all-null column is constant, while one real value plus some nulls is not.

**Usage**:

.. code-block:: python

   from aidrin import calculate_constant_feature_count
   result = calculate_constant_feature_count(file_info=file_info)

**Returns**: A dictionary with the count of constant columns, the total column count, and each constant column with its single value.

calculate_max_pairwise_correlation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Reports the strongest absolute pairwise Pearson correlation between numeric, non-constant features.

**Usage**:

.. code-block:: python

   from aidrin import calculate_max_pairwise_correlation
   result = calculate_max_pairwise_correlation(file_info=file_info)

**Returns**: A dictionary with the maximum correlation, the most-correlated pair, and the top pairs.

calculate_skewness
^^^^^^^^^^^^^^^^^^

Per-feature skewness (distribution asymmetry) for numeric columns. Values far from 0 indicate a long tail; constant columns are excluded.

**Usage**:

.. code-block:: python

   from aidrin import calculate_skewness
   result = calculate_skewness(file_info=file_info)

**Returns**: A dictionary with per-column skewness, the most-skewed feature, and a bar chart.

calculate_kurtosis
^^^^^^^^^^^^^^^^^^

Per-feature excess kurtosis (Fisher's definition, where a normal distribution is 0). Positive values mean heavier tails than normal.

**Usage**:

.. code-block:: python

   from aidrin import calculate_kurtosis
   result = calculate_kurtosis(file_info=file_info)

**Returns**: A dictionary with per-column excess kurtosis, the most-extreme feature, and a bar chart.
