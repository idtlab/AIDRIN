"""Tests for Globus Compute integration (mocked — no real endpoint needed)."""

import os
import sys
import tempfile

import pandas as pd
import pytest

import aidrin
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
    assert [target["name"] for target in result["unit_targets"]] == ["age", "label"]


def test_remote_runner_data_structure_variable_unit_validation():
    path, name, file_type = _write_csv(pd.DataFrame({"speed": [1.0], "station": ["A"]}))
    try:
        result = remote_metric_runner(
            "data_structure",
            path,
            name,
            file_type,
            selected=["variable_unit_validation"],
            unit_declarations={
                "speed": {"unit": "m/s"},
                "station": {"status": "not_applicable"},
            },
        )
    finally:
        os.unlink(path)

    assert result["Variable Unit Validation"]["all_variables_ready"] is True


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
    assert "variable_unit_validation_v1" in info["capabilities"]


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


def test_check_endpoint_compatibility_preserves_worker_capabilities():
    local_py = ".".join(map(str, sys.version_info[:3]))
    client = _FakeClient({
        "aidrin_version": aidrin.__version__,
        "python_version": local_py,
        "capabilities": ["variable_unit_validation_v1"],
    })

    report = check_endpoint_compatibility(client, "endpoint-uuid")

    assert report["remote"]["capabilities"] == ["variable_unit_validation_v1"]


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
