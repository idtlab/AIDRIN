.. _testing:

Testing
=======

AIDRIN includes a suite of unit tests that run without a web interface, Celery broker, or Redis instance. They cover the core metrics library, file readers, and data quality functions.

----

Running the Unit Tests
-----------------------

Prerequisites
~~~~~~~~~~~~~

Activate the conda environment and ensure ``pytest`` and ``pytest-cov`` are installed:

.. code-block:: bash

   conda activate aidrin-env
   pip install pytest pytest-cov

Running All Unit Tests
~~~~~~~~~~~~~~~~~~~~~~

From the project root:

.. code-block:: bash

   PYTHONPATH=. pytest tests/unit/ -v

``PYTHONPATH=.`` is required so Python can locate the ``aidrin`` and ``web`` packages.

Running a Specific Test File
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   PYTHONPATH=. pytest tests/unit/test_data_quality.py -v

Checking Code Coverage
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   PYTHONPATH=. pytest tests/unit/ --cov=aidrin --cov-report=term-missing

----

Test Structure
--------------

Tests live in ``tests/unit/`` and are grouped by functional area:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - File
     - What is tested
   * - ``test_data_quality.py``
     - Completeness, duplicity, outliers
   * - ``test_fairness.py``
     - Representation rate, statistical rate, class imbalance
   * - ``test_privacy.py``
     - Single/multiple-attribute MM risk scores, k-anonymity, l-diversity, t-closeness, entropy risk
   * - ``test_hipaa.py``
     - HIPAA identifier detection (SSN, email, phone, IP, URL, medical IDs)
   * - ``test_file_readers.py``
     - JSON and NPZ file readers
   * - ``test_hdf5_reader.py``
     - HDF5 file reader
   * - ``test_dtype_guards.py``
     - dtype handling across narrow numeric types and pandas StringDtype

----

Integration Tests
-----------------

Integration tests (requiring a running Flask app) live in ``tests/integration/``.
See :ref:`installation` for instructions on starting the full application stack before running them:

.. code-block:: bash

   PYTHONPATH=. pytest tests/integration/ -v
