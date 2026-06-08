.. _installation:

Installation
============

AIDRIN can be used in **three ways**:

1. **Run locally from source** — best for development or using the latest GitHub version.
2. **Install as a Python package via PyPI** — simplest for using AIDRIN in scripts or notebooks.
3. **Use the hosted web application** — no installation required.

Choose the option that best fits your workflow.

----

Option 1: Local Installation from Source
----------------------------------------

Works on **macOS**, **Linux**, and **Windows** (via WSL or Anaconda).

Prerequisites
~~~~~~~~~~~~~

Before installing AIDRIN locally, ensure you have:

- `Python 3.10 <https://www.python.org/downloads/release/python-3100/>`_
- `Conda <https://docs.conda.io/en/latest/miniconda.html>`_ (Anaconda or Miniconda)
- `Git <https://git-scm.com/downloads>`_ for cloning the repository

Step 1: Clone the Repository
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   git clone https://github.com/idtlab/AIDRIN.git
   cd AIDRIN

Step 2: Set Up the Conda Environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   conda create -n aidrin-env python=3.10 -y
   conda activate aidrin-env
   python -m pip install -e .

This installs AIDRIN and its dependencies in editable mode.

**Optional extras:**

.. code-block:: bash

   # AI-generated explanations of metric results (OpenAI-compatible APIs)
   pip install -e ".[llm]"

   # Remote metric execution via Globus Compute
   pip install -e ".[globus]"

   # OpenTelemetry tracing
   pip install -e ".[telemetry]"

   # All optional features
   pip install -e ".[llm,globus,telemetry]"

Step 3: Install Required Services
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

AIDRIN uses **Redis** for background task management and **Celery** for asynchronous execution.

Install Redis Locally
"""""""""""""""""""""

**macOS (Homebrew)**:

.. code-block:: bash

   brew install redis

**Ubuntu/Debian**:

.. code-block:: bash

   sudo apt update
   sudo apt install redis-server

**Windows**:

- Use `Windows Subsystem for Linux (WSL) <https://learn.microsoft.com/en-us/windows/wsl/install>`_ and follow Linux instructions, or
- Download Redis from `Microsoft’s archive <https://github.com/microsoftarchive/redis/releases>`_.

Verify Redis is running:

.. code-block:: bash

   redis-cli ping

Expected output: ``PONG``

Step 4: Start the Application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Open **three terminal windows/tabs**:

Terminal 1 – Redis Server
"""""""""""""""""""""""""

.. code-block:: bash

   redis-server --port 6379

Terminal 2 – Celery Worker
""""""""""""""""""""""""""

**macOS / Linux:**

.. code-block:: bash

   conda activate aidrin-env
   PYTHONPATH=. celery -A worker.make_celery worker --beat --loglevel=info

**Windows:**

If you see errors such as:

- ``-B option does not work on Windows. Please run celery beat as a separate service.``
- ``Can't pickle local object 'celery_init_app.<locals>.FlaskTask'``

Use the ``solo`` pool instead (no ``--beat`` required for local development):

.. code-block:: powershell

   conda activate aidrin-env
   $env:PYTHONPATH = "."
   celery -A worker.make_celery worker --loglevel=info --pool=solo

If you use a venv rather than Conda, activate it first and set ``PYTHONPATH`` the
same way before running the ``celery`` command.

Terminal 3 – Flask Server
"""""""""""""""""""""""""

.. code-block:: bash

   conda activate aidrin-env
   flask --app 'web:create_app()' run --debug

.. note::

   **Windows:** If you see ``-B option does not work on Windows`` or
   ``Can't pickle local object 'celery_init_app.<locals>.FlaskTask'``, drop
   ``--beat`` from the worker command and use ``--pool=solo`` instead:

   .. code-block:: powershell

      PYTHONPATH=. celery -A worker.make_celery worker --pool=solo --loglevel=info

   To run periodic tasks, start Beat in a **separate** terminal (optional for
   local development):

   .. code-block:: powershell

      PYTHONPATH=. celery -A worker.make_celery beat --loglevel=info

Once running, visit:
`http://127.0.0.1:5000 <http://127.0.0.1:5000>`_

.. note::

   The maximum upload size defaults to **1 GB**. To change it for a deployment,
   set the ``AIDRIN_MAX_UPLOAD_MB`` environment variable (in megabytes) before
   starting the Flask server, e.g.
   ``AIDRIN_MAX_UPLOAD_MB=2048 flask --app 'web:create_app()' run``.

----

Option 2: Install from PyPI
---------------------------

For quick use in Python scripts or Jupyter notebooks:

.. code-block:: bash

   pip install -i https://test.pypi.org/simple/ aidrin==<version>

Replace ``<version>`` with the latest from
`PyPI versions <https://test.pypi.org/project/aidrin/#history>`_.

Verify installation:

.. code-block:: python

   import aidrin
   print(aidrin.__version__)

See :ref:`usage` for examples.

----

Option 3: Use the Hosted Web Application
----------------------------------------

For zero setup, use the hosted version at:
`https://aidrin.io <https://aidrin.io>`_

Advantages:

- No installation or dependencies
- Runs entirely in the browser
- Same features as the local version
- All processing is server-side

Simply upload datasets and run analyses directly from the interface.

----

.. note::

   Both the **local** and **web** versions share the same core codebase.
   The web version is pre-configured and ready to use, while the local version offers flexibility for customization.
