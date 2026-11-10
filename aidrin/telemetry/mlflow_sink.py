"""Record AIDRIN assessments as MLflow runs.

Off unless both ``MLFLOW_TRACKING_URI`` and ``AIDRIN_MLFLOW_ENABLED`` are set and
``mlflow-skinny`` is installed; the import is lazy, so a disabled installation
pays nothing.

**Run model.** One run per metric, created and closed inside the call, plus one
parent run per assessment.  The parent is created by :func:`start_session`, is
terminated immediately, and receives the aggregated headline scores in
:func:`end_session` — MLflow permits ``log_metric`` on a terminated run.  Nothing
is left open across a call boundary, so there is no reaper, no staleness timeout
and no ``atexit`` handler to miss.

The parent is not bookkeeping: with one headline score per child run, the runs
table would compare rows that each have a single populated column.  The parent
row is the comparable unit.

**Client only.** ``mlflow._active_run_stack`` became thread-local in 2.18 and the
MCP server dispatches sync tool functions on worker threads, so a fluent-API call
would write to a stray run rather than the intended one.  Everything here goes
through ``MlflowClient`` with an explicit ``run_id``.

**Never raises.** Every AIDRIN interface funnels through ``run_metric``; an
exception escaping this module would destroy a computed result.
"""

import collections
import getpass
import hashlib
import time
import json
import logging
import os
import sys
import tempfile
import uuid

from aidrin.telemetry.redaction import (
    dimension_for,
    label_for,
    per_column,
    project,
    redact_result,
    skipped_keys,
)

logger = logging.getLogger(__name__)

_client = None
_experiment_id = None
_state = None  # None = not yet probed, True/False = probe result
_warned = False
_warned_raw = False
_commit = False  # False = not yet resolved, None = not a repo

# How many assessments to keep addressable at once.  An agent that opens an
# assessment and never closes it would otherwise grow the process forever; the
# runs themselves are already written and closed, so evicting a session only
# means a late end_assessment for it becomes a no-op.
MAX_TRACKED_SESSIONS = 64

# Which AIDRIN interface this process is (cli, mcp).  A property of the process,
# not of the call: the MCP server declares itself on import, so implicit sessions
# opened deep inside run_batch_metrics are attributed correctly instead of
# defaulting to "cli".
_default_interface = "cli"

# Shown as the experiment's description in the MLflow UI. Set only when AIDRIN
# creates the experiment: on a shared deployment these runs sit beside other
# teams' work, and a bare name leaves people guessing what produced them. An
# experiment that already exists is never relabelled.
# Shown as the description of an assessment run in the MLflow UI, where these
# rows sit beside other teams' runs.
ASSESSMENT_DESCRIPTION = "AIDRIN Assessment"

EXPERIMENT_DESCRIPTION = (
    "AIDRIN (AI Data Readiness Infrastructure) — dataset readiness assessments.\n\n"
    "Each run tagged `aidrin.run_type=assessment` is one dataset assessment and "
    "carries its aggregated readiness scores; the `metric` runs nested beneath it "
    "are the individual metrics, with their arguments as parameters and the full "
    "result as `result.json`."
)

# session id -> Session.  A plain dict keyed by a string, so that callers can
# thread an id through an API boundary (an MCP tool argument, a CLI run) without
# passing an object.  Deliberately *not* a "current session": the MCP server is
# one process serving many tool calls, and two overlapping assessments must not
# see each other's runs.
_sessions = collections.OrderedDict()


class Session:
    """Identifies one assessment: a parent run plus a tag for its children."""

    def __init__(self, session_id, parent_run_id, dataset=None, interface=None):
        self.session_id = session_id
        self.parent_run_id = parent_run_id
        self.dataset = dataset
        # Held on the session so metric runs agree with their assessment even
        # when the caller overrode the process default.
        self.interface = interface or _default_interface
        self.scores = {}
        self.failures = 0
        self.metrics_run = 0


def reset():
    """Forget the cached client and probe result.  For tests and re-config."""
    global _client, _experiment_id, _state, _warned
    global _warned_raw
    _client, _experiment_id, _state, _warned = None, None, None, False
    _warned_raw = False
    _sessions.clear()


def _log_data_details():
    """Dataset metadata — column names, file names, the result archive.

    On by default: without it a score is hard to act on, because you cannot see
    which columns produced it.  Set ``AIDRIN_MLFLOW_LOG_DATA_DETAILS=0`` to turn
    it off for a shared or untrusted tracking server.

    This governs *metadata*, not cell values.  Archived results are still
    redacted; ``AIDRIN_MLFLOW_LOG_RAW_RESULTS`` is what disables that, and it
    remains opt-in.
    """
    from aidrin.telemetry import _log_dataset_details

    return _log_dataset_details()


# MLflow's fluent API sets these on every run; MlflowClient.create_run sets none
# of them, so a client-only integration produces runs whose Source and User
# columns are blank in the UI.
def _system_tags():
    # On a shared tracking server the local OS account is the wrong identity:
    # it says "jlbez" where the account on the server is an email address.
    # MLFLOW_TRACKING_USERNAME is the user's declared identity for that server.
    user = os.environ.get("MLFLOW_TRACKING_USERNAME", "").strip()
    if not user:
        try:
            user = getpass.getuser()
        except Exception:
            user = "unknown"
    tags = {
        "mlflow.source.name": os.path.basename(sys.argv[0]) if sys.argv else "aidrin",
        "mlflow.source.type": "LOCAL",
        "mlflow.user": user,
    }
    commit = _git_commit()
    if commit:
        tags["mlflow.source.git.commit"] = commit
    return tags


def _git_commit():
    """The commit AIDRIN is running from, or None outside a repo.

    MLflow records this for runs launched from a working tree; a version number
    alone cannot distinguish two assessments made from different commits of the
    same release. Resolved once and cached — it cannot change mid-process.
    """
    global _commit
    if _commit is not False:
        return _commit

    _commit = None
    try:
        import subprocess

        here = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run(
            ["git", "-C", here, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            _commit = out.stdout.strip() or None
    except Exception:
        logger.debug("MLflow: could not resolve git commit", exc_info=True)
    return _commit


def _aidrin_version():
    try:
        from aidrin._version import __version__

        return str(__version__)
    except Exception:
        return "unknown"


# Arguments naming columns in the dataset.  Their *count* is always recorded —
# a k-anonymity score is meaningless without knowing how many quasi-identifiers
# produced it — but the names themselves are dataset content.
_COLUMN_ARGS = frozenset({
    "columns", "quasi_identifiers", "eval_columns", "cat_columns", "num_columns",
    "required_columns", "duplicate_columns", "target_columns", "target_column",
    "sensitive_column", "sensitive_attribute_column", "y_true_column", "id_column",
    "timestamp_column", "batch_column", "path_targets", "base_dir",
})

_MAX_PARAM_VALUE = 6000  # MLflow raises above this rather than truncating


def _is_empty(value):
    """True for values not worth logging, safely for array-likes."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return len(value) == 0
    except TypeError:
        return False  # scalars (including numpy scalars) are never "empty"


def _build_params(params):
    """Turn a metric's arguments into MLflow params.

    Without these a score cannot be interpreted: k-anonymity over two
    quasi-identifiers and over five both land in the same metric key.
    """
    out = {"aidrin_version": _aidrin_version()}
    details = _log_data_details()

    for key, value in (params or {}).items():
        # Not ``value == []``: numpy arrays compare elementwise and raise, and a
        # library caller may well pass one for a column list.
        if _is_empty(value):
            continue
        # Sized and not a string covers lists, tuples and numpy arrays alike;
        # the count is what makes a score comparable even when the names are
        # withheld.
        sequence = not isinstance(value, str) and hasattr(value, "__len__")

        if key in _COLUMN_ARGS:
            if sequence:
                out[f"{key}_count"] = str(len(value))
            if not details:
                continue
        rendered = ",".join(str(v) for v in value) if sequence else str(value)
        if len(rendered) > _MAX_PARAM_VALUE:
            rendered = rendered[: _MAX_PARAM_VALUE - 3] + "..."
        out[key] = rendered
    return out


def _write(run_id, metrics=None, params=None, tags=None):
    """Write metrics and params in one call.

    ``log_metric``/``log_param`` cost one HTTP round trip each; ``log_batch``
    sends them together.  Measured locally, 400 metrics took 1.77s written
    individually against 0.07s batched, and the gap widens against a remote
    tracking server.
    """
    from mlflow.entities import Metric, Param, RunTag

    stamp = int(time.time() * 1000)
    entries = [Metric(k, float(v), stamp, 0) for k, v in (metrics or {}).items()]
    values = [Param(k, str(v)) for k, v in (params or {}).items()]
    labels = [RunTag(k, str(v)) for k, v in (tags or {}).items()]
    if entries or values or labels:
        _client.log_batch(run_id, metrics=entries, params=values, tags=labels)


def _build_dataset(file_path):
    """Build the MLflow dataset entity for *file_path*, or None.

    Identity has to match what a training run over the same file produces, or
    the two never link and the whole "this data scored X, then we trained on it"
    story falls apart.  MLflow keys a dataset on name + digest and derives the
    digest from dataframe content, so the frame is read here and handed to
    ``mlflow.data.from_pandas`` — the same call a training script would make.

    AIDRIN's parser caches to Feather, so this is one read per assessment rather
    than per metric, and usually a cache hit.

    With dataset details switched off the real path must not appear, so the
    fallback is a hashed ``MetaDataset`` that deliberately does *not* match a
    training run.
    """
    dataset_id = _dataset_id(file_path)

    if _log_data_details() and file_path:
        try:
            import mlflow.data

            from aidrin.file_handling.file_parser import read_file

            name = os.path.basename(file_path)
            ext = os.path.splitext(file_path)[1].lower()
            frame = read_file((file_path, name, ext))
            return mlflow.data.from_pandas(frame, source=file_path, name=name)
        except Exception as exc:
            logger.debug(
                "MLflow: could not derive dataset digest (%s); falling back",
                type(exc).__name__,
            )

    try:
        from mlflow.data.http_dataset_source import HTTPDatasetSource
        from mlflow.data.meta_dataset import MetaDataset

        return MetaDataset(
            source=HTTPDatasetSource(url=f"aidrin://dataset/{dataset_id}"),
            name=dataset_id,
            digest=dataset_id[:36],
        )
    except Exception as exc:
        logger.debug("MLflow: could not build dataset (%s)", type(exc).__name__)
        return None


def _record_dataset(run_id, dataset):
    """Populate MLflow's native Dataset column.

    A tag is not enough: the UI's Dataset column and its dataset filters are fed
    by ``log_inputs``.
    """
    if dataset is None:
        return
    try:
        from mlflow.entities import DatasetInput

        _client.log_inputs(run_id, [DatasetInput(dataset._to_mlflow_entity())])
    except Exception as exc:
        logger.debug("MLflow: could not record dataset (%s)", type(exc).__name__)


def _has_failed(result):
    """Whether a metric errored.

    Metrics fail to an ``{"Error": ...}`` dict rather than raising, so without
    this a failed run and a run for a metric that declares no headline score
    look identical in MLflow: runtime only.
    """
    return isinstance(result, dict) and (
        "Error" in result or any(
            isinstance(v, dict) and "Error" in v for v in result.values()
        )
    )


def _log_raw_results():
    return os.environ.get("AIDRIN_MLFLOW_LOG_RAW_RESULTS", "").strip() in (
        "1", "true", "True"
    )


def _archive_result(run_id, metric_key, result):
    """Attach the full metric output as ``result.json``.

    Off unless ``AIDRIN_MLFLOW_LOG_DATA_DETAILS=1``: the archive carries column
    names, which the scores alone do not.  Redacted unless
    ``AIDRIN_MLFLOW_LOG_RAW_RESULTS=1`` is *also* set, which archives verbatim —
    including every value AIDRIN's PII and PHI scans matched.  Raw alone does not
    switch archiving on; it only changes how an already-enabled archive is written.
    """
    if not _log_data_details():
        return

    raw = _log_raw_results()
    payload = result if raw else redact_result(metric_key, result)
    global _warned_raw
    if raw and not _warned_raw:
        logger.warning(
            "AIDRIN_MLFLOW_LOG_RAW_RESULTS is set: metric results are being "
            "archived verbatim, including any PII or PHI they matched"
        )
        _warned_raw = True

    # A context manager, not mkdtemp: this runs once per metric inside
    # long-lived processes, so an un-removed directory per metric accumulates
    # on disk for the life of the MCP server.
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "result.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        _client.log_artifact(run_id, path)


def _dataset_id(file_path):
    """A stable identifier for a dataset that is not its path.

    Paths leak: ``/data/patients/MRN-4417723/scan.csv`` names a patient.  The
    digest is stable across runs, so comparing a dataset over time still works.
    """
    if not file_path:
        return "unknown"
    if _log_data_details():
        return os.path.basename(file_path)
    return hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()[:16]


def is_enabled():
    """True when tracking is configured, importable and the backend responds.

    Probed once.  A tracking server that cannot be reached disables the sink
    rather than letting the blanket guards turn every write into silence while
    discovery still advertises tracking as on.
    """
    global _client, _experiment_id, _state, _warned

    if _state is not None:
        return _state

    uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    flag = os.environ.get("AIDRIN_MLFLOW_ENABLED", "").strip() in ("1", "true", "True")
    if not uri or not flag:
        _state = False
        return False

    # A wedged tracking server must not hang a metric evaluation.  MLflow
    # defaults to a 120s HTTP timeout and 7 retries, so the worst case is over
    # ten minutes per call — the result would be computed and then thrown away.
    # setdefault, so an operator who has tuned these keeps their values.
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")

    # MLflow prints "View run <name> at: <url>" to stdout when it creates a run
    # against an HTTP tracking server. The MCP server speaks JSON-RPC over
    # stdout, so that line corrupts the stream and drops the connection. (A
    # file-store backend does not print, which is why only an end-to-end test
    # against a real server catches it.)
    os.environ.setdefault("MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT", "true")

    try:
        from mlflow.tracking import MlflowClient

        # Must happen before the client is built: gateways that want the
        # credential in their own header reject Authorization: Bearer, which is
        # all MLFLOW_TRACKING_TOKEN can send.
        from aidrin.telemetry import auth

        auth.register()

        client = MlflowClient(tracking_uri=uri)
        name = os.environ.get("AIDRIN_MLFLOW_EXPERIMENT", "aidrin")
        experiment = client.get_experiment_by_name(name)
        experiment_id = (
            experiment.experiment_id
            if experiment
            else client.create_experiment(
                name, tags={"mlflow.note.content": EXPERIMENT_DESCRIPTION}
            )
        )
    except Exception as exc:
        if not _warned:
            logger.warning(
                "MLflow tracking is configured but unusable (%s); continuing without it",
                type(exc).__name__,
            )
            _warned = True
        _state = False
        return False

    _client, _experiment_id, _state = client, experiment_id, True
    return True


def set_default_interface(interface):
    """Declare which interface this process is (``cli``, ``mcp``, ...)."""
    global _default_interface
    _default_interface = interface


def capabilities():
    """What the tracking sink can do right now, for capability discovery.

    Safe to call when the extra is absent: reports disabled rather than raising.
    """
    enabled = is_enabled()
    return {
        "mlflow_enabled": enabled,
        "experiment": os.environ.get("AIDRIN_MLFLOW_EXPERIMENT", "aidrin") if enabled else None,
    }


def start_session(file_path=None, interface=None):
    """Open an assessment.  Returns a :class:`Session`, or None when disabled."""
    if not is_enabled():
        return None

    interface = interface or _default_interface
    session_id = uuid.uuid4().hex[:16]
    dataset = _build_dataset(file_path)
    try:
        run = _client.create_run(
            _experiment_id,
            tags={
                "aidrin.session_id": session_id,
                # Explicit rather than inferred from the absence of
                # aidrin.metric: MLflow search cannot express "tag is absent",
                # so parents would not be selectable in the UI at all.
                "aidrin.run_type": "assessment",
                "aidrin.interface": interface,
                "mlflow.runName": f"assessment-{session_id[:8]}",
                "mlflow.note.content": ASSESSMENT_DESCRIPTION,
                **_system_tags(),
            },
        )
        # Terminated immediately: it is an anchor, not an open handle.  MLflow
        # still accepts metrics on a finished run, which is what end_session uses.
        _record_dataset(run.info.run_id, dataset)
        _write(run.info.run_id, params={"aidrin_version": _aidrin_version()})
        _client.set_terminated(run.info.run_id, "FINISHED")
        session = Session(session_id, run.info.run_id, dataset, interface)
        _sessions[session_id] = session
        while len(_sessions) > MAX_TRACKED_SESSIONS:
            _sessions.popitem(last=False)
        return session
    except Exception as exc:
        logger.warning("MLflow: could not start session (%s)", type(exc).__name__)
        return None


def get_session(session_id):
    """Resolve a session id to its :class:`Session`, or None."""
    if isinstance(session_id, Session):
        return session_id
    return _sessions.get(session_id) if session_id else None


def log_metric_result(
    session, metric_key, result, elapsed_seconds, file_path=None, params=None
):
    """Record one metric evaluation as its own run."""
    session = get_session(session)
    if session is None or not is_enabled():
        return

    try:
        projected = project(metric_key, result)
        skipped = skipped_keys(metric_key, result)

        failed = _has_failed(result)
        session.metrics_run += 1
        if failed:
            session.failures += 1

        tags = {
            "aidrin.session_id": session.session_id,
            "aidrin.run_type": "metric",
            # The message itself is never recorded: metric errors quote column
            # names and offending cell values.
            "aidrin.status": "error" if failed else "ok",
            "aidrin.metric": metric_key,
            # Carried on metric runs too, or the interface column is blank on
            # every row but the assessment.
            "aidrin.interface": session.interface,
            "mlflow.parentRunId": session.parent_run_id,
            "mlflow.runName": metric_key,
            "mlflow.note.content": label_for(metric_key),
            **_system_tags(),
        }
        if skipped:
            tags["aidrin.skipped_metrics"] = ",".join(skipped)

        run = _client.create_run(_experiment_id, tags=tags)
        run_id = run.info.run_id
        # Whatever happens next, the run must not be left RUNNING: an unclosed
        # run shows as in-progress in the UI forever.
        try:
            # Recorded on the metric run as well as the assessment, or the Dataset
            # column is blank on every drill-down row.
            _record_dataset(run_id, session.dataset)
            # Keep the best-known values for the parent's aggregated row.
            # Per-column values go on this run only. They follow the
            # dataset-details opt-out because the keys carry column names,
            # exactly as the column arguments in params do.
            columns = per_column(metric_key, result) if _log_data_details() else {}

            # Namespaced by dimension, so runtimes can be compared within one
            # readiness dimension rather than across all of them at once.
            dimension = dimension_for(metric_key)
            runtime_key = (
                f"aidrin.{dimension}.runtime_seconds"
                if dimension
                else "aidrin.runtime_seconds"
            )

            # Only the aggregates reach the parent's row: per-column keys differ
            # between datasets, and the assessment run is where runs are
            # compared against one another.
            session.scores.update(projected)

            _write(
                run_id,
                metrics={
                    **projected,
                    **columns,
                    runtime_key: float(elapsed_seconds),
                },
                params=_build_params(params),
            )
            _archive_result(run_id, metric_key, result)
        finally:
            _client.set_terminated(run_id, "FINISHED")
    except Exception as exc:
        logger.warning(
            "MLflow: could not log %s (%s)", metric_key, type(exc).__name__
        )


def end_session(session, report_path=None):
    """Write the aggregated readiness row onto the parent run."""
    session = get_session(session)
    if session is None or not is_enabled():
        return

    try:
        # An assessment where every metric failed is not the same as one where a
        # single privacy metric was misconfigured, so the two are distinguished.
        if not session.failures:
            status = "ok"
        elif session.failures < session.metrics_run:
            status = "partial"
        else:
            status = "error"

        _write(
            session.parent_run_id,
            metrics={
                **session.scores,
                "aidrin.failed_metrics": float(session.failures),
                "aidrin.metrics_run": float(session.metrics_run),
            },
            tags={"aidrin.status": status},
        )
        if report_path and os.path.exists(report_path):
            _client.log_artifact(session.parent_run_id, report_path)
    except Exception as exc:
        logger.warning("MLflow: could not close session (%s)", type(exc).__name__)
    finally:
        _sessions.pop(session.session_id, None)
