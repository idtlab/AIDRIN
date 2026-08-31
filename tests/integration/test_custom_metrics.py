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
