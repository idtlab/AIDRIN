Tracking assessments with MLflow
================================

AIDRIN records each dataset assessment to MLflow, so that you can compare a
dataset's readiness across versions, compare datasets against each other, and
connect a readiness assessment to the model runs trained on that data.

Tracking is optional and off by default. Without it, AIDRIN behaves exactly as
it does today.

Tracking covers the command line, the Python library, and the MCP server. The web
interface is not tracked, and neither are metrics executed remotely through
Globus Compute, which run on the endpoint rather than on your machine.

.. contents::
   :local:
   :depth: 2


Quick start
-----------

Install the extra, which pulls in ``mlflow-skinny`` (the client, without the
server components):

.. code-block:: bash

   pip install -e ".[mlflow]"

AIDRIN requires MLflow 3.15 or later. The client and the tracking server should
be on the same major version, because AIDRIN identifies a dataset using the
digest that MLflow computes, and a mismatch would break dataset lineage without
producing an error.

Start a tracking server. Any MLflow server works; to run one locally:

.. code-block:: bash

   pip install mlflow      # the full package, required for the server
   mlflow server \
     --backend-store-uri "sqlite:///$PWD/mlflow.db" \
     --artifacts-destination "$PWD/mlruns" \
     --host 127.0.0.1 --port 5000

Use a database backend rather than a plain directory. Recent MLflow releases
place the filesystem store in maintenance mode and refuse it unless
``MLFLOW_ALLOW_FILE_STORE`` is set.

Point AIDRIN at the server. Both variables are required, so that a tracking URI
inherited from your environment never starts recording on its own:

.. code-block:: bash

   export MLFLOW_TRACKING_URI=http://127.0.0.1:5000
   export AIDRIN_MLFLOW_ENABLED=1

Run an assessment:

.. code-block:: bash

   aidrin data-quality data.csv
   aidrin batch config.yaml --report report.md

Open http://127.0.0.1:5000 and the assessment is there.


What gets recorded
------------------

Each assessment produces one **assessment run**, with one **metric run** nested
beneath it for every metric.

To compare assessments, select the parent runs. Each is a single row carrying
every score as a column, which is what makes two datasets, or two versions of
one dataset, comparable side by side. Filter the runs table to those rows with:

.. code-block:: text

   tags.`aidrin.run_type` = 'assessment'

The nested metric runs are for drill-down. Each records its runtime, the
arguments that produced the score, and the full result as an artifact.

**Metrics** are namespaced by readiness dimension, so that a wide table can be
filtered to a single concern (e.g., governance):

.. code-block:: text

   aidrin.quality.completeness              aidrin.governance.k_anonymity
   aidrin.quality.duplicity                 aidrin.governance.hipaa_total_flags
   aidrin.structure.constant_feature_count  aidrin.fairness.class_imbalance
   aidrin.impact.max_correlation            aidrin.failed_metrics

Every metric reports at least one comparable value, so no run shows a runtime
alone. A metric that returns several scalars contributes several keys. For
instance, ``constant_feature_count`` records both the number of constant
features and the total feature count.

Runtime is namespaced the same way, as ``aidrin.<dimension>.runtime_seconds``,
so that the cost of the governance metrics can be read separately from that of
the quality metrics. A custom metric belongs to no dimension and records the
plain ``aidrin.runtime_seconds`` instead.

**Per-column values** are recorded on the metric run, alongside that metric's
overall score:

.. code-block:: text

   aidrin.column.completeness.age                  aidrin.quality.completeness
   aidrin.column.completeness.income               aidrin.structure.max_abs_skewness
   aidrin.column.skewness.cholesterol              aidrin.impact.max_correlation
   aidrin.column.correlations.age_vs_cholesterol

Column names are normalized to the character set MLflow accepts, with separators
written as underscores. Two columns whose names normalize identically (for
instance ``Income (USD)`` and ``Income [USD]``) are kept apart by a short digest,
because MLflow does not reject a repeated metric key: it appends another point to
the same series, which would silently merge two columns into one chart.

Per-column keys stay on the metric run and are never rolled up to the assessment
run. The assessment run is the only place where keys have to line up across runs,
and two datasets with different schemas would turn its comparison view into a
sparse grid. What it carries instead is the aggregate over those columns: the
largest absolute skewness, the strongest correlation between any pair, the worst
batch's null count, the widest disparity between groups.

Per-column recording follows ``AIDRIN_MLFLOW_LOG_DATA_DETAILS``, since the keys
carry column names, exactly as the column arguments recorded as parameters do.

**Parameters** record what produced a score, together with ``aidrin_version``. A
k-anonymity value means nothing without the quasi-identifiers it was computed
over, so those arguments travel with it.

**Artifacts**: each metric run carries ``result.json`` with its full result, and
the assessment run carries the report you pass to ``--report`` (CLI) or
``end_assessment`` (MCP).

**Provenance**: every run records the AIDRIN version, the source, the user, and
the git commit when AIDRIN runs from a checkout.

**Tags** identify each run and make the table filterable:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Tag
     - Meaning
   * - ``aidrin.run_type``
     - ``assessment`` or ``metric``. MLflow search cannot express "this tag is
       absent", so both kinds carry it and either can be selected.
   * - ``aidrin.interface``
     - Which AIDRIN interface produced the run: ``cli`` or ``mcp``.
   * - ``aidrin.session_id``
     - Groups an assessment with its metric runs, alongside the parent link.
   * - ``aidrin.metric``
     - On a metric run, which metric it is.
   * - ``aidrin.status``
     - On a metric run, ``ok`` or ``error``. On an assessment, ``ok`` when every
       metric succeeded, ``partial`` when some did, and ``error`` when none did.
   * - ``aidrin.skipped_metrics``
     - Keys that resolved to a non-finite value and were therefore not recorded.

Runs are described in the interface as well: an assessment reads
``AIDRIN Assessment``, and a metric run reads ``Pillar: Metric Name`` (for
instance ``Data Governance: k-Anonymity``), so a run says which readiness
dimension it belongs to without the reader having to decode the key scheme.

An assessment also records ``aidrin.metrics_run`` and ``aidrin.failed_metrics``,
so the proportion that succeeded is visible without opening the nested runs. To
find assessments needing attention:

.. code-block:: text

   tags.`aidrin.run_type` = 'assessment' and tags.`aidrin.status` != 'ok'

**Dataset lineage**: AIDRIN records the dataset using the same digest that
``mlflow.data.from_pandas`` computes, so an assessment and a training run over
the same file resolve to one dataset in MLflow. Filter both with:

.. code-block:: text

   datasets.name = 'my_data.csv'

That link is what connects a readiness score to the model trained on the data it
describes.


From the skill or an MCP client
-------------------------------

``list_metrics()`` reports ``mlflow_enabled``. When it is true:

.. code-block:: text

   start_assessment(file_path)        -> session_id
   run_aidrin_metric(..., session_id=session_id)
   end_assessment(session_id, report_path="report.md")

From the command line, ``aidrin list --capabilities`` returns the same
information, and ``aidrin batch <config> --report <path>`` attaches a report to
the assessment that the batch opened. Both ``aidrin batch`` and ``aidrin
data-quality`` manage their own assessment, so there is no session to track by
hand.

The MCP server runs as its own process, so it reads the tracking configuration
from its own environment rather than from the shell you launch your client in.
Set the variables in the server definition:

.. code-block:: json

   {
     "mcpServers": {
       "aidrin": {
         "type": "stdio",
         "command": "aidrin-mcp",
         "args": [],
         "env": {
           "MLFLOW_TRACKING_URI": "http://127.0.0.1:5000",
           "AIDRIN_MLFLOW_ENABLED": "1"
         }
       }
     }
   }


What AIDRIN does not send
-------------------------

AIDRIN exists to find personally identifiable information (PII) and protected
health information (PHI), so its results contain both. None of it reaches the
tracking server.

Metric values come from an allowlist: a metric contributes only the numbers it
explicitly declares, and a metric with no declaration contributes only its
runtime. Adding a new metric therefore cannot introduce a leak by default. The
``result.json`` archive is redacted structurally, keeping numbers and the shape
of the result while removing string values, payloads keyed by
sensitive-attribute values, and keys known to hold raw matches. Exception
messages are never recorded anywhere, only the exception type, because metric
errors routinely quote column names and offending values.

For instance, a HIPAA scan that matched 1,000 postal codes records
``hipaa_flagged_columns=1`` and ``hipaa_total_flags=1000``, together with an
artifact naming the types of identifier found. Not one matched value leaves your
machine.

Dataset details, which cover real file names, the column arguments each metric
was given, and the ``result.json`` archive, are on by default, because a score
you cannot attribute to specific columns is difficult to act on. On a shared or
untrusted tracking server, turn them off:

.. code-block:: bash

   export AIDRIN_MLFLOW_LOG_DATA_DETAILS=0

That setting hashes dataset paths, withholds column names, and stops archiving
results. It governs metadata rather than cell values, which are redacted either
way.


Configuration
-------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Variable
     - Meaning
   * - ``MLFLOW_TRACKING_URI``
     - Tracking server. Required.
   * - ``AIDRIN_MLFLOW_ENABLED``
     - Set to ``1`` to record. Required.
   * - ``AIDRIN_MLFLOW_EXPERIMENT``
     - Experiment name. Defaults to ``aidrin``, and is created if absent.
   * - ``AIDRIN_MLFLOW_LOG_DATA_DETAILS``
     - Dataset metadata and result archives. On by default; set ``0`` to opt out.
   * - ``MLFLOW_TRACKING_USERNAME``
     - Your identity on the tracking server, used for the ``mlflow.user`` tag.
       Set this on a shared server, where the local account name is misleading.
   * - ``AIDRIN_MLFLOW_LOG_RAW_RESULTS``
     - Archive results verbatim, without redaction, including every PII and PHI
       match. Requires ``AIDRIN_MLFLOW_LOG_DATA_DETAILS``. Private servers only.
   * - ``AIDRIN_MLFLOW_AUTH_HEADER`` / ``AIDRIN_MLFLOW_AUTH_KEY``
     - Send your credential in a named header, for a tracking server behind an
       API gateway. See :doc:`genesis_mission`.

Tracking failures never break an assessment. An unreachable tracking server
produces one warning and the metrics run untracked, so a metric never fails
because telemetry did.

To keep that promise, AIDRIN lowers three MLflow defaults when tracking is
enabled, and leaves any value you have already set alone:

.. list-table::
   :header-rows: 1
   :widths: 46 54

   * - Variable
     - Why AIDRIN changes it
   * - ``MLFLOW_HTTP_REQUEST_TIMEOUT``
     - Lowered to 5 seconds. MLflow defaults to 120.
   * - ``MLFLOW_HTTP_REQUEST_MAX_RETRIES``
     - Lowered to 1. MLflow defaults to 7, so an unresponsive server would
       otherwise stall a metric evaluation for several minutes before failing.
   * - ``MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT``
     - Enabled. MLflow prints a run URL to standard output on each run, which
       corrupts the JSON-RPC stream that the MCP server communicates over.

Raise the timeout and retry count yourself if your tracking server is slow to
respond and you would rather wait than lose a record.


Troubleshooting
---------------

**Nothing appears in MLflow.** Both ``MLFLOW_TRACKING_URI`` and
``AIDRIN_MLFLOW_ENABLED=1`` must be set. Confirm with ``aidrin list
--capabilities``, which reports ``mlflow_enabled``.

**The server returns 401.** A tracking server behind an API gateway may expect
your credential in a named header rather than in an ``Authorization`` header.
Set ``AIDRIN_MLFLOW_AUTH_HEADER`` and ``AIDRIN_MLFLOW_AUTH_KEY``; see
:doc:`genesis_mission` for a worked configuration.

**Runs appear, but without artifacts.** Artifact archiving follows
``AIDRIN_MLFLOW_LOG_DATA_DETAILS``, so this is expected when that is ``0``.
Otherwise, check whether the server proxies artifacts (an artifact location of
``mlflow-artifacts:/``) or expects the client to write to cloud storage
directly, in which case the client needs its own credentials.

**A metric shows a runtime but no score.** There are three causes, and the tags
tell them apart. The metric failed, in which case it is tagged:

.. code-block:: text

   tags.`aidrin.status` = 'error'

Or every value it computed was non-finite, which happens when a column is
constant and skewness, kurtosis or correlation are undefined for it. MLflow
renders a stored NaN as ``0``, so those values are skipped rather than recorded
as zero, and the keys that were dropped are listed in ``aidrin.skipped_metrics``.

Or the metric genuinely produced no numeric result, for instance a privacy
metric whose inputs were rejected. The assessment run carries
``aidrin.failed_metrics`` and ``aidrin.metrics_run`` for the overall picture.

**Runs show a local account name on a shared server.** Set
``MLFLOW_TRACKING_USERNAME`` to your identity on that server.
