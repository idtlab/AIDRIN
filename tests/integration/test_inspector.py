"""Tests for the inspector page routes and rendering."""

from aidrin._version import __version__


# -------------------------------------------------
# Redirect tests
# -------------------------------------------------


def test_root_redirects_to_inspector(client):
    """/ should redirect to /inspector."""
    response = client.get("/")
    assert response.status_code == 302
    assert "/inspector" in response.headers["Location"]


def test_upload_file_redirects_to_inspector(client):
    """Legacy /upload-file should redirect to /inspector."""
    response = client.get("/upload-file")
    assert response.status_code == 302
    assert "/inspector" in response.headers["Location"]


def test_metric_routes_redirect_to_inspector(client):
    """Direct GET to metric routes should redirect to /inspector."""
    metric_routes = [
        "/data-quality",
        "/fairness",
        "/feature-relevance",
        "/correlation-analysis",
        "/class-imbalance",
        "/privacy-preservation",
        "/hipaa-compliance",
    ]
    for route in metric_routes:
        response = client.get(route)
        assert response.status_code == 302, f"{route} did not redirect"
        assert "/inspector" in response.headers["Location"], f"{route} did not redirect to /inspector"


def test_fair_assessment_get_redirects(client):
    """/fair-assessment GET should redirect to /inspector."""
    response = client.get("/fair-assessment")
    assert response.status_code == 302
    assert "/inspector" in response.headers["Location"]


def test_nonexistent_route(client):
    """Non-existent route should return 404."""
    response = client.get("/non-existent")
    assert response.status_code == 404


# -------------------------------------------------
# Inspector page rendering (no file uploaded)
# -------------------------------------------------


def test_inspector_get_no_file(client):
    """/inspector without upload should show the upload panel."""
    response = client.get("/inspector")
    assert response.status_code == 200
    html = response.data.decode()
    assert "AI Data Readiness Inspector" in html
    assert "Select a File Type" in html
    assert "https://aidrin.readthedocs.io/en/latest/" in html


def test_inspector_contains_version(uploaded_client):
    """Version string should appear in the sidebar when a file is uploaded."""
    response = uploaded_client.get("/inspector")
    html = response.data.decode()
    assert f"v{__version__}" in html


def test_inspector_no_sidebar_without_file(client):
    """Sidebar should not appear when no file is uploaded."""
    response = client.get("/inspector")
    html = response.data.decode()
    assert 'id="sidebar"' not in html


# -------------------------------------------------
# Inspector page rendering (file uploaded)
# -------------------------------------------------


def test_inspector_with_file_shows_sidebar(uploaded_client):
    """After upload, inspector should show the sidebar."""
    response = uploaded_client.get("/inspector")
    assert response.status_code == 200
    html = response.data.decode()
    assert 'id="sidebar"' in html
    assert "Data Quality" in html
    assert "Data Overview" in html


def test_inspector_with_file_shows_filename(uploaded_client):
    """After upload, the topbar should show the file name."""
    response = uploaded_client.get("/inspector")
    html = response.data.decode()
    assert "test_data.csv" in html


def test_inspector_with_file_shows_all_pillars(uploaded_client):
    """All 6 metric pillars should appear in the sidebar."""
    response = uploaded_client.get("/inspector")
    html = response.data.decode()
    for pillar in ["Data Quality", "Impact on AI", "Fairness", "Data Governance", "Understandability", "Data Structure"]:
        assert pillar in html, f"Pillar '{pillar}' not found in sidebar"


def test_inspector_with_file_loads_panels(uploaded_client):
    """All metric panels should be present in the DOM (hidden)."""
    response = uploaded_client.get("/inspector")
    html = response.data.decode()
    panels = [
        "panel-data-overview",
        "panel-data-quality",
        "panel-feature-relevance",
        "panel-correlation-analysis",
        "panel-fairness",
        "panel-class-imbalance",
        "panel-privacy-preservation",
        "panel-hipaa-compliance",
        "panel-fair-assessment",
    ]
    for panel_id in panels:
        assert panel_id in html, f"Panel '{panel_id}' not found in DOM"
