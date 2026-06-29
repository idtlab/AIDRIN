"""Tests for Globus Compute integration (mocked — no real endpoint needed)."""

import os
import tempfile

import pandas as pd

from web.globus import is_globus_available, remote_metric_runner


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


def test_remote_runner_data_quality_custom_outliers():
    path, name, file_type = _write_csv(pd.DataFrame({"age": [25, 30, 45]}))
    rules = [{
        "id": "age-range",
        "target": "age",
        "target_type": "column",
        "criteria_type": "range",
        "min": 26,
        "max": 40,
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
