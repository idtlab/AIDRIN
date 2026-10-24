"""Globus web OAuth configuration — HTTP integration (issue #206)."""

import pytest

from web.globus import (
    GLOBUS_WEB_AUTH_SETUP_MESSAGE,
    get_globus_web_client_id,
    is_globus_available,
)


def test_globus_auth_returns_clear_error_without_client_id(client, monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.delenv("GLOBUS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GLOBUS_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GLOBUS_REDIRECT_URI", "https://aidrin.example.org/globus/callback")

    response = client.get("/globus/auth")
    assert response.status_code == 400
    data = response.get_json()
    assert data["code"] == "globus_web_auth_not_configured"
    assert "GLOBUS_CLIENT_ID" in data["error"]
    assert data["error"] == GLOBUS_WEB_AUTH_SETUP_MESSAGE
    assert "internal error" not in data["error"].lower()


def test_globus_auth_starts_flow_on_localhost_without_env(client, monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.delenv("GLOBUS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GLOBUS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GLOBUS_REDIRECT_URI", raising=False)
    assert get_globus_web_client_id()

    response = client.get("/globus/auth", follow_redirects=False)
    assert response.status_code == 302
    assert "auth.globus.org" in response.headers.get("Location", "")


def test_globus_status_reports_web_auth_flag(client, monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.delenv("GLOBUS_CLIENT_ID", raising=False)
    response = client.get("/globus/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["globus_available"] is True
    assert data["web_auth_configured"] is True
    assert data["web_auth_uses_aidrin_default_client"] is True


def test_inspector_shows_setup_when_web_auth_missing(client, monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.delenv("GLOBUS_CLIENT_ID", raising=False)
    monkeypatch.setenv("GLOBUS_REDIRECT_URI", "https://aidrin.example.org/globus/callback")

    response = client.get("/inspector")
    assert response.status_code == 200
    assert b"Globus web sign-in not configured" in response.data
    assert b'href="/globus/auth"' not in response.data
