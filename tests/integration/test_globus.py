"""Tests for Globus Compute integration (mocked — no real endpoint needed)."""

import sys

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
