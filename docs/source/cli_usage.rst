.. _cli_usage:

CLI Usage
=========

Quick Start
-----------

.. code-block:: bash

   # Fast data quality assessment (completeness, duplicates, outliers)
   aidrin data-quality path/to/dataset.csv

   # List all available metrics
   aidrin list

   # Run a single metric
   aidrin run completeness path/to/dataset.csv

   # Run a batch of metrics from a YAML config
   aidrin batch path/to/config.yaml

----

Commands
--------

``aidrin list``
~~~~~~~~~~~~~~~

Lists all available metrics grouped by category.

.. code-block:: bash

   aidrin list

   # Filter by category
   aidrin list --category data-quality

``aidrin data-quality``
~~~~~~~~~~~~~~~~~~~~~~~

Runs the three core data quality metrics (completeness, duplicity, and outliers) in one shot and
prints a compact summary.

.. code-block:: bash

   aidrin data-quality path/to/dataset.csv

   # Output full per-feature JSON instead of summary
   aidrin data-quality path/to/dataset.csv --detail

   # Specify file type explicitly
   aidrin data-quality path/to/dataset.csv --file-type .csv

``aidrin run``
~~~~~~~~~~~~~~

Runs a single metric. Use ``aidrin run <metric> -h`` to see required arguments for that metric.

.. code-block:: bash

   # General form
   aidrin run <metric-name> path/to/dataset.csv [metric-specific args]

   # Shortcut: omit the "run" subcommand
   aidrin <metric-name> path/to/dataset.csv [metric-specific args]

Examples:

.. code-block:: bash

   # Data quality (no extra args needed)
   aidrin run completeness data.csv
   aidrin run duplicity data.csv
   aidrin run outliers data.csv

   # Impact on AI
   aidrin run correlations data.csv "age,income,education"
   aidrin run feature-relevance data.csv "gender,education" "age,income,credit_score" approved

   # Fairness & bias
   aidrin run class-imbalance data.csv income
   aidrin run statistical-rates data.csv income gender
   aidrin run representation-rate data.csv "gender,ethnicity"

   # Data governance / privacy
   aidrin run k-anonymity data.csv "age,zipcode,gender"
   aidrin run l-diversity data.csv "age,zipcode" diagnosis
   aidrin run t-closeness data.csv "age,zipcode" diagnosis
   aidrin run entropy-risk data.csv "age,zipcode,gender"

Options available on all ``run`` subcommands:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Flag
     - Description
   * - ``-v``, ``--verbose``
     - Show progress output while the metric runs
   * - ``--file-type``
     - Override file type detection (e.g. ``--file-type .csv``)

``aidrin batch``
~~~~~~~~~~~~~~~~

Runs a set of metrics defined in a JSON or YAML config file. Useful for reproducible pipelines.

.. code-block:: bash

   aidrin batch path/to/config.yaml
   aidrin batch path/to/config.yaml -v          # verbose
   aidrin batch path/to/config.yaml --viz       # include visualization data in output

Config file format (YAML):

.. code-block:: yaml

   file-path: path/to/dataset.csv
   file-type: .csv

   metrics:
     - completeness
     - duplicity
     - outliers
     - class-imbalance

   target-column: income

Results are printed as JSON to stdout. Redirect to a file to save:

.. code-block:: bash

   aidrin batch config.yaml > results.json

``aidrin add-custom-module``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Scaffolds a new custom metric module in the ``aidrin/custom_metrics/`` directory.

.. code-block:: bash

   aidrin add-custom-module my_audit

This creates ``aidrin/custom_metrics/my_audit.py`` with a ``metric()`` and a ``remedy()`` method.
Edit those methods to add your logic, then run via:

.. code-block:: bash

   aidrin run custom my_audit data.csv metric    # run the metric
   aidrin run custom my_audit data.csv remedy    # run the remedy and save corrected CSV

----

Available Metrics
-----------------

.. list-table::
   :header-rows: 1
   :widths: 25 25 50

   * - Category
     - Metric
     - Required Args
   * - Data Quality
     - ``completeness``
     - —
   * - Data Quality
     - ``duplicity``
     - —
   * - Data Quality
     - ``outliers``
     - —
   * - Impact on AI
     - ``correlations``
     - ``columns``
   * - Impact on AI
     - ``feature-relevance``
     - ``categorical-columns``, ``numerical-columns``, ``target-column``
   * - Fairness & Bias
     - ``class-imbalance``
     - ``target-column``
   * - Fairness & Bias
     - ``statistical-rates``
     - ``target-column``, ``sensitive-attribute-column``
   * - Fairness & Bias
     - ``representation-rate``
     - ``columns``
   * - Data Governance
     - ``k-anonymity``
     - ``quasi-identifiers``
   * - Data Governance
     - ``l-diversity``
     - ``quasi-identifiers``, ``sensitive-column``
   * - Data Governance
     - ``t-closeness``
     - ``quasi-identifiers``, ``sensitive-column``
   * - Data Governance
     - ``entropy-risk``
     - ``quasi-identifiers``
   * - Data Governance
     - ``single-attribute-risk``
     - ``id-column``, ``eval-columns``
   * - Data Governance
     - ``multiple-attribute-risk``
     - ``id-column``, ``eval-columns``
   * - Custom
     - ``custom``
     - varies — see ``aidrin run custom -h``

Metric and category names accept either dashes or underscores interchangeably
(e.g. ``class-imbalance`` and ``class_imbalance`` are equivalent).

----

Batch Config Examples
---------------------

Example configs are bundled in the ``headless_demos/`` directory:

.. code-block:: bash

   # Data quality on a sensor dataset
   aidrin batch headless_demos/01_data_quality.yaml

   # Feature analysis on loan applications
   aidrin batch headless_demos/02_feature_analysis.yaml

   # Fairness metrics
   aidrin batch headless_demos/03_fairness.yaml

   # Privacy / data governance
   aidrin batch headless_demos/04_privacy.yaml

----

Using AIDRIN as a Python Library
---------------------------------

All CLI metrics are also available as a Python API for use in notebooks or scripts:

.. code-block:: python

   from aidrin.headless import run_metric, run_data_quality, run_batch_metrics
   from aidrin.headless import HeadlessConfig

   # Single metric
   result = run_metric("completeness", "path/to/data.csv")

   # Fast data quality bundle
   result = run_data_quality("path/to/data.csv")

   # Batch from config
   config = HeadlessConfig.from_file("config.yaml")
   result = run_batch_metrics(config)

For the web interface's lower-level functional API, see the :ref:`web_usage` page.

----

.. _adroit_integration:

ADROIT
------

**ADROIT** (Agentic Data Readiness via Orchestrated Intelligent Toolkit) is an LLM-powered data
readiness agent built on top of the AIDRIN CLI. While the ``aidrin`` CLI runs quantitative,
metric-driven evaluations, ADROIT adds a *question-answering* layer: given domain-specific
literature (papers, regulatory documents, standards), ADROIT automatically answers data readiness
questions against an actual dataset and generates actionable, domain-grounded remediation
recommendations.

ADROIT is provided as a separate optional extra (``aidrin[adroit]``) because it requires LLM API
access and heavier dependencies not needed for standard CLI or web interface use. See
:ref:`cli_installation` for installation instructions.

How ADROIT Works
~~~~~~~~~~~~~~~~

ADROIT runs a five-stage pipeline for each data readiness question:

1. **Data Profiler** — loads the dataset and computes compact summary statistics (counts, means,
   missing ratios, top categories) to give the LLM structural context about the data.

2. **Vector Retriever** — searches a pre-built FAISS vector index of domain literature (PDFs, text
   files) to retrieve the most relevant passages for each question. If retrieval is disabled, the LLM
   answers from its own knowledge and the dataset profile alone.

3. **Code Executor** — uses the retrieved context and profile to prompt an LLM to write executable
   Python/pandas code, then runs that code directly against the dataset. A self-healing loop
   automatically repairs failing code, up to a configurable number of attempts.

4. **Complexity Scorer** — scores each query on three dimensions (profile dependency, domain
   knowledge dependency, code complexity) to classify queries as ``easy``, ``moderate``, or ``hard``.

5. **Remediation Generator** — synthesises concrete, domain-grounded remediation recommendations
   for each finding, citing the same domain literature used during retrieval.

Multiple questions can be processed in parallel via a configurable thread pool
(``retrieval.max_workers``). All results are written to a timestamped JSON log.

Worked Example: UCI Power Consumption Dataset
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This end-to-end example walks through using ADROIT on the
`UCI Individual Household Electric Power Consumption <https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption>`_
dataset — a real-world time-series dataset of ~2 million minute-level household energy readings
with known data quality challenges including ~1.25% missing values.

The metadata, domain literature PDFs, and config are already bundled with the package.
The only file you need to supply is the dataset itself.

**Step 1: Set your API key**

.. code-block:: bash

   export OPENAI_API_KEY="sk-..."

**Step 2: Download and place the dataset**

Download ``household_power_consumption.zip`` from:

   https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption

Extract and place ``household_power_consumption.txt`` at:

.. code-block:: text

   aidrin/adroit/
   ├── configs/
   │   └── power_consumption.yaml              ← bundled
   └── use_cases/
       └── power_consumption/
           ├── data/
           │   ├── metadata.txt                ← bundled
           │   └── household_power_consumption.txt  ← add this
           └── sources/
               └── *.pdf                       ← bundled

**Step 3: Build the vector store** (run once)

.. code-block:: bash

   python -m aidrin.adroit.vector_db_builder -c aidrin/adroit/configs/power_consumption.yaml

**Step 4: Run the pipeline**

.. code-block:: bash

   python -m aidrin.adroit.run -c aidrin/adroit/configs/power_consumption.yaml -o aidrin/adroit/results/power_consumption.json

Output is printed to stdout and written to the specified JSON file.

Using ADROIT with Your Own Dataset
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Follow the same four steps, substituting your own dataset and literature.

**Step 1: Set your API key**

.. code-block:: bash

   export OPENAI_API_KEY="sk-..."

**Step 2: Prepare your dataset and domain literature**

.. code-block:: text

   aidrin/adroit/use_cases/
   └── my_dataset/
       ├── data/
       │   ├── my_data.csv       # the dataset
       │   └── metadata.csv      # column-level metadata (CSV or plain text)
       └── sources/              # domain literature to index (PDF, TXT)
           ├── reference.pdf
           └── standards.txt

**Step 3: Write a YAML config**

.. code-block:: yaml

   # aidrin/adroit/configs/my_dataset.yaml

   paths:
     data_csv: "./use_cases/my_dataset/data/my_data.csv"
     metadata_csv: "./use_cases/my_dataset/data/metadata.csv"

   profiling:
     full_summary: false

   vector_store:
     sources:
       - ./use_cases/my_dataset/sources
     embedding_model: text-embedding-3-large
     chunk_size: 1000
     chunk_overlap: 200
     vector_store_name: my_dataset_vector_store

   retrieval:
     enabled: true
     max_workers: 8
     answer_model: gpt-4o
     top_k: 3
     question:
       - "Does the age feature satisfy the HIPAA Safe Harbor de-identification standard?"

   executor:
     enabled: true
     max_attempts: 5
     model: gpt-4o
     temperature: 0.0

   complexity_scorer:
     enabled: true
     model: gpt-4o

   remediation:
     enabled: true
     model: gpt-4o
     context_chars: 3000

**Step 4: Build the vector store and run**

.. code-block:: bash

   python -m aidrin.adroit.vector_db_builder -c aidrin/adroit/configs/my_dataset.yaml
   python -m aidrin.adroit.run -c aidrin/adroit/configs/my_dataset.yaml -o aidrin/adroit/results/output.json

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Flag
     - Description
   * - ``-c`` / ``--config``
     - Path to YAML config (required)
   * - ``-o`` / ``--output``
     - Path to write JSON results (optional; also printed to stdout)

Custom Data Loaders
~~~~~~~~~~~~~~~~~~~

For datasets that require custom loading logic (multiple files, Parquet, HDF5, etc.), write a
Python function that returns a ``pandas.DataFrame`` and reference it in the YAML config:

.. code-block:: python

   # my_project/loaders.py
   import pandas as pd
   from pathlib import Path

   def load_dataset() -> pd.DataFrame:
       return pd.read_parquet(Path("use_cases/my_dataset/data/my_data.parquet"))

.. code-block:: yaml

   paths:
     data_loader: "my_project.loaders:load_dataset"
     metadata_csv: "./use_cases/my_dataset/data/metadata.csv"

The built-in loader for the power consumption example is at:

.. code-block:: text

   aidrin.adroit.dataloaders.power_consumption:load_dataset
