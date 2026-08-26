.. _installation:
.. _web_installation:

Web Application Installation
=============================

This page covers installation and setup of the **AIDRIN web interface**. For the CLI and the agentic evaluation component, see the :ref:`cli` page.

There are **three ways** to run the web interface:

1. **Install from source**: best for development or the latest GitHub version.
2. **Run with Docker**: the bundled Compose stack, with no local Redis to set up.
3. **Hosted service**: no installation required.

To use AIDRIN in notebooks and scripts instead, see :ref:`python_api`; for the
terminal, see :ref:`cli_installation`.

.. note::

   ``pip install aidrin`` does **not** give you the web interface. Only the
   ``aidrin`` package is published; the ``web`` package is not part of the
   wheel, so ``flask --app 'web:create_app()'`` will fail with
   ``ModuleNotFoundError: No module named 'web'``. Install from source to run
   the web application.

----

Install from Source
-------------------

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
- Download Redis from `Microsoft's archive <https://github.com/microsoftarchive/redis/releases>`_.

Verify Redis is running:

.. code-block:: bash

   redis-cli ping

Expected output: ``PONG``

Install PDF Export Libraries
""""""""""""""""""""""""""""

The **Readiness Report** exports PDFs with `WeasyPrint <https://weasyprint.org>`_.
WeasyPrint is installed with AIDRIN, but it links against system libraries
(Pango, HarfBuzz and gdk-pixbuf) that ``pip`` and ``uv`` cannot install. Without
them the report itself still works; only PDF export fails, with
``WeasyPrint could not be loaded``.

**macOS (Homebrew)**:

.. code-block:: bash

   brew install pango gdk-pixbuf libffi

**Ubuntu/Debian**:

.. code-block:: bash

   sudo apt update
   sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
       libgdk-pixbuf-2.0-0 shared-mime-info fonts-dejavu-core

**Windows**:

- Use `Windows Subsystem for Linux (WSL) <https://learn.microsoft.com/en-us/windows/wsl/install>`_
  and follow the Linux instructions, or install the GTK runtime environment.

Verify the libraries are visible to Python:

.. code-block:: bash

   python -c "import weasyprint; print(weasyprint.__version__)"

A version number means PDF export will work. An ``OSError`` naming a missing
``lib...`` file means the system libraries above are not installed.

.. note::

   The Docker images install these packages already, so no extra setup is
   needed when running AIDRIN with ``docker compose``.

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

File-reference validation is disabled unless the server administrator explicitly
allows one or more filesystem roots. Set
``AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS`` to a JSON array of absolute, existing
directories before starting Flask. For example:

.. code-block:: bash

   export AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS='["/absolute/path/to/project-data"]'
   flask --app 'web:create_app()' run --debug

There is intentionally no fallback to the working directory or filesystem root;
the allowlist prevents web users from probing arbitrary server paths. The local
Docker Compose stack sets the value to ``["/app"]`` so the feature can be tested
against files copied into the development image. Production deployments should
use the narrowest directories containing the referenced data. See
:ref:`web_usage` for the metric workflow and optional scan-limit setting.

This fail-closed policy is specific to the web request boundary. The CLI,
headless Python API, and local stdio MCP server intentionally rely on the
filesystem permissions of the account running AIDRIN instead of this allowlist.

.. note::

   **Windows:** to run periodic tasks alongside a ``--pool=solo`` worker, start
   Beat in a separate terminal. This is optional for local development:

   .. code-block:: powershell

      $env:PYTHONPATH = "."
      celery -A worker.make_celery beat --loglevel=info

Once running, visit:
`http://127.0.0.1:5000 <http://127.0.0.1:5000>`_

.. note::

   The maximum upload size defaults to **1 GB**. To change it for a deployment,
   set the ``AIDRIN_MAX_UPLOAD_MB`` environment variable (in megabytes) before
   starting the Flask server, e.g.
   ``AIDRIN_MAX_UPLOAD_MB=2048 flask --app 'web:create_app()' run``.

.. note::

   **Frame cache.** To avoid re-parsing the uploaded file for every metric, the
   first read of a dataset is materialised to an on-disk Arrow/Feather artifact
   (``<source>.aidrin.feather``) next to the upload; later metric tasks reload it
   instead of re-parsing. Caching applies only to dtype-stable formats (CSV,
   Parquet, Excel); JSON/NPZ/HDF5 are always parsed directly. The sidecars roughly
   double an upload's on-disk footprint and are reaped together with stale uploads
   by the scheduled cleanup. The cache is **on by default**; disable it by setting
   ``AIDRIN_FRAME_CACHE=0``. On multi-worker deployments it is most effective when
   the upload folder is on a volume shared by all workers.

----

Run with Docker
---------------

The repository ships a Compose file that starts every service, so you do not
have to install Redis or run three terminals yourself.

.. warning::

   The Compose file defines no shared volume, so ``web``, ``worker`` and
   ``beat`` each get their own filesystem. Metrics that run inline will work,
   but any metric dispatched to Celery cannot see the file the web container
   received, and the scheduled cleanup prunes an empty directory. Treat this
   stack as a way to bring the services up, not as a drop-in replacement for
   the local setup above, until a shared upload volume is added.

.. code-block:: bash

   git clone https://github.com/idtlab/AIDRIN.git
   cd AIDRIN
   docker compose -f docker/local/docker-compose.yml up --build

This starts five services:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Service
     - Role
   * - ``web``
     - Gunicorn serving the app on `http://localhost:5000 <http://localhost:5000>`_
   * - ``worker``
     - Celery worker for background metric evaluation
   * - ``beat``
     - Celery beat, for scheduled cleanup tasks
   * - ``redis``
     - Broker and result backend
   * - ``jaeger``
     - Trace viewer on `http://localhost:16686 <http://localhost:16686>`_

The local image is built with the ``llm``, ``globus``, and ``telemetry`` extras
already installed, so those optional features are available without a rebuild.
The NERSC image ships ``llm`` and ``globus`` only.
Stop the stack with ``docker compose -f docker/local/docker-compose.yml down``.

.. note::

   ``docker/NERSC/`` holds a separate image for deployment to NERSC Spin. It runs
   the web app, worker, and beat together under supervisord, with Redis supplied
   externally. Because it runs Celery beat in-image, deploy it with **exactly one
   replica** or scheduled tasks will run more than once.


----

Hosted Service
--------------

For zero setup, use the hosted version at:
`https://aidrin.org <https://aidrin.org>`_

Advantages:

- No installation or dependencies
- Use it from any browser, on any platform
- Same features as the local version
- All processing is server-side

Simply upload datasets and run analyses directly from the interface.

----

OpenTelemetry Tracing
---------------------

Optional tracing for the person running the server. This is operator configuration,
not a user-facing feature; the other extras (``llm`` and ``globus``) are set up
and used from the web interface, and are documented in :ref:`web_usage`.

AIDRIN supports optional OpenTelemetry tracing for monitoring metric evaluation performance.

**Installation (from local source):**

.. code-block:: bash

   # From the project root:
   pip install -e ".[telemetry]"

   # Or with dev tools as well:
   pip install -e ".[telemetry,dev]"

When the telemetry packages are not installed (plain ``pip install -e .``), all tracing
is a no-op with zero overhead.

**Configuration** via environment variables:

- ``OTEL_EXPORTER_OTLP_ENDPOINT``: collector endpoint (e.g., ``http://localhost:4317``). If not set, traces go to console.
- ``OTEL_SERVICE_NAME``: service name (defaults to ``aidrin``).

**What gets traced:**

- Every HTTP request (automatic via Flask instrumentation)
- Each metric evaluation with attributes: ``metric.name``, ``metric.pillar``, ``metric.duration_ms``
- File metadata: ``file.name``, ``file.type``

**Quick test (console output):**

.. code-block:: bash

   pip install -e ".[telemetry]"
   flask --app 'web:create_app()' run --debug

Run a metric and observe trace spans printed to the terminal.

**Test with Jaeger:**

.. code-block:: bash

   # Start Jaeger (Docker)
   docker run -d --name jaeger \
     -p 16686:16686 -p 4317:4317 \
     jaegertracing/all-in-one:1.62.0

   # Start AIDRIN with OTLP exporter
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
   flask --app 'web:create_app()' run --debug

   # Open Jaeger UI at http://localhost:16686, select service "aidrin"

**Verify installation:**

``get_tracer()`` returns a real tracer only after ``init_telemetry(app)`` has
run, so check from inside the application rather than a bare interpreter: start
the server and confirm spans appear, either on the console or in Jaeger.


----

.. note::

   Both the **local** and **web** versions share the same core codebase.
   The web version is pre-configured and ready to use, while the local version offers flexibility for customization.
