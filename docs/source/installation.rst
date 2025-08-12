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

.. code-block:: bash

   conda activate aidrin-env
   PYTHONPATH=. celery -A aidrin.make_celery worker --loglevel=info

Terminal 3 – Flask Server
"""""""""""""""""""""""""

.. code-block:: bash

   conda activate aidrin-env
   flask --app aidrin run --debug

Once running, visit:
`http://127.0.0.1:5000 <http://127.0.0.1:5000>`_

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
