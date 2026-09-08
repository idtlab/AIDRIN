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
- Each metric evaluation in the web app, with attributes ``metric.name``,
  ``metric.pillar``, ``metric.duration_ms`` and file metadata ``file.name``, ``file.type``
- Each metric evaluation on the CLI and the MCP server, via
  ``aidrin.headless.api.run_metric``. These spans use ``metric.category``
  (the ``METRIC_REGISTRY`` vocabulary: ``data-quality``, ``data-structure``,
  ``impact-of-data-on-AI``, ``fairness-and-bias``, ``data-governance``) rather than
  ``metric.pillar``, which the web routes use with a different vocabulary.

Spans record the *type* of any exception, never its message: metric errors routinely
interpolate column names and cell values, and OTLP exports leave the host unredacted.

The tracer lives in :mod:`aidrin.telemetry` so the CLI and MCP server can use it without
importing Flask; ``web/telemetry.py`` re-exports it and adds the Flask instrumentation.

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


Assessment tracking (MLflow)
----------------------------

Tracing answers "what ran and how long did it take". Assessment tracking answers "what was
this dataset's readiness, and how has it changed" — each assessment becomes an MLflow run
carrying its readiness scores.

This covers the **CLI and the MCP/skill surfaces**. The web interface is not tracked; its
metric routes are a separate code path.

**Installation:**

.. code-block:: bash

   pip install -e ".[mlflow]"

``mlflow-skinny`` is used rather than ``mlflow``: the full package pulls in Flask, alembic,
docker, graphene, gunicorn and sqlalchemy, which a client logging to a remote server does
not need. To run your own local tracking server, install full ``mlflow`` separately.

The pin is ``>=3.15,<4``. AIDRIN identifies a dataset by the digest
``mlflow.data.from_pandas`` computes, so that an assessment and a training run over the
same file resolve to one dataset in MLflow. A major release that changed that algorithm
would break the link silently — runs would still log, they would just stop matching.

**Configuration:**

- ``MLFLOW_TRACKING_URI``: the tracking server (required).
- ``AIDRIN_MLFLOW_ENABLED``: set to ``1`` to turn tracking on (required — the URI alone is
  not enough, so a URI inherited from the environment does not silently enable it).
- ``AIDRIN_MLFLOW_EXPERIMENT``: experiment name (defaults to ``aidrin``).
- ``AIDRIN_MLFLOW_LOG_DATA_DETAILS``: dataset metadata — file names rather than hashes,
  the column arguments each metric was given, and each metric's full output archived as a
  ``result.json`` artifact. **On by default**, because without it a score cannot be acted
  on: you can see that k-anonymity is 1 but not which quasi-identifiers produced it. Set it
  to ``0`` for a shared or untrusted tracking server. This governs metadata, not cell
  values — archived results are redacted either way.
- ``AIDRIN_MLFLOW_LOG_RAW_RESULTS``: set to ``1`` to archive results *verbatim*, with no
  redaction — including every value the PII and PHI scans matched. Requires
  ``AIDRIN_MLFLOW_LOG_DATA_DETAILS`` as well; it modifies archiving rather than enabling
  it. Private tracking servers only. AIDRIN logs a warning when it is on.

If the tracking server cannot be reached, AIDRIN warns once and continues untracked. It
never fails a metric because telemetry failed, and never leaves a run open: a metric run is
terminated even if writing to it fails. Writes are batched into one call per run, and the
HTTP timeout and retry count are lowered from MLflow's defaults (120s x 7) so a wedged
server cannot stall a metric evaluation.

**What gets recorded:**

One MLflow run per metric, nested under one parent run per assessment that carries the
aggregated readiness scores. **Compare assessments by selecting the parent runs** — each is
one row with every score as a column. The per-metric child runs exist for drill-down:
runtime, and the optional full-output artifact.

Metric keys are namespaced by readiness dimension — ``aidrin.quality.completeness``,
``aidrin.governance.k_anonymity``, ``aidrin.fairness.class_imbalance`` — so a wide
runs table can be filtered to one dimension. The dimension segment always matches the
metric's ``METRIC_REGISTRY`` category, and a test enforces that; renaming a key later
orphans its history under the old name.

The parent run also records the dataset via ``log_inputs``, which populates MLflow's
Dataset column and lets runs be grouped by the dataset they assessed. The dataset is
identified by a stable hash of its path unless ``AIDRIN_MLFLOW_LOG_DATA_DETAILS`` is set.

**What does not get recorded.** AIDRIN's purpose is finding PII and PHI, so its results
contain it: matched SSNs and email addresses, duplicate-group cell values, flagged outlier
values, resolved file paths, and sensitive-attribute values used as dictionary keys.
Tracking is therefore an *allowlist* — a metric contributes only the numbers it explicitly
declares in ``aidrin/telemetry/redaction.py``, and a metric with no declaration contributes
only its runtime. Dataset paths are hashed. Exception messages are never recorded.

Adding a metric does not require touching redaction: an undeclared metric is silent by
default. Declare a projection only after checking that the values it exposes are counts or
scores, never cell contents.

The ``result.json`` archive uses a different mechanism, because per-column detail cannot be
expressed as an allowlist without restating every metric's schema. Redaction there is
*structural*: numbers and the shape of the result are kept, and anything that can carry a
cell value is removed — string values, payloads keyed by sensitive-attribute values, and
keys known to hold raw matches. That is weaker than the projection allowlist, which is why
archiving is opt-in and verbatim archiving needs a second flag.

**Usage:**

.. code-block:: bash

   export MLFLOW_TRACKING_URI=http://localhost:5000
   export AIDRIN_MLFLOW_ENABLED=1

   aidrin data-quality data.csv     # opens and closes its own assessment
   aidrin batch config.yaml         # one parent run, one child run per metric

Both surfaces can discover whether tracking is on, and both can attach a finished report.

From the MCP server or the skill, ``list_metrics()`` reports ``mlflow_enabled``; when it is
true, call ``start_assessment(file_path)``, pass the returned ``session_id`` to each metric
call, and finish with ``end_assessment(session_id, report_path=...)``.

From the CLI, ``aidrin list --capabilities`` returns the same information, and
``aidrin batch <config> --report <path>`` attaches a report to the assessment the batch
opened. Both degrade quietly when tracking is off: the capability reports ``false``, and
``--report`` is ignored rather than failing. Plain ``aidrin list`` is unchanged, so
existing scripts that parse it are unaffected.

**Relationship to OpenTelemetry.** The two are independent and both can be on. They answer
different questions: tracing is "what ran and how long did it take", assessment tracking is
"what was this dataset's readiness". Send spans to a collector (Jaeger, Grafana Tempo, or
any OTLP endpoint) via ``OTEL_EXPORTER_OTLP_ENDPOINT``, and let MLflow hold the readiness
runs.

MLflow 3.6+ can ingest OTLP traces at ``/v1/traces``, so both signals could share one UI.
**AIDRIN deliberately does not do this.** It would need the HTTP exporter instead of the
gRPC one, a SQL backend store, and it makes the MLflow UI treat the experiment as a GenAI
workload — which moves the runs out of the classic view where dataset lineage, parameters,
artifacts and run comparison are shown. If you want it anyway, configure your own exporter;
nothing in AIDRIN prevents it. Note that setting ``OTEL_EXPORTER_OTLP_ENDPOINT`` also stops
MLflow exporting its own traces to the MLflow UI.


----

.. note::

   Both the **local** and **web** versions share the same core codebase.
   The web version is pre-configured and ready to use, while the local version offers flexibility for customization.
