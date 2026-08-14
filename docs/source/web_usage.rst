.. _usage:
.. _web_usage:

Web Application Usage
=====================

Overview
--------

AIDRIN can be used as a web application at `aidrin.org <https://aidrin.org>`_ or installed locally (see :ref:`Web Application Installation <web_installation>`). Both share the same codebase, but the web application is hosted on a server, eliminating the need to manage dependencies or background services like Redis, Celery, or Flask. The web interface provides a user-friendly way to evaluate datasets across six dimensions of data readiness for AI: **Data Quality**, **Impact of Data on AI**, **Fairness and Bias**, **Data Governance**, **Understandability and Usability**, and **Data Structure**. Each dimension includes specific metrics to assess dataset readiness.

Web Application Workflow
~~~~~~~~~~~~~~~~~~~~~~~~

To use the AIDRIN web application:

1. **Upload a Data File**:
   - Navigate to the inspector page at `demo.aidrin.org <https://demo.aidrin.org/inspector>`__, or ``http://127.0.0.1:5000/inspector`` if running locally.
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

5. **AI Explanations (Optional)**:
   - With the ``llm`` extra installed, each metric result can carry a short AI-generated interpretation. See `AI Explanations`_ below.

Data Readiness Dimensions and Metrics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Below are the six dimensions, their associated metrics, the methods used, and the outputs generated.

Data Quality
^^^^^^^^^^^^

Evaluates the quality of the dataset through metrics that assess completeness, duplicates, and outliers,
as well as row-level completeness, feature coverage, temporal completeness, and null-count trends.

- **Column-Level Completeness**:

  - **Method**: Calculates the proportion of non-missing values in the dataset. The overall completeness score is the column-wise average of the per-column non-missing rates. (The underlying metric id / CLI command is still ``completeness``.)
  - **Parameters**: None (uses entire dataset).
  - **Result**: A chart with values ranging from 0 (all values missing) to 1 (no missing values) for each column in the dataset, and an overall completeness score.

- **Row-Level Completeness**:

  - **Method**: Computes the percentage of rows whose *required* columns are all non-null.
  - **Parameters**: Required columns (the columns that must all be populated for a row to count as complete).
  - **Result**: The percentage of complete rows, alongside the complete and total row counts.

- **Feature Coverage Ratio**:

  - **Method**: Computes the percentage of features whose non-null rate meets or exceeds a threshold.
  - **Parameters**: Coverage threshold in [0, 1] (default 0.9).
  - **Result**: A bar chart of feature coverage and the percentage of features meeting the threshold.

- **Temporal Completeness**:

  - **Method**: Computes the percentage of expected time intervals present between the earliest and latest timestamps at a chosen frequency.
  - **Parameters**: Timestamp column and frequency (one of ``ms, s, min, h, D, W, ME, QE, YE``; default ``D``).
  - **Result**: A timeline chart of present vs. missing intervals, with the percentage present and the expected/present counts.

- **Null Count Trend**:

  - **Method**: Counts total null cells per batch, grouped by a batch column, to spot quality regressions across batches.
  - **Parameters**: Batch column, and optional target columns (defaults to all other columns).
  - **Result**: A chart of null counts per batch.

- **Duplicates**:

  - **Method**: Identifies duplicate rows by comparing all column values. The duplicity score is the proportion of duplicate rows in the dataset.
  - **Parameters**: None (uses entire dataset).
  - **Result**: A duplicity score (0 for no duplicates).

- **Duplicates by Selected Features**:

  - **Method**: Identifies duplicate rows by comparing only the selected feature columns, rather than the whole row.
  - **Parameters**: Features to compare.
  - **Result**: Duplicate row count and percentage, plus the top 10 largest duplicate groups with their feature values and row counts.


- **Outliers**:

  - **Method**: Uses the Interquartile Range (IQR) method, calculating Q1 (first quartile), Q3 (third quartile), and IQR (Q3 - Q1). Outliers are values below `Q1 - 1.5 * IQR` or above `Q3 + 1.5 * IQR`. The outlier score is the proportion of outliers per numerical column, with an overall score averaged across columns.
  - **Parameters**: None (applies to all numerical columns).
  - **Result**: Bar chart of outlier scores per numerical column and an overall outlier score.

- **Custom Criteria Outliers**:

  - **Method**: Evaluates user-defined valid-value criteria against selected columns or HDF5 datasets. Values that do not satisfy those criteria are flagged as outliers. Criteria can use numeric ranges, regular expressions, missing-value handling, and nested ``and``/``or``/``not`` conditions.
  - **Parameters**: Choose either manually entered rules or a JSON file containing the same top-level rules array used by the CLI and MCP server, plus maximum preview/export rows, optional scan limit, and whether to stop scanning after the preview limit is reached. Rules use exact target matching by default. The exact-name picker is searchable. In the manual editor, choose **Regex** and enter a **Target pattern** to apply a rule to every complete column or HDF5-dataset name that matches it. The target category is inferred from the loaded file; it is shown only if the file exposes more than one category. JSON rules use ``"target_match": "regex"``. Manually entered rules can be saved as a reusable JSON file; the browser reads selected JSON files without uploading or saving them.
  - **Result**: Per-rule counts, compact outlier preview rows with locations and values, downloadable CSV export rows, and HDF5 aggregate summaries when applicable. A regex target produces separate results for each resolved target.

Impact of Data on AI
^^^^^^^^^^^^^^^^^^^^

Assesses how dataset features influence AI through correlation and feature relevance analysis.

- **Correlation Analysis**:

  - **Method**: For numerical columns, runs a normality check using the Shapiro–Wilk test (α = 0.05) on up to 5000 sampled rows; if the test does not reject normality it computes Pearson's correlation coefficient; otherwise it uses Spearman's rank correlation (both ranging from -1 to 1). When SciPy is unavailable, a skewness/kurtosis heuristic is used as a fallback. For categorical columns, it uses Theil's U statistic to measure association.
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

- **Single Attribute Risk Score**:

  - **Method**: Markov-model risk score computed per evaluated column against an identifier column, estimating how far each attribute alone narrows down an individual.
  - **Parameters**: An ID column, and the columns to evaluate.
  - **Result**: Per-column risk scores with a visualization.

- **Multiple Attribute Risk Score**:

  - **Method**: As above, but over combinations of the evaluated columns, capturing risk that only appears when attributes are considered together.
  - **Parameters**: An ID column, and the columns to evaluate.
  - **Result**: Combined risk scores with a visualization.

- **Differential Privacy**:

  - **Method**: Adds calibrated noise to the selected columns and reports how the summary statistics shift, so you can judge the utility cost of a given privacy budget.
  - **Parameters**: Columns to noise, and the privacy budget (epsilon; the panel defaults to 0.1). A smaller epsilon means more noise and stronger privacy.
  - **Result**: Before-and-after statistics for each column with a visualization. The noised dataset is also written to ``noisy/noisy_data.csv`` on the server.

- **HIPAA Compliance**:

  - **Method**: Scans datasets for the presence of 8 out of 18 key HIPAA-regulated identifiers as defined under the `Safe Harbor method <https://www.accountablehq.com/post/what-are-the-18-hipaa-identifiers-a-clear-guide-with-examples>`_. This includes detection of direct and indirect identifiers that could enable re-identification of individuals.
  - **Identifiers Detected**: Social Security Numbers (SSNs), email addresses, phone and fax numbers, IP addresses, URLs, Vehicle Identification Numbers (VINs), and medical or account identifiers. Additionally, US postal codes are identified using geographic validation powered by `pgeocode <https://pgeocode.readthedocs.io/en/latest/>`_.
  - **Parameters**: Configuration of columns to scan or exclude.
  - **Result**: Flagged records with detected identifiers, including counts and classification by identifier type.

Understandability and Usability
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This feature evaluates dataset metadata for compliance with the **FAIR principles** — *Findable*, *Accessible*, *Interoperable*, and *Reusable*.
It ensures your dataset is well-documented, discoverable, and reusable by others.

FAIR Compliance Report
'''''''''''''''''''''''

The **FAIR Compliance Report** analyzes your dataset's metadata file (in **DCAT** or **DataCite JSON** format)
and provides a detailed assessment against the FAIR criteria.

How it Works
''''''''''''''

1. Open the **FAIR Assessment** panel from the sidebar of the `inspector page <https://demo.aidrin.org/inspector>`__.
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
''''''

The system returns:

- **FAIR compliance scores** for each principle with visualizations.
- A breakdown of present and missing metadata elements.

.. note::

   AIDRIN focuses on the completeness and structure of your metadata.
   It does **not** validate the factual accuracy of the content.

Data Structure
^^^^^^^^^^^^^^

Assesses structural and distributional properties of the dataset. The four
statistical metrics require no parameters; the latter three operate on the
numeric, non-constant columns. Referenced-file validation uses selected
path-bearing targets and filesystem settings.

- **Referenced Files** (local deployments only):

  - **Method**: Resolves paths stored in selected string-valued columns or HDF5 datasets and checks whether they identify regular files on the AIDRIN web server. Valid files include size, owner when available, creation time when the operating system exposes one, and modification time.
  - **Parameters**: Search for and select exact path-bearing targets, or choose **Regex** to match complete target names. Also select an administrator-configured filesystem root, an optional relative base subdirectory, and a detail-record cap. Suggested target names appear first but are never selected automatically. Both regex workflows preview their matching targets before submission.
  - **Result**: Complete or partial scan counts, per-target summaries, invalid-reference locations and reasons, and deduplicated file metadata. A warning appears when the administrator scan cap prevents a complete scan.

  This control is disabled until an administrator configures at least one root.
  Set ``AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS`` to a JSON array of absolute,
  existing directories and optionally set a positive web scan cap (default
  ``10000``):

  .. code-block:: bash

     export AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS='["/data/project","/data/shared"]'
     export AIDRIN_FILE_REFERENCE_WEB_SCAN_LIMIT=10000

  AIDRIN does not fall back to the process working directory or filesystem root
  when this allowlist is unset. The local Docker Compose stack uses ``["/app"]``
  for development testing; production deployments should allow only the
  directories that contain referenced data.

  The selected base directory must remain inside its configured root, and every
  referenced file must remain inside one of the configured roots after resolving
  symbolic links. Paths are checked on the web server, not on the browser's
  computer. Globus datasets cannot use this local filesystem check; use CLI or
  MCP on the host that can access the referenced files instead.

- **Constant Feature Count**:

  - **Method**: Counts columns that have a single distinct value. Null is treated as a value like any other: a column that is entirely null counts as constant, and a column with one real value plus some nulls does not (it has two distinct values — the value and null).
  - **Parameters**: None (uses entire dataset).
  - **Result**: The count of constant columns, the total column count, and the constant columns with their single value (``null`` for an all-null column).

- **Max Pairwise Correlation**:

  - **Method**: Computes the absolute Pearson correlation matrix over numeric
    features and reports the single strongest pair. Values near 1.0 indicate
    redundant (near-collinear) features.
  - **Parameters**: None.
  - **Result**: The maximum correlation, the most-correlated pair, the top pairs,
    and an absolute-correlation heatmap.

- **Skewness**:

  - **Method**: Per-feature skewness (distribution asymmetry). Values far from 0
    indicate long-tailed, asymmetric distributions.
  - **Parameters**: None.
  - **Result**: Per-column skewness, the most-skewed feature, and a bar chart.

- **Kurtosis**:

  - **Method**: Per-feature excess kurtosis (Fisher's definition; normal = 0).
    Positive values mean heavier tails / more outliers than a normal distribution.
  - **Parameters**: None.
  - **Result**: Per-column excess kurtosis, the most-extreme feature, and a bar chart.

Notes
~~~~~

- **Local vs. Web Application**:
  - The local installation requires setting up Redis, Celery, and Flask (see :ref:`Web Application Installation <web_installation>`). The web application at `aidrin.org <https://aidrin.org>`_ handles these server-side, offering a no-setup alternative.
  - Both use the same codebase, ensuring identical functionality. The web application is ideal for users who prefer a browser-based interface.

- **File Formats**: The web application supports CSV, Excel, JSON, NumPy (``.npz``),
  HDF5 (``.h5``), and Parquet (``.parquet``) files for data uploads, and
  DCAT/DataCite JSON for metadata
  in the Understandability and Usability dimension.  For HDF5 files, fill-value
  sentinels (``_FillValue``, ``missing_value``, and the HDF5 native fill value) are
  automatically converted to ``NaN`` so that all metrics — completeness, outliers,
  feature relevance, and privacy — operate on accurately marked missing data.  See
  the ``calculate_completeness`` note in :ref:`python_api` for the full
  sentinel-resolution order.
  Custom Criteria Outliers can evaluate tabular columns, JSON/NetCDF-style column
  targets discovered by the inspector, and native HDF5 datasets.
- **Visualizations**: Generated downloadable plots (e.g., histograms, bar charts, heatmaps) are displayed in the web interface.
- **JSON Reports**: Each dimension's analysis generates a downloadable JSON report containing all metrics, statistics, and visualization data (where applicable).

----

Remote Datasets (Globus)
------------------------

AIDRIN can run metrics on a remote machine via `Globus Compute
<https://www.globus.org/compute>`_, so large datasets never have to be
transferred to the AIDRIN server. Only the results travel back.

This is optional. Install the extra to enable it:

.. code-block:: bash

   pip install "aidrin[globus]"

**One-time setup**

1. Register an application at `developers.globus.org <https://developers.globus.org/>`_.
2. Set the client ID before starting the server:

   .. code-block:: bash

      export GLOBUS_CLIENT_ID=<your-client-id>

   Set ``GLOBUS_CLIENT_SECRET`` as well if you registered a confidential client.

**Set up an endpoint on the machine holding your data**

.. code-block:: bash

   pip install globus-compute-endpoint aidrin

   globus-compute-endpoint configure aidrin-endpoint
   globus-compute-endpoint start aidrin-endpoint

   # Copy the UUID; you will paste it into the web interface
   globus-compute-endpoint list

Stop an endpoint with ``globus-compute-endpoint stop <name>``. For local
testing you can run an endpoint on the same machine under a different name.

The endpoint machine needs ``aidrin`` installed, network access to
authenticate with Globus, and the dataset reachable at the path you enter.

**Running a remote analysis**

1. Select the **Remote (Globus)** tab.
2. Click **Sign in with Globus**, which redirects to Globus Auth.
3. Paste the Globus Compute endpoint UUID.
4. Enter the file path as it exists on the remote machine, e.g.
   ``/home/user/data/adult.csv``.
5. Choose the file type and click **Load Remote Dataset**.
6. Run metrics as usual. Computation happens on the endpoint; only results
   come back.

AI Explanations
---------------

AIDRIN can annotate each metric result with a short plain-language
interpretation, generated by any OpenAI-compatible API (OpenAI, Azure OpenAI,
Ollama, vLLM, and similar).

This is optional. Install the extra to enable it:

.. code-block:: bash

   pip install "aidrin[llm]"

When the ``openai`` package is absent the feature is hidden entirely, with no
overhead.

**Setup**

1. Click the sparkle icon in the top-right toolbar to open the AI settings.
2. Enter the API base URL, API key, and model name.
3. Click **Test** to verify the connection, then **Save**.

Every metric result then shows an **AI Explanation** callout beneath it.

- **API Base URL**: base URL of the OpenAI-compatible API. Defaults to
  ``https://api.openai.com/v1``; for Ollama use ``http://localhost:11434/v1``.
- **API Key**: stored in the server-side Flask session only. It is never
  exposed to client-side JavaScript or written to logs.
- **Model**: the model identifier, e.g. ``gpt-4o-mini`` or ``llama3``.

**What is sent to the model**

- The metric name and description, as context
- The metric scores and values, as JSON
- The plot image as a base64 PNG, if the model supports vision

If the model does not support vision, AIDRIN retries automatically with
text-only input. The model name appears in the explanation callout so it is
always clear what produced the text.

.. note::

   To try this without an API key, run Ollama locally:

   .. code-block:: bash

      ollama serve
      ollama pull llama3

   Then set the base URL to ``http://localhost:11434/v1``, the API key to any
   non-empty string, and the model to ``llama3``.

----

.. _web_usage_custom_metrics:

Custom Metrics and Remedies
----------------------------

This section explains how to define custom metrics and remediation logic for your uploaded CSV files
using the **CustomDR** class inside the CodeMirror editor. After uploading a dataset, you
will navigate to a page where you can write Python code that extends the platform's data-review logic.

Workflow
~~~~~~~~

1. Navigate to the file upload page and upload a CSV file.
2. After upload, click the **Define Custom Metrics** button. You will be redirected to ``/customMetrics``.
3. A CodeMirror Python editor appears, preloaded with an editable ``CustomDR`` class that inherits from ``BaseDRAgent`` and contains two methods:
   - ``metric()``: returns a dictionary of metric results.
   - ``remedy()``: returns a modified dataset based on your remediation logic.
4. Write or modify your code inside the editor.
5. Press **Save** to store your custom logic on the server (temporary, 1-hour expiration).
6. Press **Submit** to execute your ``metric()`` function, and optionally your ``remedy()`` function if you have checked the **Apply Remedy** box.

The platform will display your computed metric dictionary, any remediated dataset to download (if remedy is enabled), and any warnings or errors raised by your code.

Understanding the ``CustomDR`` Base Class
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Below is the template initially shown in CodeMirror:

.. code-block:: python

    from aidrin.custom_metrics.base_dr import BaseDRAgent
    from typing import Any
    from typing import Dict, Union, Any

    class CustomDR(BaseDRAgent):
        def __init__(self, dataset: Any, **kwargs):
            super().__init__(dataset, **kwargs)

        def metric(self, **kwargs):
            """
            Implement your custom metric logic here.
            """

            # IMPLEMENT YOUR METRIC LOGIC BELOW
            # Example: Calculating the total number of missing cells in the entire DataFrame

            # df: pd.DataFrame = self.dataset
            # return {
            #   "total_missing_cells": df.isna().sum().to_dict()
            # }

            return {"message": "Placeholder metric. Implement your logic here."}

        def remedy(self, **kwargs**):
            """
            Applies custom remediation logic based on the calculated metrics.
            """

            # IMPLEMENT YOUR REMEDIATION LOGIC BELOW
            # For example, filling null values with a default value

            # df_remedied: pd.DataFrame = self.dataset.copy()
            # df_remedied.fillna(0, inplace=True)
            # return df_remedied

            return self.dataset

The goal is to replace the placeholder logic with your own custom metric and remediation steps.

Implementing ``metric()``: Requirements and Tips
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Your ``metric()`` method:

- Must return a **dictionary** whose keys are metric names and values are computed results.
- Receives the dataset through ``self.dataset``.
- May accept additional keyword arguments (depending on future UI extensions).
- Should not mutate the dataset; all transformations belong in ``remedy()``.

Example: Compute missing values, row count, and column datatypes.

.. code-block:: python

    def metric(self, **kwargs):
        df = self.dataset

        return {
            "row_count": len(df),
            "column_count": df.shape[1],
            "missing_values": df.isna().sum().to_dict(),
            "dtypes": df.dtypes.apply(lambda x: str(x)).to_dict(),
        }

Implementing ``remedy()``: Requirements and Tips
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``remedy()`` method receives the ``metric_results`` dictionary returned by ``metric()``.
Use this method when you want to apply data-cleaning or transformation logic based on your computed metrics. Or, you can modify the dataset directly without relying on ``metric_results``.

You must return the updated dataset at the end of ``remedy()``.

Full Practical Example: A Combined Metric and Remedy Class
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The example below shows both ``metric()`` and ``remedy()`` implemented in a realistic workflow.

.. code-block:: python

    from aidrin.custom_metrics.base_dr import BaseDRAgent
    import pandas as pd
    from typing import Dict, Union, Any

    class CustomDR(BaseDRAgent):
        """
        An agent focused on detecting and removing duplicate rows.
        """

        def __init__(self, dataset: Any, **kwargs):
            super().__init__(dataset, **kwargs)

        def metric(self, **kwargs) -> Dict[str, int]:
            """
            Calculates the total count of duplicate rows.
            """
            df: pd.DataFrame = self.dataset
            duplicate_rows_count: int = df.duplicated().sum()

            return {
                "duplicate_rows_total": duplicate_rows_count,
            }

        def remedy(self, metric_results: Dict[str, Any]) -> pd.DataFrame:
            """
            Removes duplicate rows using the calculated metric results.
            """
            # Create a copy for safe modification to prevent side effects on the original state.
            df_remedied: pd.DataFrame = self.dataset.copy()

            duplicate_count = metric_results.get("duplicate_rows_total", 0)

            if duplicate_count > 0:
                df_remedied.drop_duplicates(inplace=True)

            return df_remedied

How the System Uses Your CustomDR Class
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When you click **Submit**:

1. Your code is dynamically loaded and executed in an isolated environment.
2. The system creates an instance of your ``CustomDR`` class.
3. The system calls your ``metric()`` method to compute metrics.
4. If **Apply Remedy** is checked, the system calls your ``remedy()`` method to get the modified dataset.
5. Metrics and (optionally) the remedied data preview are displayed on the results section of the page.

Best Practices for Writing Custom Metrics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Do not mutate the dataset inside ``metric()``.**
  All modifications belong in ``remedy()``.
- Work on a **copy** of ``self.dataset`` in ``remedy()`` to avoid side effects.
- Always return the modified dataset at the end of ``remedy()``.

Data and Code Storage Rules
~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Your custom metric code is stored temporarily for **1 hour**.
- The (optional) remedied dataset is also stored for **1 hour**.
- After expiration, all artifacts are safely removed.
