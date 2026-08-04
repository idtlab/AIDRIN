.. AIDRIN documentation master file

AIDRIN Documentation
====================

**AIDRIN** (AI Data Readiness Infrastructure) is an open-source tool for
evaluating whether a dataset is ready for artificial intelligence and machine
learning work. It scores quality, structure, fairness, and privacy risk, and
returns the results as plots and machine-readable JSON. Use it from a browser,
a terminal, a notebook, or Claude Code.

It reads CSV, Excel, JSON, NumPy (``.npz``), HDF5, and Parquet, plus DCAT and
DataCite JSON for metadata.

----

Six Dimensions of Data Readiness
--------------------------------

AIDRIN groups its metrics into six dimensions. Each is documented in
:ref:`web_usage`; :ref:`metric_names` maps every metric between the web
interface, the command line, and the Python library.

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Dimension
     - What it measures
   * - **Data Quality**
     - Completeness, duplicates, and outliers, including row-level and temporal completeness and custom validity rules
   * - **Impact of Data on AI**
     - Feature correlation and how strongly each feature relates to your target
   * - **Fairness and Bias**
     - Class imbalance, representation rates, and statistical parity across sensitive attributes
   * - **Data Governance**
     - Re-identification risk: k-anonymity, l-diversity, t-closeness, entropy risk, HIPAA identifiers, and differential privacy
   * - **Understandability and Usability**
     - FAIR compliance of your metadata, against the DCAT and DataCite schemas
   * - **Data Structure**
     - Constant features, collinearity, skewness, and kurtosis

.. list-table::
   :widths: 50 50
   :class: screenshots

   * - .. image:: _static/demo-stats.png
          :alt: Data Overview panel showing summary statistics and feature distributions
     - .. image:: _static/demo-metrics.png
          :alt: Metric results panel

----

Four Ways to Use AIDRIN
-----------------------

**Web Interface**
   An interactive, browser-based dashboard. Upload a dataset, select dimensions and metrics, and
   explore results with visualizations and downloadable reports — no coding required. Available
   hosted at `aidrin.org <https://aidrin.org>`_ or self-hosted locally.
   See :ref:`web_installation` and :ref:`web_usage`.

**Command Line Interface (CLI)**
   Run data readiness metrics directly from your terminal. Suitable for
   automated pipelines, CI workflows, and headless environments. Also includes an **agentic
   evaluation** component for domain-aware data readiness question answering and remediation
   grounded in scientific literature.
   See :ref:`cli_installation` and :ref:`cli_usage`.

**Python Library**
   Import AIDRIN into notebooks and scripts. A per-metric functional API for
   exploratory work, and a registry-driven headless API that shares its metric
   set with the command line for pipelines.
   See :ref:`python_api`.

**Claude Code (MCP)**
   Ask Claude Code to assess your dataset in plain language. AIDRIN ships an MCP server
   (``aidrin-mcp``) and a Claude Code skill that together let Claude run metrics, interpret
   results, and write a readiness report — with no commands to remember.
   See :ref:`aidrin_skill`.

----

.. toctree::
   :maxdepth: 2
   :caption: Metrics

   metric_names

.. toctree::
   :maxdepth: 2
   :caption: Web Interface

   web_installation
   web_usage

.. toctree::
   :maxdepth: 2
   :caption: CLI Interface

   cli_installation
   cli_usage

.. toctree::
   :maxdepth: 2
   :caption: Python Library

   python_api

.. toctree::
   :maxdepth: 2
   :caption: Integrations

   aidrin_skill
   appfl_integration

.. toctree::
   :maxdepth: 2
   :caption: Developers

   testing
   contributing

.. toctree::
   :maxdepth: 2
   :caption: More

   limitations
   publications
