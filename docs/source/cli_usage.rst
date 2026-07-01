.. _cli_usage:

CLI Usage
=========

Quick Start
-----------

.. code-block:: bash

   # Fast data quality assessment (completeness, duplicates, outliers)
   aidrin data-quality /path/to/sample_dataset.csv

   # List all available metrics
   aidrin list

   # Run a single metric
   aidrin run completeness /path/to/sample_dataset.csv

   # Run a batch of metrics from a YAML config
   aidrin batch /path/to/my_project/batch_config.yaml

----

Sample Dataset
--------------

All examples on this page use a single CSV file. You can also find ready-to-use sample
datasets in ``examples/sample_data/`` in the repository.

For the following example, run the following Python snippet
once to generate a synthetic datasets yourself — then substitute ``/path/to/sample_dataset.csv`` with the
actual path where you saved it:

.. code-block:: python

   import pandas as pd

   data = {
       "age":          [34, 28, 42, 31, 25, 34, 38, 45, 29, 33],
       "income":       [75000, 45000, 95000, 55000, 35000, 75000, 85000, 950000, 42000, None],
       "credit_score": [720, 650, 780, 690, 600, 720, 750, 800, 620, 700],
       "education":    ["bachelor","high_school","master","bachelor","high_school",
                        "bachelor","bachelor","master","bachelor","bachelor"],
       "gender":       ["male","female","male","female","male","male","female","male","female","male"],
       "ethnicity":    ["white","hispanic","asian","black","white","white","asian","white","hispanic","black"],
       "zipcode":      [43201, 43201, 43202, 43202, 43203, 43201, 43203, 43204, 43204, 43205],
       "diagnosis":    ["diabetes","hypertension","diabetes","hypertension","asthma",
                        "diabetes","hypertension","asthma","diabetes","hypertension"],
       "approved":     [1, 0, 1, 1, 0, 1, 1, 1, 0, 0],
   }
   pd.DataFrame(data).to_csv("/path/to/sample_dataset.csv", index=False)

The dataset intentionally includes one duplicate row (rows 1 and 6), one missing
``income`` value (row 10), and one income outlier (row 8) so that completeness,
duplicity, and outlier metrics return non-trivial results.



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

   aidrin data-quality /path/to/sample_dataset.csv

   # Output full per-feature JSON instead of summary
   aidrin data-quality /path/to/sample_dataset.csv --detail

``aidrin run``
~~~~~~~~~~~~~~

Runs a single metric. Use ``aidrin run <metric> -h`` to see required arguments for that metric.

.. code-block:: bash

   # General form
   aidrin run <metric-name> /path/to/sample_dataset.csv [metric-specific args]

   # Shortcut: omit the "run" subcommand
   aidrin <metric-name> /path/to/sample_dataset.csv [metric-specific args]

Examples:

.. code-block:: bash

   # Data quality (no extra args needed)
   aidrin run completeness /path/to/sample_dataset.csv
   aidrin run duplicity /path/to/sample_dataset.csv
   aidrin run outliers /path/to/sample_dataset.csv

   # Impact on AI
   aidrin run correlations /path/to/sample_dataset.csv "age,income,credit_score"
   aidrin run feature-relevance /path/to/sample_dataset.csv "gender,education" "age,income,credit_score" approved

   # Fairness & bias
   aidrin run class-imbalance /path/to/sample_dataset.csv approved
   aidrin run statistical-rates /path/to/sample_dataset.csv approved gender
   aidrin run representation-rate /path/to/sample_dataset.csv "gender,ethnicity"

   # Data governance / privacy
   aidrin run k-anonymity /path/to/sample_dataset.csv "age,zipcode,gender"
   aidrin run l-diversity /path/to/sample_dataset.csv "age,zipcode" diagnosis
   aidrin run t-closeness /path/to/sample_dataset.csv "age,zipcode" diagnosis
   aidrin run entropy-risk /path/to/sample_dataset.csv "age,zipcode,gender"

Options available on all ``run`` subcommands:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Flag
     - Description
   * - ``-v``, ``--verbose``
     - Show progress output while the metric runs

``aidrin batch``
~~~~~~~~~~~~~~~~

Runs a set of metrics defined in a JSON or YAML config file. Useful for reproducible pipelines.

.. code-block:: bash

   aidrin batch /path/to/my_project/batch_config.yaml
   aidrin batch /path/to/my_project/batch_config.yaml -v          # verbose

Results are printed as JSON to stdout. Redirect to a file to save:

.. code-block:: bash

   aidrin batch /path/to/my_project/batch_config.yaml > results.json

**Config file format (YAML):**

.. code-block:: yaml

   file-path: /path/to/sample_dataset.csv
   file-type: .csv

   metrics:
     - completeness
     - duplicity
     - outliers
     - class-imbalance

   target-column: approved

**Example** — fairness analysis on the sample dataset:

.. code-block:: yaml

   # /path/to/my_project/fairness_config.yaml

   file-path: /path/to/sample_dataset.csv
   file-type: .csv

   metrics:
     - statistical-rates
     - representation-rate
     - class-imbalance

   target-column: approved
   sensitive-attribute-column: ethnicity
   columns:
     - gender
     - ethnicity

.. code-block:: bash

   aidrin batch /path/to/my_project/fairness_config.yaml > fairness_results.json

``aidrin add-custom-module``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Scaffolds a new custom metric module in a directory of your choice. Custom metrics live
entirely outside the AIDRIN package — you own the file.

.. code-block:: bash

   aidrin add-custom-module my_audit --dir /path/to/my_project

This creates ``/path/to/my_project/my_audit.py`` with a ``metric()`` and a ``remedy()`` method.
Edit those methods to add your logic, then run by passing the file path directly:

.. code-block:: bash

   aidrin run custom /path/to/my_project/my_audit.py /path/to/sample_dataset.csv metric    # run the metric
   aidrin run custom /path/to/my_project/my_audit.py /path/to/sample_dataset.csv remedy    # run the remedy

The remedy output CSV is saved to a ``remedy_data/`` folder next to the module file
(``/path/to/my_project/remedy_data/my_audit_remedy.csv``).

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
     - ``<name-or-path>``, varies — see ``aidrin run custom -h``

Metric and category names accept either dashes or underscores interchangeably
(e.g. ``class-imbalance`` and ``class_imbalance`` are equivalent).

----

Using AIDRIN as a Python Library
---------------------------------

All CLI metrics are also available as a Python API for use in notebooks or scripts:

.. code-block:: python

   from aidrin.headless import run_metric, run_data_quality, run_batch_metrics
   from aidrin.headless import HeadlessConfig

   # Single metric
   result = run_metric("completeness", "/path/to/sample_dataset.csv")

   # Fast data quality bundle
   result = run_data_quality("/path/to/sample_dataset.csv")

   # Batch from config
   config = HeadlessConfig.from_file("/path/to/my_project/batch_config.yaml")
   result = run_batch_metrics(config)

For the web interface's lower-level functional API, see the :ref:`web_usage` page.

----

.. _agentic_integration:

Agentic Evaluation
------------------

The **agentic evaluation** component extends the AIDRIN CLI with a question-answering layer for
domain-aware data readiness assessment. Where the ``aidrin`` CLI runs quantitative, metric-driven
evaluations, the agentic component lets you pose natural-language questions about your data against
a body of domain literature — papers, regulatory documents, standards — and receive evidence-backed
answers along with actionable remediation recommendations.

.. note::

   The agentic component is an optional extra (``aidrin[agentic]``) because it requires LLM API
   access and additional dependencies not needed for standard CLI or web interface use.
   See :ref:`cli_installation` for installation instructions.


How It Works
~~~~~~~~~~~~

Each question is processed through a five-stage pipeline:

1. **Data Profiler** — loads the dataset and computes compact summary statistics (row/column
   counts, means, missing-value ratios, top categories) to give the LLM structural context about
   the data.

2. **Vector Retriever** — searches a pre-built FAISS vector index of your domain literature (PDFs,
   text files) to retrieve the most relevant passages for each question. When retrieval is
   disabled, the LLM answers from its own knowledge and the dataset profile alone.

3. **Code Executor** — uses the retrieved passages and dataset profile to prompt an LLM to write
   executable Python/pandas code, then runs that code directly against the dataset. A self-healing
   loop automatically repairs failing code, up to a configurable number of attempts
   (``executor.max_attempts``).

4. **Complexity Scorer** — classifies each query as ``easy``, ``moderate``, or ``hard`` based on
   three dimensions: profile dependency, domain-knowledge dependency, and code complexity.

5. **Remediation Generator** — synthesises concrete, domain-grounded remediation recommendations
   for each finding, citing the same domain literature used during retrieval.

Multiple questions are processed in parallel via a configurable thread pool
(``retrieval.max_workers``). Results are printed to stdout and optionally written to a JSON file.


Commands
~~~~~~~~

Two subcommands are available under ``aidrin agentic``:

.. code-block:: bash

   # Build (or rebuild) the vector index from your domain literature
   aidrin agentic build-index -c /path/to/my_project/config.yaml

   # Run the full evaluation pipeline
   aidrin agentic run -c /path/to/my_project/config.yaml -o /path/to/my_project/results.json

   # Run without rebuilding the index (use an existing one)
   aidrin agentic run -c /path/to/my_project/config.yaml --skip-vector -o results.json

All paths in ``config.yaml`` are resolved relative to the config file itself, so your project
directory can live anywhere on disk.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Flag
     - Description
   * - ``-c`` / ``--config``
     - Path to the YAML config file **(required)**
   * - ``-o`` / ``--output``
     - Path to write JSON results (optional; results are always printed to stdout regardless)
   * - ``--skip-vector``
     - Skip rebuilding the vector index and use the existing one (``run`` only)
   * - ``-v`` / ``--verbose``
     - Print vector build progress to stderr

.. warning::

   **The embedding model must not change between** ``build-index`` **and** ``run``.

   If a different ``vector_store.embedding_model`` is set in the config when ``run`` is executed,
   AIDRIN will raise an error immediately. To switch models, re-run ``build-index`` with the new model before calling ``run``.


Quickstart: UCI Power Consumption Dataset
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This end-to-end example uses the
`UCI Individual Household Electric Power Consumption
<https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption>`_
dataset — a real-world time-series dataset of ~2 million minute-level household energy readings.

Step 1: Add the dataset
^^^^^^^^^^^^^^^^^^^^^^^

The repository includes a ready-to-use example project at
``examples/agentic/power_consumption/``. Download
``household_power_consumption.zip`` from the UCI link above, extract it, and place the ``.txt``
file in the ``data/`` subdirectory:

Step 2: Add domain literature
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Download papers that cite the dataset (published 2016–2026) in the link above, and place their PDFs in
``examples/agentic/power_consumption/sources/``.

Your example project directory should then look like this:

.. code-block:: text

   examples/agentic/power_consumption/
   ├── config.yaml          ← pre-configured, ready to use
   ├── loader.py            ← handles the semicolon-separated .txt format
   ├── data/
   │   ├── metadata.txt                          ← included in repo
   │   └── household_power_consumption.txt       ← add this
   └── sources/
       ├── paper1.pdf                            ← add one or more PDFs here
       └── ...

Step 3: Configure your API key and endpoint
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The included ``config.yaml`` is pre-configured for the standard OpenAI API. Set the environment
variable to the key your endpoint requires:

.. code-block:: bash

   export OPENAI_API_KEY="sk-..."

If you are using a different OpenAI compatible endpoint (e.g. LBL CBORG), update ``llm.base_url``
in the config and ensure all ``model`` and ``embedding_model`` values are names available on that
provider:

.. code-block:: yaml

   # examples/agentic/power_consumption/config.yaml

   paths:
     data_loader: "./loader.py:load_dataset"
     metadata_csv: "./data/metadata.txt"

   llm:
     base_url: "https://api.openai.com/v1"   # replace with your OpenAI compatible endpoint, e.g. https://api.cborg.lbl.gov

   profiling:
     full_summary: false

   vector_store:
     sources:
       - ./sources
     embedding_model: text-embedding-ada-002
     chunk_size: 1000
     chunk_overlap: 200
     vector_store_name: power_consumption_index

   retrieval:
     enabled: true
     max_workers: 4
     answer_model: gpt-4o
     top_k: 3
     question:
       - "Which European Union regulation is cited as requiring that the consequences of profiling be informed to the data subject? Return the name of the regulation as a string."
       - "Return True if more than 80% of the data is resampled to align with the widely adopted industry standards for smart meter technology to reduce behavioral noise. Return False if not."

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

   output:
     save_log: true

Step 4: Build the vector index
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Run this once. Re-run only when your literature changes:

.. code-block:: bash

   aidrin agentic build-index -c examples/agentic/power_consumption/config.yaml

Step 5: Run the pipeline
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   aidrin agentic run \
     -c examples/agentic/power_consumption/config.yaml \
     -o examples/agentic/power_consumption/results.json

On subsequent runs, skip rebuilding the index with ``--skip-vector``:

.. code-block:: bash

   aidrin agentic run \
     -c examples/agentic/power_consumption/config.yaml \
     --skip-vector \
     -o examples/agentic/power_consumption/results.json

Results are printed to stdout and written to ``examples/agentic/power_consumption/results.json``. Each result includes the question,
the answer, the retrieved passages that informed it, the generated code (if applicable), a
complexity classification, and remediation recommendations.


Using Your Own Dataset
~~~~~~~~~~~~~~~~~~~~~~

Follow the same steps, substituting your own dataset and literature.

Step 1: Set up your project directory
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

   ~/my_project/
   ├── config.yaml
   ├── loader.py
   ├── data/
   │   ├── my_data.csv          # your dataset
   │   └── metadata.txt         # column-level descriptions (plain text or CSV)
   └── sources/                 # domain literature to index (PDF or TXT)
       ├── reference.pdf
       └── standards.txt

Step 2: Define your custom data loader
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Implement ``loader.py`` in your project directory with a function ``load_dataset`` that returns a ``pandas.DataFrame`` of your dataset.
This gives you full control over loading logic, and support for any file format.:

.. code-block:: python

   # ~/my_project/loader.py
   import pandas as pd
   from pathlib import Path

   def load_dataset() -> pd.DataFrame:
       return pd.read_csv(Path(__file__).parent / "data/my_data.csv")

Then reference it in ``config.yaml`` via ``paths.data_loader`` (see Step 4). For datasets that
require more complex loading — multiple files, Parquet, HDF5, etc. — replace the body of
``load_dataset`` with whatever logic you need; the only requirement is that it returns a
``pandas.DataFrame``.

Step 3: Add domain literature
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Place your domain literature (PDFs, text files) in ``sources/`` and your dataset in ``data/``.

Step 4: Configure your API key and write a config file
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Set the environment variable to the key your endpoint requires:

.. code-block:: bash

   export OPENAI_API_KEY="sk-..."

Then create ``config.yaml``. If you are using a different OpenAI compatible endpoint (e.g. LBL CBORG), update
``llm.base_url`` to point to it and ensure all ``model`` and ``embedding_model`` values are names
available on that provider:

.. code-block:: yaml

   # ~/my_project/config.yaml

   llm:
     base_url: "https://api.openai.com/v1"   # replace with your OpenAI-compatible endpoint, e.g. https://api.cborg.lbl.gov

   paths:
     data_loader: "./loader.py:load_dataset"   # module:function relative to config dir
     metadata_csv: "./data/metadata.txt"

   profiling:
     full_summary: false

   vector_store:
     sources:
       - ./sources
     embedding_model: text-embedding-ada-002
     chunk_size: 1000
     chunk_overlap: 200
     vector_store_name: my_project_index # name for the FAISS index that will be created

   retrieval:
     enabled: true
     max_workers: 8
     answer_model: gpt-5.2
     top_k: 3
     question:
       - "Does the age feature satisfy the HIPAA Safe Harbor de-identification standard?"

   executor:
     enabled: true
     max_attempts: 5
     model: gpt-5.2
     temperature: 0.0

   complexity_scorer:
     enabled: true
     model: gpt-5.2

   remediation:
     enabled: true
     model: gpt-5.2
     context_chars: 3000

Step 5: Build the index and run
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   aidrin agentic build-index -c ~/my_project/config.yaml
   aidrin agentic run -c ~/my_project/config.yaml -o ~/my_project/results.json
