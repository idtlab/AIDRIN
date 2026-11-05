"""Tests for admin routes: images, docs, logs, publications."""

import pathlib
import re

import pytest

from web.routes import admin


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


def test_logs_page_forbidden_when_viewer_disabled(app):
    """/logs is gated behind ENABLE_LOG_VIEWER."""
    app.config["ENABLE_LOG_VIEWER"] = False
    response = app.test_client().get("/logs")
    assert response.status_code == 403


def test_view_logs_forbidden_when_viewer_disabled(app):
    """/view-logs is gated behind ENABLE_LOG_VIEWER."""
    app.config["ENABLE_LOG_VIEWER"] = False
    response = app.test_client().get("/view-logs")
    assert response.status_code == 403


# -------------------------------------------------
# Doc redirects
# -------------------------------------------------


DOCS_SOURCE = pathlib.Path(__file__).resolve().parents[2] / "docs" / "source"
DOCS_ROUTES = ["/docs", "/class-imbalance-docs", "/privacy-metrics-docs"]


def _buildable_pages():
    """HTML page names a Sphinx build of docs/source actually produces."""
    return {path.stem + ".html" for path in DOCS_SOURCE.glob("*.rst")}


def _section_anchors(page):
    """Anchors Sphinx generates from the section headings of one page."""
    lines = (DOCS_SOURCE / (page[:-len(".html")] + ".rst")).read_text().splitlines()
    anchors = set()
    for text, underline in zip(lines, lines[1:]):
        title = text.strip()
        rule = underline.strip()
        if not title or not re.fullmatch(r"[-=~^'\"+*#]{3,}", rule):
            continue
        if len(rule) < len(title) - 2:
            continue
        anchors.add(re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"))
    # Explicit label targets (.. _name:) are anchors too.
    for line in lines:
        label = re.fullmatch(r"\.\. _([A-Za-z0-9_-]+):", line.strip())
        if label:
            anchors.add(label.group(1).replace("_", "-"))
    return anchors


@pytest.mark.parametrize("url", DOCS_ROUTES)
def test_docs_redirect_target_is_a_page_that_exists(client, url):
    """These links 404'd because they pointed at pages no build produces."""
    response = client.get(url)
    assert response.status_code == 302
    page, _, anchor = response.headers["Location"].partition("#")
    page = page.rsplit("/", 1)[-1]

    assert page in _buildable_pages(), (
        f"{url} redirects to {page!r}, which no docs/source/*.rst produces"
    )
    if anchor:
        assert anchor in _section_anchors(page), (
            f"{url} redirects to #{anchor}, which is not a section of {page}"
        )


def test_docs_url_prefers_a_local_sphinx_build(monkeypatch):
    monkeypatch.setattr(admin.os.path, "exists", lambda _path: True)
    assert admin.docs_url("web_usage.html", "#data-governance") == (
        "/docs/build/html/web_usage.html#data-governance"
    )


def test_docs_url_falls_back_to_hosted_docs(monkeypatch):
    monkeypatch.setattr(admin.os.path, "exists", lambda _path: False)
    url = admin.docs_url("web_usage.html", "#data-governance")
    assert url == "https://aidrin.readthedocs.io/en/latest/web_usage.html#data-governance"


def test_javascript_docs_links_point_at_real_routes(app):
    """main.js hardcodes its docs href, so it cannot be caught by url_for."""
    js = (
        pathlib.Path(__file__).resolve().parents[2] / "web" / "static" / "js" / "main.js"
    ).read_text()
    targets = set(re.findall(r'href="(/[a-z0-9-]*docs[a-z0-9-]*)"', js))
    assert targets, "expected at least one hardcoded docs link in main.js"
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    for target in sorted(targets):
        assert target in rules, f"main.js links to {target}, which is not a route"


# -------------------------------------------------
# Image serving
# -------------------------------------------------


def test_serve_logo_image(client):
    """Logo image should be served from /images/."""
    response = client.get("/images/logoNoBackground.png")
    assert response.status_code == 200
    assert response.content_type.startswith("image/")
