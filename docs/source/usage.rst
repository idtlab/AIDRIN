.. _usage:

AIDRIN Usage
============

Usage via PyPI
--------------

This section describes how to use **AIDRIN** after installing it via TestPyPI. The PyPI package enables data readiness and privacy analysis functions in Python notebooks or scripts, offering a simpler setup compared to cloning the GitHub repository. Note that this method may not include the latest changes available in the repository.

Installation
~~~~~~~~~~~~

Install AIDRIN from TestPyPI with:

.. code-block:: bash

   pip install -i https://test.pypi.org/simple/ aidrin==<version>

Replace ``<version>`` with the latest version (e.g., ``0.9.7``) from the `TestPyPI page <https://test.pypi.org/project/aidrin/>`_.

Verify the installation:

.. code-block:: python

   import aidrin
   print(aidrin.__version__)

This displays the installed version (e.g., ``0.9.7``).

Using AIDRIN Functions
~~~~~~~~~~~~~~~~~~~~~~

AIDRIN provides functions for data readiness and privacy analysis on datasets (e.g., CSV files). Below, we outline the key functions, their purpose, and what they return, using a sample dataset (``adult.csv``) as an example. You can download this dataset from the `UCI Machine Learning Repository <https://archive.ics.uci.edu/ml/datasets/adult>`_.
You can find sample datasets in the `aidrin/datasets/test_data` directory.

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

Below are AIDRIN’s primary functions, their usage, and the type of output they return.

calculate_completeness
^^^^^^^^^^^^^^^^^^^^^^

Evaluates dataset completeness by checking for missing values.

**Usage**:

.. code-block:: python

   from aidrin import calculate_completeness
   result = calculate_completeness(file_info)

**Returns**: A dictionary with an overall completeness score (1 for no missing values, 0 for all missing) and a histogram of missing value proportions per column.

calculate_correlations
^^^^^^^^^^^^^^^^^^^^^^

Calculates correlations between specified columns (numerical or categorical). You can specify the columns interested in analysis using the `columns` parameter.

**Usage**:

.. code-block:: python

   from aidrin import calculate_correlations
   result = calculate_correlations(columns=['age', 'education.num'], file_info=file_info)

**Returns**: A dictionary with numerical correlation scores (using Pearson’s coefficient) and categorical correlation analysis using Theil's U statistic. It will also return a visualization (heatmap) of the correlations.

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

**Returns**: A dictionary with the minimum k-anonymity value, risk score, descriptive statistics, histogram data, and a visualization (histogram).

compute_l_diversity
^^^^^^^^^^^^^^^^^^^

Quantifies l-diversity for a sensitive attribute within groups defined by quasi-identifiers. It measures the diversity of sensitive attribute values in each group, with a higher l-diversity indicating better protection against attribute disclosure.

**Usage**:

.. code-block:: python

   from aidrin import compute_l_diversity
   result = compute_l_diversity(quasi_identifiers=['sex'], sensitive_column='race', file_info=file_info)

**Returns**: A dictionary with the l-diversity value, risk score, descriptive statistics, histogram data, and a visualization (histogram).

compute_t_closeness
^^^^^^^^^^^^^^^^^^^

Measures t-closeness for a sensitive attribute relative to its overall distribution. It quantifies the similarity between the distribution of a sensitive attribute in a group and its distribution in the overall dataset. A lower t-closeness value indicates better protection against attribute disclosure.

**Usage**:

.. code-block:: python

   from aidrin import compute_t_closeness
   result = compute_t_closeness(quasi_identifiers=['sex'], sensitive_column='sex', file_info=file_info)

**Returns**: A dictionary with the t-closeness value, risk score, descriptive statistics, histogram data, and a visualization (histogram).

compute_entropy_risk
^^^^^^^^^^^^^^^^^^^^

Calculates entropy risk for quasi-identifier columns. It measures the uncertainty in identifying individuals based on the quasi-identifiers. A higher entropy value indicates greater uncertainty and lower re-identification risk.

**Usage**:

.. code-block:: python

   from aidrin import compute_entropy_risk
   result = compute_entropy_risk(quasi_identifiers=['sex'], file_info=file_info)

**Returns**: A dictionary with the entropy risk value, risk score, descriptive statistics, histogram data, and a visualization (bar chart).

Local and Web Application Usage
-------------------------------

AIDRIN can be used as a web application at `aidrin.io <https://aidrin.io>`_ or installed locally (see `Installation <./installation.html>`_). Both share the same codebase, but the web application is hosted on a server, eliminating the need to manage dependencies or background services like Redis, Celery, or Flask. The web interface provides a user-friendly way to evaluate datasets across six dimensions of data readiness for AI: **Data Quality**, **Impact of Data on AI**, **Fairness and Bias**, **Data Governance**, **Understandability and Usability**, and **Data Structure and Organization**. Each dimension includes specific metrics to assess dataset readiness.

Web Application Workflow
~~~~~~~~~~~~~~~~~~~~~~~~

To use the AIDRIN web application:

1. **Upload a Data File**:
   - Navigate to the file upload page at `aidrin.io <https://aidrin.io/upload_file>`_. or `https://127.0.0.1:5000/upload_file` if running locally.
   - Upload a dataset (e.g., CSV file like ``adult.csv``) via the web interface. You can download the sample dataset from the `UCI Machine Learning Repository <https://archive.ics.uci.edu/ml/datasets/adult>`_.
   - The file is processed server-side.

2. **Select a Data Readiness Dimension**:
   - From the homepage, choose one of the six dimensions to evaluate.
   - Each dimension offers specific metrics, detailed below.

3. **Choose Metrics and Configure Parameters**:
   - Select the desired metrics for the chosen dimension.
   - Specify any required parameters (e.g., column names for analysis).
   - AIDRIN processes the dataset and generates results.

4. **View Results and Download Report**:
   - Results include downloadable data summary statistics and visualizations (e.g., histograms, bar charts, heatmaps).
   - A JSON report summarizing the results is available for download.
   - Return to the homepage to select another dimension or upload a new dataset.

Data Readiness Dimensions and Metrics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Below are the six dimensions, their associated metrics, the methods used, and the outputs generated.

Data Quality
^^^^^^^^^^^^

Evaluates the quality of the dataset through metrics that assess completeness, duplicates, and outliers.

- **Completeness**:

  - **Method**: Calculates the proportion of non-missing values in the dataset. The overall completeness score is the average proportion of non-missing values across all columns.
  - **Parameters**: None (uses entire dataset).
  - **Result**: A chart with values ranging from 0 (all values missing) to 1 (no missing values) for each column in the dataset, and an overall completeness score.

- **Duplicates**:

  - **Method**: Identifies duplicate rows by comparing all column values. The duplicity score is the proportion of duplicate rows in the dataset.
  - **Parameters**: None (uses entire dataset).
  - **Result**: A duplicity score (0 for no duplicates).


- **Outliers**:

  - **Method**: Uses the Interquartile Range (IQR) method, calculating Q1 (first quartile), Q3 (third quartile), and IQR (Q3 - Q1). Outliers are values below `Q1 - 1.5 * IQR` or above `Q3 + 1.5 * IQR`. The outlier score is the proportion of outliers per numerical column, with an overall score averaged across columns.
  - **Parameters**: None (applies to all numerical columns).
  - **Result**: Bar chart of outlier scores per numerical column and an overall outlier score.

Impact of Data on AI
^^^^^^^^^^^^^^^^^^^^

Assesses how dataset features influence AI through correlation and feature relevance analysis.

- **Correlation Analysis**:

  - **Method**: For numerical columns, computes Pearson’s correlation coefficient (ranging from -1 to 1). For categorical columns, uses Theil's U statistic to measure association.
  - **Parameters**: Select columns for analysis (numerical and/or categorical).
  - **Result**: Heatmap visualization of correlation coefficients.

- **Feature Relevance**:

  - **Method**: Encodes categorical features using one-hot encoding and uses numerical features as-is. Computes the Pearson correlation coefficient between each feature and the target column.
  - **Parameters**: Select a target column (e.g., `'income'`) and features to analyze.
  - **Result**: Bar chart of feature importance scores relative to the target column.

Fairness and Bias
^^^^^^^^^^^^^^^^^

Evaluates potential biases in the dataset, particularly for classification tasks, through class imbalance and demographic metrics.

- **Class Imbalance**:

  - **Method**: Measures the distance between the actual class distribution and a perfectly balanced distribution using an imbalance degree score. You can select the distance metric from the provided options (e.g., Euclidean distance). Also you will have to specify the target column for analysis.
  - **Parameters**: Target column name (e.g., `'income'`). Distance metric (e.g., `'euclidean'`).
  - **Result**: Pie chart of class distribution. JSON report with imbalance degree score.

- **Representation Rates**:

  - **Method**: Calculates the proportion of each group (defined by a sensitive attribute) in the dataset.
  - **Parameters**: Sensitive attribute column (e.g., `'sex'`).
  - **Result**: Bar chart of representation rates.

- **Statistical Rates**:

  - **Method**: Computes proportions of groups (defined by a sensitive attribute) across class labels.
  - **Parameters**: Sensitive attribute column (e.g., `'sex'`) and class label column (e.g., `'income'`).
  - **Result**: Bar chart of proportions subdivided by class labels.

- **Conditional Demographic Disparity**:

  - **Method**: Measures disparity in outcomes across demographic groups, conditioned on other variables, to identify potential bias.
  - **Parameters**: Sensitive attribute column and class label column.
  - **Result**: Bar chart of disparity scores.

Data Governance
^^^^^^^^^^^^^^^

Focuses on privacy preservation through metrics that assess anonymity and disclosure risk.

- **k-Anonymity**:

  - **Method**: Calculates the minimum group size (k) sharing the same quasi-identifier values. A higher k indicates lower re-identification risk.
  - **Parameters**: List of quasi-identifier columns (e.g., `['sex', 'race']`).
  - **Result**: Histogram of equivalence class sizes.

- **l-Diversity**:

  - **Method**: Quantifies the diversity of sensitive attribute values within groups defined by quasi-identifiers. A higher l value indicates better protection against attribute disclosure.
  - **Parameters**: Quasi-identifier columns (e.g., `['sex']`) and sensitive column (e.g., `'race'`).
  - **Result**: Histogram of l-diversity values.

- **t-Closeness**:

  - **Method**: Measures the distance between the distribution of a sensitive attribute in a group and the overall dataset distribution. A lower t value indicates better privacy.
  - **Parameters**: Quasi-identifier columns (e.g., `['sex']`) and sensitive column (e.g., `'sex'`).
  - **Result**: Histogram of t-closeness values.

- **Entropy Risk**:

  - **Method**: Measures the uncertainty in identifying individuals based on quasi-identifiers. A higher entropy value indicates lower re-identification risk.
  - **Parameters**: Quasi-identifier columns (e.g., `['sex']`).
  - **Result**: Bar chart of entropy values.

Understandability and Usability
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This feature evaluates dataset metadata for compliance with the **FAIR principles** — *Findable*, *Accessible*, *Interoperable*, and *Reusable*.
It ensures your dataset is well-documented, discoverable, and reusable by others.

FAIR Compliance Report
'''''''''''''''''''''''

The **FAIR Compliance Report** analyzes your dataset’s metadata file (in **DCAT** or **DataCite JSON** format)
and provides a detailed assessment against the FAIR criteria.

How it Works
''''''''''''''

1. Navigate to the `FAIR Compliance Report upload page <https://aidrin.io/FAIR>`_.
2. Upload your metadata file (**DCAT** or **DataCite JSON**).
3. The system evaluates the file against the FAIR principles and generates a structured report.

FAIR Principles and Criteria
'''''''''''''''''''''''''''''

The evaluation checks for the presence and quality of specific metadata elements grouped under each FAIR principle:

**Findable**
    - ``identifier``
    - ``title``
    - ``description``
    - ``keyword``
    - ``theme``
    - ``landingPage``

**Accessible**
    - ``accessLevel``
    - ``downloadURL``
    - ``mediaType``
    - ``accessURL``
    - ``issued``
    - ``modified``

**Interoperable**
    - ``conformsTo``
    - ``references``
    - ``language``
    - ``format``
    - ``spatial``
    - ``temporal``

**Reusable**
    - ``license``
    - ``rights``
    - ``publisher``
    - ``description``
    - ``format``
    - ``programCode``
    - ``bureauCode``
    - ``contactPoint``

Output
~~~~~~

The system returns:

- **FAIR compliance scores** for each principle with visualizations.
- A breakdown of present and missing metadata elements.

.. note::

   AIDRIN focuses on the completeness and structure of your metadata.
   It does **not** validate the factual accuracy of the content.

Data Structure and Organization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Currently, no specific metrics are implemented for this dimension. Future updates may include metrics for assessing dataset schema, format consistency, or organization.

Notes
~~~~~

- **Local vs. Web Application**:
  - The local installation requires setting up Redis, Celery, and Flask (see `Installation <./installation.html>`_). The web application at `aidrin.io <https://aidrin.io>`_ handles these server-side, offering a no-setup alternative.
  - Both use the same codebase, ensuring identical functionality. The web application is ideal for users who prefer a browser-based interface.

- **File Formats**: The web application supports CSV files for data uploads and DCAT/DataCite JSON for metadata in the Understandability and Usability dimension.
- **Visualizations**: Generated downloadable plots (e.g., histograms, bar charts, heatmaps) are displayed in the web interface.
- **JSON Reports**: Each dimension’s analysis generates a downloadable JSON report containing all metrics, statistics, and visualization data (where applicable).
