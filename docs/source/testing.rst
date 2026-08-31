.. _testing:

Testing
=======

AIDRIN's tests run entirely offline. Neither suite needs a Celery broker, a
Redis instance, or a running server: the unit tests exercise the library
directly, and the integration tests build their own Flask app and run Celery
tasks eagerly.

----

Running the Tests
-----------------

Prerequisites
~~~~~~~~~~~~~

Activate the environment and install the development extra, which pulls in
``pytest``, ``pytest-flask``, ``pytest-cov``, and ``flake8``:

.. code-block:: bash

   conda activate aidrin-env
   pip install -e ".[dev]"

Running the Suites
~~~~~~~~~~~~~~~~~~

From the project root:

.. code-block:: bash

   PYTHONPATH=. pytest tests/unit/ -v
   PYTHONPATH=. pytest tests/integration/ -v

``PYTHONPATH=.`` lets Python locate the ``aidrin``, ``web``, and ``worker``
packages. It is not needed when you run from the repository root with the
package installed in editable mode, but it does no harm.

A plain ``.[dev]`` install skips a handful of tests whose optional dependencies
are absent, notably the agentic and HDF5 sample suites. Install the extras you
want to exercise.

Running a Specific Test File
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   PYTHONPATH=. pytest tests/unit/test_data_quality.py -v

Checking Code Coverage
~~~~~~~~~~~~~~~~~~~~~~

Cover all three packages. CI runs this over both suites, appending the second:

.. code-block:: bash

   PYTHONPATH=. pytest tests/unit/ \
     --cov=aidrin --cov=web --cov=worker --cov-report=term-missing
   PYTHONPATH=. pytest tests/integration/ \
     --cov=aidrin --cov=web --cov=worker --cov-append --cov-report=term-missing

----

Test Structure
--------------

Unit tests live in ``tests/unit/`` and integration tests in
``tests/integration/``.

Metrics
~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 42 58

   * - File
     - What is tested
   * - ``test_data_quality.py``
     - Completeness, duplicity, outliers
   * - ``test_completeness_extras.py``
     - Row-level completeness, feature coverage ratio, temporal completeness, null-count trend
   * - ``test_duplicity_by_features.py``
     - Duplicates compared over selected features only
   * - ``test_custom_outliers.py``
     - Custom criteria outlier rules
   * - ``test_structure_metrics.py``
     - Data structure metrics: skewness, kurtosis, max pairwise correlation
   * - ``test_constant_feature_count.py``
     - Constant feature detection
   * - ``test_fairness.py``
     - Representation rate, statistical rate, class imbalance
   * - ``test_compare_representation_rate.py``
     - Representation rate comparison against a reference distribution
   * - ``test_privacy.py``
     - Single/multiple-attribute MM risk scores, k-anonymity, l-diversity, t-closeness, entropy risk
   * - ``test_hipaa.py``
     - HIPAA identifier detection (SSN, email, phone, IP, URL, medical IDs)
   * - ``test_add_noise.py``
     - Differential privacy noise statistics

File Handling
~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 42 58

   * - File
     - What is tested
   * - ``test_file_readers.py``
     - JSON and NPZ readers
   * - ``test_hdf5_reader.py``
     - HDF5 reader, including fill-value sentinels
   * - ``test_excel_reader.py``
     - Excel reader, including multi-row and merged-cell headers
   * - ``test_parquet_reader.py``
     - Parquet reader
   * - ``test_file_parser_cache.py``
     - The parse-once Arrow/Feather frame cache
   * - ``test_dtype_guards.py``
     - dtype handling across narrow numeric types and pandas StringDtype
   * - ``test_hashable_utils.py``
     - Normalisation of unhashable values

Interfaces
~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 42 58

   * - File
     - What is tested
   * - ``test_cli.py``
     - The ``aidrin`` command line interface
   * - ``test_agentic.py``
     - The ``aidrin agentic`` subcommand
   * - ``test_mcp_server.py``
     - MCP server rule-file interfaces
   * - ``test_public_api.py``
     - The public API exported from ``aidrin/__init__.py``
   * - ``test_docs_metric_names.py``
     - That the metric mapping table in the docs still matches the registry

Web Application and Security
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 42 58

   * - File
     - What is tested
   * - ``test_path_confinement.py``
     - Upload-folder path-traversal barrier
   * - ``test_inspector_js_security.py``
     - Inspector JavaScript contracts: output escaping and the custom-outlier UI
   * - ``test_upload_cleanup.py``
     - The scheduled upload-folder reaper in ``worker.tasks``

The integration suite in ``tests/integration/`` covers the Flask routes end to
end: page rendering, uploads, the inspector, metric endpoints, custom metrics,
admin pages, Globus, LLM explanations, and telemetry.
