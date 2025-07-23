.. _installation:

Installation
============

This section guides you through installing **AIDRIN** locally. AIDRIN works on **macOS**, **Linux**, and **Windows** (via WSL or Anaconda).

Prerequisites
-------------

Before installing AIDRIN, ensure you have the following:

- `Python 3.10 <https://www.python.org/downloads/release/python-3100/>`_
- `Conda <https://docs.conda.io/en/latest/miniconda.html>`_ (Anaconda or Miniconda)
- `Git <https://git-scm.com/downloads>`_ for cloning the repository

Step 1: Clone the Repository
----------------------------

Clone the AIDRIN repository from GitHub:

.. code-block:: bash

   git clone https://github.com/idtlab/AIDRIN.git
   cd AIDRIN

Step 2: Set Up the Conda Environment
------------------------------------

Create and activate a Conda environment for AIDRIN:

.. code-block:: bash

   conda create -n aidrin-env python=3.10 -y
   conda activate aidrin-env
   python -m pip install -e .

This installs AIDRIN and its dependencies in editable mode.

Step 3: Install Required Services
---------------------------------

AIDRIN uses **Redis** as a message broker for background tasks and **Celery** for asynchronous task execution.

Install Redis Locally
~~~~~~~~~~~~~~~~~~~~~

No Docker is required. Follow the instructions for your operating system.

**On macOS (using Homebrew)**:

.. code-block:: bash

   brew install redis

**On Ubuntu/Debian**:

.. code-block:: bash

   sudo apt update
   sudo apt install redis-server

**On Windows**:

- Use `Windows Subsystem for Linux (WSL) <https://learn.microsoft.com/en-us/windows/wsl/install>`_ and follow the Linux instructions above, or
- Download and install Redis from `Microsoft’s archive <https://github.com/microsoftarchive/redis/releases>`_.

Ensure the Redis server is running on the default port (6379). Verify with:

.. code-block:: bash

   redis-cli ping

If Redis is running, this should return ``PONG``.

Step 4: Start the Application
-----------------------------

You need **three terminal windows/tabs** to run AIDRIN locally.

Terminal 1: Start Redis Server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ensure Redis is running:

.. code-block:: bash

   redis-server --port 6379

Terminal 2: Start Celery Worker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

From the AIDRIN directory, activate the environment and start the Celery worker:

.. code-block:: bash

   conda activate aidrin-env
   PYTHONPATH=. celery -A aidrin.make_celery worker --loglevel=info

Wait until you see ``ready`` or ``waiting for tasks`` in the Celery logs (this may take 30–40 seconds).

Terminal 3: Run Flask Application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

From the AIDRIN directory, activate the environment and start the Flask development server:

.. code-block:: bash

   conda activate aidrin-env
   flask --app aidrin run --debug

Once the server is running, open your browser and navigate to:

`http://127.0.0.1:5000 <http://127.0.0.1:5000>`_