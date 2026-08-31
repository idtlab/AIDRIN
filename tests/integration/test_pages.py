"""Tests for supporting pages: logs, cache, publications."""

from aidrin._version import __version__


# -------------------------------------------------
# Logs page
# -------------------------------------------------


def test_logs_page_renders(client):
    """/logs should return 200 with the logs page."""
    response = client.get("/logs")
    assert response.status_code == 200
    html = response.data.decode()
    assert "Application Logs" in html
    assert "All Logs" in html
    assert "File Upload" in html
    assert "Metric" in html


def test_view_logs_json(client):
    """/view-logs should return JSON (array or error)."""
    response = client.get("/view-logs")
    assert response.status_code in (200, 404)
    data = response.get_json()
    assert data is not None
    # Either a list of log rows or an error dict
    assert isinstance(data, (list, dict))


# -------------------------------------------------
# Cache page
# -------------------------------------------------


def test_cache_page_renders(client):
    """/my-cache should return 200 with cache info."""
    response = client.get("/my-cache")
    assert response.status_code == 200
    html = response.data.decode()
    assert "Cache Information" in html


def test_cache_page_shows_stats(client):
    """Cache page should show stat boxes."""
    response = client.get("/my-cache")
    html = response.data.decode()
    assert "Cached Results" in html
    assert "Global Total" in html
    assert "User ID" in html


def test_clear_cache(client):
    """/clear-cache should return success JSON."""
    response = client.post(
        "/clear-cache",
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True


# -------------------------------------------------
# Publications page
# -------------------------------------------------


def test_publications_page_renders(client):
    """/publications should return 200."""
    response = client.get("/publications")
    assert response.status_code == 200
    html = response.data.decode()
    assert "Publications" in html


def test_publications_shows_papers(client):
    """Publications page should show both papers."""
    response = client.get("/publications")
    html = response.data.decode()
    assert "Data Readiness for AI: A 360-Degree Survey" in html
    assert "AI Data Readiness Inspector (AIDRIN)" in html


def test_publications_has_return_link(client):
    """Publications page should have a link back to inspector."""
    response = client.get("/publications")
    html = response.data.decode()
    assert "Return to Infrastructure" in html


# -------------------------------------------------
# Version injection across pages
# -------------------------------------------------


def test_version_in_inspector(uploaded_client):
    """Inspector page should contain version string in sidebar."""
    response = uploaded_client.get("/inspector")
    html = response.data.decode()
    assert f"v{__version__}" in html


def test_version_in_cache_page(client):
    """Cache page (via _base.html) should have proper title."""
    response = client.get("/my-cache")
    html = response.data.decode()
    assert "AIDRIN" in html
