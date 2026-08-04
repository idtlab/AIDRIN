"""Tests for Globus Compute integration (mocked — no real endpoint needed)."""

import os
import json
import sys
import tempfile

import pandas as pd
import pytest

import aidrin
import web.routes.globus as globus_routes
from web.globus import (
    is_globus_available,
    remote_metric_runner,
    remote_env_probe,
    check_endpoint_compatibility,
)


# -------------------------------------------------
# Availability
# -------------------------------------------------


def test_globus_availability():
    """is_globus_available should return bool (True if SDK installed, False otherwise)."""
    result = is_globus_available()
    assert isinstance(result, bool)


# -------------------------------------------------
# Inspector shows/hides Globus option
# -------------------------------------------------


def test_inspector_passes_globus_flag(client):
    """Inspector page should include globus_available context."""
    response = client.get("/inspector")
    assert response.status_code == 200
    # The template conditionally renders based on globus_available
    # We can't check the flag directly, but the page should render without error


def test_globus_status_endpoint(client):
    """/globus/status should return availability info."""
    if not is_globus_available():
        # Blueprint not registered — 404 is expected
        response = client.get("/globus/status")
        assert response.status_code == 404
    else:
        response = client.get("/globus/status")
        assert response.status_code == 200
        data = response.get_json()
        assert "globus_available" in data
        assert "authenticated" in data


def test_globus_submit_without_auth(client):
    """Submitting without Globus auth should return 401."""
    if not is_globus_available():
        return  # Skip if SDK not installed

    response = client.post(
        "/globus/submit",
        json={
            "endpoint_id": "test-uuid",
            "file_path": "/data/test.csv",
            "file_type": ".csv",
            "metric_name": "completeness",
        },
    )
    assert response.status_code == 401


def test_globus_check_task_without_auth(client):
    """Checking task without auth should return 401."""
    if not is_globus_available():
        return

    response = client.get("/globus/check-task/fake-task-id")
    assert response.status_code == 401


def test_globus_disconnect(client):
    """/globus/disconnect should clear session."""
    if not is_globus_available():
        return

    response = client.post("/globus/disconnect")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True


# -------------------------------------------------
# Remote metric runner (unit test — runs locally)
# -------------------------------------------------


def test_remote_runner_unknown_metric():
    """Unknown metric name should return error dict."""
    result = remote_metric_runner("nonexistent", "/tmp/test.csv", "test.csv", ".csv")
    assert "error" in result
    assert "Unknown metric" in result["error"]


def test_remote_runner_missing_file():
    """Non-existent file should return error dict."""
    result = remote_metric_runner("completeness", "/tmp/does_not_exist.csv", "missing.csv", ".csv")
    assert "error" in result or "Error" in str(result)


def _write_csv(df):
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return tmp.name, os.path.basename(tmp.name), ".csv"


def test_remote_runner_custom_outlier_targets():
    path, name, file_type = _write_csv(pd.DataFrame({"age": [25, 30], "label": ["a", "b"]}))
    try:
        result = remote_metric_runner("custom_outlier_targets", path, name, file_type)
    finally:
        os.unlink(path)

    assert result["success"] is True
    assert any(target["name"] == "age" for target in result["targets"])
    assert result["file_reference"]["enabled"] is False


def test_remote_runner_file_reference_discovery_uses_worker_environment(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("path\nartifact.bin\n", encoding="utf-8")
    monkeypatch.setenv("AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS", json.dumps([str(tmp_path)]))
    monkeypatch.setenv("AIDRIN_FILE_REFERENCE_WEB_SCAN_LIMIT", "17")

    result = remote_metric_runner("custom_outlier_targets", str(manifest), manifest.name, ".csv")

    assert result["file_reference"] == {
        "enabled": True,
        "roots": [{"id": "root-0", "label": str(tmp_path)}],
        "scan_limit": 17,
    }


def test_remote_runner_file_reference_standalone_and_bundled(monkeypatch, tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"aidrin")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("path\nartifact.bin\n", encoding="utf-8")
    monkeypatch.setenv("AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS", json.dumps([str(tmp_path)]))
    params = {
        "path_targets": ["path"],
        "root_id": "root-0",
        "base_subdirectory": "",
        "max_results": 5,
        "target_match": "exact",
    }

    standalone = remote_metric_runner(
        "file_reference_validation", str(manifest), manifest.name, ".csv", **params
    )
    bundled = remote_metric_runner(
        "data_structure",
        str(manifest),
        manifest.name,
        ".csv",
        selected=["constant_feature_count", "file_reference_validation"],
        **params,
    )

    assert standalone["Summary"]["all_references_valid"] is True
    assert "File Reference Validation" not in standalone
    assert bundled["File Reference Validation"]["Summary"] == standalone["Summary"]
    assert "Constant Feature Count" in bundled


def test_remote_runner_file_reference_failure_is_metric_scoped(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("path\nmissing.bin\n", encoding="utf-8")
    monkeypatch.delenv("AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS", raising=False)

    result = remote_metric_runner(
        "data_structure",
        str(manifest),
        manifest.name,
        ".csv",
        selected=["constant_feature_count", "file_reference_validation"],
        path_targets=["path"],
        root_id="root-0",
    )

    assert "Constant Feature Count" in result
    assert "Select an allowed filesystem root" in result["File Reference Validation"]["Error"]


def test_remote_runner_data_quality_custom_outliers():
    path, name, file_type = _write_csv(pd.DataFrame({"age": [25, 30, 45]}))
    rules = [{
        "id": "age-range",
        "target": "age",
        "target_type": "column",
        "criteria": {"type": "range", "min": 26, "max": 40},
    }]
    try:
        result = remote_metric_runner(
            "data_quality",
            path,
            name,
            file_type,
            selected=["custom_outliers"],
            custom_outlier_rules=rules,
            max_outliers=1,
            max_export_rows=2,
            stop_after_outliers=False,
        )
    finally:
        os.unlink(path)

    assert "Custom Criteria Outliers" in result
    custom = result["Custom Criteria Outliers"]
    assert custom["Rule summaries"]["age-range"]["outlier"] == 2
    assert len(custom["Outlier preview"]["age-range"]) == 1
    assert len(custom["Outlier export"]["age-range"]) == 2


def test_remote_runner_data_quality_custom_outlier_error_is_metric_scoped():
    path, name, file_type = _write_csv(pd.DataFrame({"age": [25, 30, 45]}))
    try:
        result = remote_metric_runner(
            "data_quality",
            path,
            name,
            file_type,
            selected=["completeness", "custom_outliers"],
            custom_outlier_rules=[],
        )
    finally:
        os.unlink(path)

    assert "Completeness" in result
    assert "Custom Criteria Outliers" in result
    assert "Error" in result["Custom Criteria Outliers"]


# -------------------------------------------------
# Runner lives in aidrin (so the remote worker can import it)
# -------------------------------------------------


def test_remote_runner_defined_in_aidrin():
    """The runner must be defined in ``aidrin.compute.remote`` — Globus serialises
    it by reference, and the endpoint has ``aidrin`` installed but not ``web``.
    """
    assert remote_metric_runner.__module__ == "aidrin.compute.remote"


# -------------------------------------------------
# Environment probe (unit test — runs locally)
# -------------------------------------------------


def test_remote_env_probe_reports_versions():
    """Probe returns this environment's aidrin + Python versions."""
    info = remote_env_probe()
    assert info["aidrin_version"] == aidrin.__version__
    assert info["python_version"] == ".".join(map(str, sys.version_info[:3]))
    assert info["capability_schema_version"] == 1
    assert info["capabilities"] == ["file_reference_validation_v1"]


# -------------------------------------------------
# Endpoint compatibility check (mocked client)
# -------------------------------------------------


class _FakeClient:
    """Minimal stand-in for globus_compute_sdk.Client used by the probe."""

    def __init__(self, probe_result):
        self._probe_result = probe_result

    def register_function(self, fn):
        return "fake-func-uuid"

    def run(self, *args, **kwargs):
        return "fake-task-uuid"

    def get_result(self, task_id):
        return self._probe_result


def test_check_endpoint_compatibility_matching():
    """Same aidrin + Python versions → compatible, no warnings."""
    local_py = ".".join(map(str, sys.version_info[:3]))
    client = _FakeClient({
        "aidrin_version": aidrin.__version__,
        "python_version": local_py,
    })
    report = check_endpoint_compatibility(client, "endpoint-uuid")
    assert report["compatible"] is True
    assert report["warnings"] == []
    assert report["remote"]["aidrin"] == aidrin.__version__
    assert report["remote"]["capabilities"] == []


def test_check_endpoint_compatibility_reports_optional_capabilities():
    local_py = ".".join(map(str, sys.version_info[:3]))
    client = _FakeClient({
        "aidrin_version": aidrin.__version__,
        "python_version": local_py,
        "capability_schema_version": 1,
        "capabilities": ["file_reference_validation_v1"],
    })

    report = check_endpoint_compatibility(client, "endpoint-uuid")

    assert report["compatible"] is True
    assert report["remote"]["capability_schema_version"] == 1
    assert report["remote"]["capabilities"] == ["file_reference_validation_v1"]


def test_check_endpoint_compatibility_ignores_unknown_capability_schema():
    local_py = ".".join(map(str, sys.version_info[:3]))
    client = _FakeClient({
        "aidrin_version": aidrin.__version__,
        "python_version": local_py,
        "capability_schema_version": 99,
        "capabilities": ["file_reference_validation_v1"],
    })

    report = check_endpoint_compatibility(client, "endpoint-uuid")

    assert report["compatible"] is True
    assert report["remote"]["capabilities"] == []
    assert any("unsupported schema" in warning for warning in report["warnings"])


def test_check_endpoint_compatibility_aidrin_mismatch():
    """Different aidrin major.minor → incompatible with a warning."""
    local_py = ".".join(map(str, sys.version_info[:3]))
    client = _FakeClient({
        "aidrin_version": "1999.01.0",
        "python_version": local_py,
    })
    report = check_endpoint_compatibility(client, "endpoint-uuid")
    assert report["compatible"] is False
    assert any("aidrin version mismatch" in w for w in report["warnings"])


def test_check_endpoint_compatibility_python_mismatch_is_warning():
    """Different Python minor → still compatible, but warns."""
    client = _FakeClient({
        "aidrin_version": aidrin.__version__,
        "python_version": "2.7.18",
    })
    report = check_endpoint_compatibility(client, "endpoint-uuid")
    assert report["compatible"] is True
    assert any("Python version differs" in w for w in report["warnings"])


# -------------------------------------------------
# /globus/check-endpoint route
# -------------------------------------------------


def test_globus_check_endpoint_without_auth(client):
    """Checking an endpoint without Globus auth should return 401."""
    if not is_globus_available():
        return

    response = client.post("/globus/check-endpoint", json={"endpoint_id": "x"})
    assert response.status_code == 401


class _FailingProbeClient:
    """Client whose endpoint cannot deserialise the probe (old aidrin)."""

    def __init__(self, exc):
        self._exc = exc

    def register_function(self, fn):
        return "fake-func-uuid"

    def run(self, *args, **kwargs):
        return "fake-task-uuid"

    def get_result(self, task_id):
        raise self._exc


def test_check_endpoint_compatibility_old_endpoint_missing_probe():
    """Endpoint too old to have aidrin.compute.remote → incompatible, clear message."""
    client = _FailingProbeClient(
        ModuleNotFoundError("No module named 'aidrin.compute'")
    )
    report = check_endpoint_compatibility(client, "endpoint-uuid")
    assert report["compatible"] is False
    assert any(aidrin.__version__ in w for w in report["warnings"])
    assert report["remote"]["aidrin"] == "unknown"


def test_check_endpoint_compatibility_infra_error_propagates():
    """A non-probe error (e.g. timeout) is not masked as a version issue."""
    import pytest

    client = _FailingProbeClient(TimeoutError("endpoint offline"))
    with pytest.raises(TimeoutError):
        check_endpoint_compatibility(client, "endpoint-uuid")


# -------------------------------------------------
# Headless remote path (needs a real endpoint)
# -------------------------------------------------

AIDRIN_TEST_ENDPOINT = os.environ.get("AIDRIN_TEST_ENDPOINT")
AIDRIN_TEST_REMOTE_FILE = os.environ.get("AIDRIN_TEST_REMOTE_FILE")


@pytest.mark.skipif(
    not (AIDRIN_TEST_ENDPOINT and AIDRIN_TEST_REMOTE_FILE),
    reason="Set AIDRIN_TEST_ENDPOINT and AIDRIN_TEST_REMOTE_FILE to run",
)
def test_remote_summarize_matches_local():
    """The same file summarized locally and remotely must agree.

    AIDRIN_TEST_REMOTE_FILE must name a file present at the same path on both
    this machine and the endpoint.
    """
    from aidrin.compute.executor import RemoteExecutor
    from aidrin.compute.profiles import RemoteTarget
    from aidrin.headless.api import summarize_dataset

    local = summarize_dataset(AIDRIN_TEST_REMOTE_FILE)
    target = RemoteTarget(endpoint=AIDRIN_TEST_ENDPOINT, profile=None, source="flag")
    remote = RemoteExecutor(target).summarize_dataset(AIDRIN_TEST_REMOTE_FILE)

    assert remote["shape"] == local["shape"]
    assert remote["columns"] == local["columns"]
    assert remote["numerical"].keys() == local["numerical"].keys()


@pytest.mark.skipif(
    not (AIDRIN_TEST_ENDPOINT and AIDRIN_TEST_REMOTE_FILE),
    reason="Set AIDRIN_TEST_ENDPOINT and AIDRIN_TEST_REMOTE_FILE to run",
)
def test_remote_probe_reports_headless_import():
    from aidrin.compute import client as compute_client

    env = compute_client.probe(compute_client.get_client(), AIDRIN_TEST_ENDPOINT)
    assert env["headless_import"] is True
    assert env["aidrin_version"]

# Negotiation and asynchronous task context routes
# -------------------------------------------------


def _compatibility_report(capabilities=(), compatible=True):
    return {
        "compatible": compatible,
        "local": {"aidrin": aidrin.__version__, "python": "3.12.0"},
        "remote": {
            "aidrin": aidrin.__version__ if compatible else "1999.01.0",
            "python": "3.12.0",
            "capability_schema_version": 1 if capabilities else None,
            "capabilities": list(capabilities),
        },
        "warnings": [],
    }


def _authenticate(client):
    with client.session_transaction() as flask_session:
        flask_session["globus_authenticated"] = True
        flask_session["globus_tokens"] = {"compute.api.globus.org": {"access_token": "test"}}


def _submission(metric_name="completeness", params=None):
    return {
        "endpoint_id": "endpoint-uuid",
        "file_path": "/remote/manifest.csv",
        "file_name": "manifest.csv",
        "file_type": ".csv",
        "metric_name": metric_name,
        "params": params or {},
    }


def test_capability_absent_worker_runs_existing_metrics_but_not_file_reference(client, monkeypatch):
    if not is_globus_available():
        return
    _authenticate(client)
    monkeypatch.setattr(globus_routes, "get_compute_client", lambda _tokens: object())
    monkeypatch.setattr(globus_routes, "check_endpoint_compatibility", lambda *_args: _compatibility_report())
    monkeypatch.setattr(globus_routes, "submit_metric", lambda *_args, **_kwargs: "existing-task")

    existing = client.post("/globus/submit", json=_submission())
    blocked = client.post(
        "/globus/submit",
        json=_submission("file_reference_validation", {"path_targets": ["path"], "root_id": "root-0"}),
    )

    assert existing.status_code == 200
    assert existing.get_json()["task_id"] == "existing-task"
    assert blocked.status_code == 409
    assert "Upgrade AIDRIN" in blocked.get_json()["error"]


def test_worker_policy_cannot_be_overridden_in_file_reference_submission(client, monkeypatch):
    if not is_globus_available():
        return
    _authenticate(client)
    monkeypatch.setattr(globus_routes, "get_compute_client", lambda _tokens: object())
    monkeypatch.setattr(
        globus_routes,
        "check_endpoint_compatibility",
        lambda *_args: _compatibility_report(["file_reference_validation_v1"]),
    )

    response = client.post(
        "/globus/submit",
        json=_submission(
            "file_reference_validation",
            {"path_targets": ["path"], "root_id": "root-0", "scan_limit": 0},
        ),
    )

    assert response.status_code == 400
    assert "controlled by the Compute worker" in response.get_json()["error"]


def test_bundled_file_reference_submission_forwards_browser_choices(client, monkeypatch):
    if not is_globus_available():
        return
    _authenticate(client)
    captured = {}
    monkeypatch.setattr(globus_routes, "get_compute_client", lambda _tokens: object())
    monkeypatch.setattr(
        globus_routes,
        "check_endpoint_compatibility",
        lambda *_args: _compatibility_report(["file_reference_validation_v1"]),
    )

    def capture_submission(_client, _endpoint_id, _metric_name, _path, _name, _type, **params):
        captured.update(params)
        return "file-reference-task"

    monkeypatch.setattr(globus_routes, "submit_metric", capture_submission)
    params = {
        "selected": ["constant_feature_count", "file_reference_validation"],
        "path_targets": ["primary_path", "secondary_path"],
        "target_match": "exact",
        "root_id": "root-0",
        "base_subdirectory": "artifacts",
        "max_results": 25,
    }

    response = client.post("/globus/submit", json=_submission("data_structure", params))

    assert response.status_code == 200
    assert captured == params


def test_baseline_incompatible_worker_is_rejected_even_with_capability(client, monkeypatch):
    if not is_globus_available():
        return
    _authenticate(client)
    monkeypatch.setattr(globus_routes, "get_compute_client", lambda _tokens: object())
    monkeypatch.setattr(
        globus_routes,
        "check_endpoint_compatibility",
        lambda *_args: _compatibility_report(["file_reference_validation_v1"], compatible=False),
    )

    response = client.post("/globus/submit", json=_submission())

    assert response.status_code == 409
    assert "incompatible" in response.get_json()["error"]


def test_expired_negotiation_is_reprobed(client, monkeypatch):
    if not is_globus_available():
        return
    _authenticate(client)
    calls = []
    monkeypatch.setattr(globus_routes, "get_compute_client", lambda _tokens: object())
    monkeypatch.setattr(
        globus_routes,
        "check_endpoint_compatibility",
        lambda *_args: calls.append("probe") or _compatibility_report(),
    )
    monkeypatch.setattr(globus_routes, "submit_metric", lambda *_args, **_kwargs: "task-id")
    with client.session_transaction() as flask_session:
        flask_session["globus_endpoint_negotiation"] = {
            "endpoint_id": "endpoint-uuid",
            "remote_aidrin_version": aidrin.__version__,
            "capability_schema_version": None,
            "capabilities": [],
            "checked_at": 0,
            "fingerprint": "old",
        }

    assert client.post("/globus/submit", json=_submission()).status_code == 200
    assert calls == ["probe"]


def test_discovery_context_is_retained_pending_and_cleaned_on_completion(client, monkeypatch):
    if not is_globus_available():
        return
    _authenticate(client)
    monkeypatch.setattr(globus_routes, "get_compute_client", lambda _tokens: object())
    monkeypatch.setattr(
        globus_routes,
        "check_endpoint_compatibility",
        lambda *_args: _compatibility_report(["file_reference_validation_v1"]),
    )
    monkeypatch.setattr(globus_routes, "submit_metric", lambda *_args, **_kwargs: "discovery-task")
    monkeypatch.setattr(
        globus_routes,
        "check_task",
        lambda *_args: {"status": "processing", "progress": {"status": "running"}},
    )

    submitted = client.post("/globus/submit", json=_submission("custom_outlier_targets"))
    assert submitted.get_json()["negotiation_expires_at"] > 0
    assert client.get("/globus/check-task/discovery-task").get_json()["status"] == "processing"
    with client.session_transaction() as flask_session:
        context = flask_session["globus_task_contexts"]["discovery-task"]
        assert context["operation"] == "target_discovery"
        assert context["expected_capability"] == "file_reference_validation_v1"

    monkeypatch.setattr(
        globus_routes,
        "check_task",
        lambda *_args: {
            "status": "completed",
            "result": {
                "success": True,
                "targets": [],
                "file_reference": {"enabled": False, "roots": [], "scan_limit": 10},
            },
        },
    )
    assert client.get("/globus/check-task/discovery-task").status_code == 200
    with client.session_transaction() as flask_session:
        assert "discovery-task" not in flask_session["globus_active_tasks"]
        assert "discovery-task" not in flask_session["globus_task_contexts"]


def test_malformed_discovery_invalidates_only_matching_capability(client, monkeypatch):
    if not is_globus_available():
        return
    _authenticate(client)
    monkeypatch.setattr(globus_routes, "get_compute_client", lambda _tokens: object())
    monkeypatch.setattr(
        globus_routes,
        "check_endpoint_compatibility",
        lambda *_args: _compatibility_report(["file_reference_validation_v1", "another_capability"]),
    )
    monkeypatch.setattr(globus_routes, "submit_metric", lambda *_args, **_kwargs: "malformed-task")
    client.post("/globus/submit", json=_submission("custom_outlier_targets"))
    monkeypatch.setattr(
        globus_routes,
        "check_task",
        lambda *_args: {"status": "completed", "result": {"success": True, "targets": []}},
    )

    result = client.get("/globus/check-task/malformed-task").get_json()

    assert result["capability_invalidated"] is True
    assert result["result"]["file_reference"]["enabled"] is False
    with client.session_transaction() as flask_session:
        assert flask_session["globus_endpoint_negotiation"]["capabilities"] == ["another_capability"]


def test_late_malformed_discovery_cannot_change_refreshed_negotiation(client, monkeypatch):
    if not is_globus_available():
        return
    _authenticate(client)
    monkeypatch.setattr(globus_routes, "get_compute_client", lambda _tokens: object())
    monkeypatch.setattr(
        globus_routes,
        "check_endpoint_compatibility",
        lambda *_args: _compatibility_report(["file_reference_validation_v1"]),
    )
    monkeypatch.setattr(globus_routes, "submit_metric", lambda *_args, **_kwargs: "late-task")
    client.post("/globus/submit", json=_submission("custom_outlier_targets"))
    with client.session_transaction() as flask_session:
        record = flask_session["globus_endpoint_negotiation"]
        record["checked_at"] += 1
        record["fingerprint"] = "refreshed-fingerprint"
        flask_session["globus_endpoint_negotiation"] = record
    monkeypatch.setattr(
        globus_routes,
        "check_task",
        lambda *_args: {"status": "completed", "result": {"success": True, "targets": []}},
    )

    result = client.get("/globus/check-task/late-task").get_json()

    assert result["capability_invalidated"] is False
    with client.session_transaction() as flask_session:
        assert "file_reference_validation_v1" in flask_session["globus_endpoint_negotiation"]["capabilities"]


def test_disconnect_clears_negotiation_and_task_context(client, monkeypatch):
    if not is_globus_available():
        return
    _authenticate(client)
    stopped = []

    class CancelClient:
        def stop(self, task_id):
            stopped.append(task_id)

    monkeypatch.setattr(globus_routes, "get_compute_client", lambda _tokens: CancelClient())
    with client.session_transaction() as flask_session:
        flask_session["globus_active_tasks"] = ["task-id"]
        flask_session["globus_task_contexts"] = {"task-id": {"operation": "metric_execution"}}
        flask_session["globus_endpoint_negotiation"] = {"endpoint_id": "endpoint-uuid"}

    assert client.post("/globus/disconnect").status_code == 200
    assert stopped == ["task-id"]
    with client.session_transaction() as flask_session:
        assert "globus_active_tasks" not in flask_session
        assert "globus_task_contexts" not in flask_session
        assert "globus_endpoint_negotiation" not in flask_session
