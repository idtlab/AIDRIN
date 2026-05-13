"""Tests for admin routes: images, docs, logs, publications."""


# -------------------------------------------------
# Publications
# -------------------------------------------------


def test_publications_renders(client):
    response = client.get("/publications")
    assert response.status_code == 200
    html = response.data.decode()
    assert "Publications" in html


# -------------------------------------------------
# Logs
# -------------------------------------------------


def test_logs_page_renders(client):
    response = client.get("/logs")
    assert response.status_code == 200
    html = response.data.decode()
    assert "Application Logs" in html


def test_view_logs_returns_json(client):
    """/view-logs returns JSON array or 404 error."""
    response = client.get("/view-logs")
    assert response.status_code in (200, 404)
    data = response.get_json()
    assert data is not None


# -------------------------------------------------
# Doc redirects
# -------------------------------------------------


def test_docs_index_redirects(client):
    response = client.get("/docs")
    assert response.status_code == 302
    assert "/docs/build/html/index.html" in response.headers["Location"]


def test_class_imbalance_docs_redirects(client):
    response = client.get("/class-imbalance-docs")
    assert response.status_code == 302
    assert "class_imbalance" in response.headers["Location"]


def test_privacy_metrics_docs_redirects(client):
    response = client.get("/privacy-metrics-docs")
    assert response.status_code == 302
    assert "privacy_metrics" in response.headers["Location"]


# -------------------------------------------------
# Image serving
# -------------------------------------------------


def test_serve_logo_image(client):
    """Logo image should be served from /images/."""
    response = client.get("/images/logoNoBackground.png")
    assert response.status_code == 200
    assert response.content_type.startswith("image/")
