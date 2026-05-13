"""Tests for LLM explanation integration (works with or without openai installed)."""

from web.llm import is_llm_available

# Detect whether the openai package is available
try:
    import openai  # noqa: F401
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


def test_llm_availability():
    """is_llm_available reflects whether openai is installed."""
    assert is_llm_available() == _HAS_OPENAI


def test_llm_status_endpoint(client):
    """GET /llm/status returns availability info."""
    if not _HAS_OPENAI:
        # Blueprint not registered when openai is absent
        response = client.get("/llm/status")
        assert response.status_code == 404
    else:
        response = client.get("/llm/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["available"] is True
        assert data["configured"] is False


def test_llm_explain_requires_config(client):
    """POST /llm/explain without config returns 400."""
    if not _HAS_OPENAI:
        return  # blueprint not registered
    response = client.post("/llm/explain", json={
        "metric_name": "Completeness",
        "description": "Test description",
    })
    assert response.status_code == 400
    data = response.get_json()
    assert "not configured" in data["error"].lower()


def test_llm_configure_requires_api_key(client):
    """POST /llm/configure without api_key returns 400."""
    if not _HAS_OPENAI:
        return
    response = client.post("/llm/configure", json={
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    })
    assert response.status_code == 400
    assert "api key" in response.get_json()["error"].lower()


def test_llm_configure_and_disconnect(client):
    """Configure and disconnect cycle works."""
    if not _HAS_OPENAI:
        return
    # Configure
    response = client.post("/llm/configure", json={
        "api_base": "https://api.openai.com/v1",
        "api_key": "sk-test-key",
        "model": "gpt-4o-mini",
    })
    assert response.status_code == 200
    assert response.get_json()["success"] is True

    # Check status — should be configured
    response = client.get("/llm/status")
    data = response.get_json()
    assert data["configured"] is True

    # Disconnect
    response = client.post("/llm/disconnect")
    assert response.status_code == 200

    # Check status again — should not be configured
    response = client.get("/llm/status")
    data = response.get_json()
    assert data["configured"] is False


def test_llm_explain_no_body(client):
    """POST /llm/explain with no JSON body returns 400."""
    if not _HAS_OPENAI:
        return
    # First configure
    client.post("/llm/configure", json={
        "api_key": "sk-test",
        "model": "test",
    })
    response = client.post("/llm/explain", data="not json",
                           content_type="text/plain")
    assert response.status_code == 400


def test_explain_metric_without_openai():
    """explain_metric raises when openai is not installed."""
    import pytest
    from web.llm import explain_metric
    if _HAS_OPENAI:
        return  # can't test fallback when openai is installed
    with pytest.raises(RuntimeError, match="openai package not installed"):
        explain_metric("test", "base64data", {
            "api_base": "http://localhost",
            "api_key": "key",
            "model": "m",
        })
