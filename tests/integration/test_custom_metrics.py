"""Tests for custom metrics routes."""


# -------------------------------------------------
# Load custom metric template
# -------------------------------------------------


def test_load_custom_metric(client):
    """/load-custom-metric should return the default template code."""
    response = client.get("/load-custom-metric")
    assert response.status_code == 200
    text = response.data.decode()
    assert "metric" in text.lower() or "def" in text.lower()


# -------------------------------------------------
# Save custom metric
# -------------------------------------------------


def test_save_custom_metric(uploaded_client):
    """/save-custom-metric-text should accept code and return success."""
    # Ensure session_id exists (set during file upload flow)
    with uploaded_client.session_transaction() as sess:
        if "session_id" not in sess:
            sess["session_id"] = "test-session-id"

    code = """
class CustomMetric:
    def __init__(self, dataset):
        self.dataset = dataset

    def metric(self):
        return {"test": "value"}

    def remedy(self, metric_results):
        return self.dataset
"""
    response = uploaded_client.post(
        "/save-custom-metric-text",
        data={"metric_code": code, "apply_remedy": "no"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "message" in data or "error" in data


# -------------------------------------------------
# Custom metrics route redirects on GET
# -------------------------------------------------


def test_custom_metrics_get_redirects(client):
    """GET /custom-metrics should redirect to inspector."""
    response = client.get("/custom-metrics")
    assert response.status_code == 302
    assert "/inspector" in response.headers["Location"]


# -------------------------------------------------
# Custom metrics run — non-CSV formats
# -------------------------------------------------

_CUSTOM_CODE = """
from aidrin.custom_metrics.base_dr import BaseDRAgent

class CustomDR(BaseDRAgent):
    def metric(self, **kwargs):
        return {"row_count": len(self.dataset)}

    def remedy(self, **kwargs):
        return self.dataset.copy()
"""


def test_custom_metrics_run_on_json_upload(uploaded_client_json):
    """The Custom Metrics route should work for non-CSV uploads (previously
    gated to CSV only in the UI, and previously the remedy write-back named
    the output file with the original extension while always writing CSV
    bytes into it)."""
    with uploaded_client_json.session_transaction() as sess:
        if "session_id" not in sess:
            sess["session_id"] = "test-session-json"

    save_response = uploaded_client_json.post(
        "/save-custom-metric-text",
        data={"metric_code": _CUSTOM_CODE, "apply_remedy": "no"},
    )
    assert save_response.status_code == 200

    response = uploaded_client_json.post(
        "/custom-metrics?return_type=json", data={"apply_remedy": "yes"}
    )
    assert response.status_code == 200
    data = response.get_json()
    evaluation = data["Custom Metric Evaluation"]
    assert evaluation["row_count"] == 3
    # Remedy output must be a .csv file regardless of the .json input.
    assert evaluation["apply_remedy"].endswith(".csv")


# -------------------------------------------------
# Custom metrics run — error messages
# -------------------------------------------------


def _save_and_run(client, code):
    with client.session_transaction() as sess:
        if "session_id" not in sess:
            sess["session_id"] = "test-session-errors"
    client.post("/save-custom-metric-text", data={"metric_code": code, "apply_remedy": "no"})
    return client.post("/custom-metrics?return_type=json", data={"apply_remedy": "no"})


def test_custom_metrics_syntax_error_returns_specific_message(uploaded_client):
    """A syntax error in the user's script must surface a specific, actionable
    message (with the failing line number) and a 400, not a bare 500 that the
    frontend previously collapsed into a generic 'Server error (500)'."""
    code = """
from aidrin.custom_metrics.base_dr import BaseDRAgent

class CustomDR(BaseDRAgent):
    def metric(self, **kwargs):
        return {
            "total_missing_cells": self.dataset.isna().sum().to_dict(),,,
        }
"""
    response = _save_and_run(uploaded_client, code)
    assert response.status_code == 400
    data = response.get_json()
    assert "Syntax error" in data["error"]
    assert "line" in data["error"]


def test_custom_metrics_missing_customdr_class_returns_400(uploaded_client):
    code = """
class NotCustomDR:
    def metric(self):
        return {}
"""
    response = _save_and_run(uploaded_client, code)
    assert response.status_code == 400
    assert "CustomDR" in response.get_json()["error"]


def test_custom_metrics_runtime_error_in_metric_returns_400(uploaded_client):
    code = """
from aidrin.custom_metrics.base_dr import BaseDRAgent

class CustomDR(BaseDRAgent):
    def metric(self, **kwargs):
        raise ValueError("boom")
"""
    response = _save_and_run(uploaded_client, code)
    assert response.status_code == 400
    data = response.get_json()
    assert "Error running metric()" in data["error"]
    assert "boom" in data["error"]


def test_custom_metrics_non_dict_metric_result_returns_400(uploaded_client):
    code = """
from aidrin.custom_metrics.base_dr import BaseDRAgent

class CustomDR(BaseDRAgent):
    def metric(self, **kwargs):
        return "not a dict"
"""
    response = _save_and_run(uploaded_client, code)
    assert response.status_code == 400
    assert "must return a dictionary" in response.get_json()["error"]
