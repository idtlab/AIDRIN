"""Globus web OAuth configuration (issue #206)."""

import pytest

from web.globus import (
    GLOBUS_WEB_AUTH_SETUP_MESSAGE,
    is_globus_available,
    is_globus_web_auth_configured,
)


def test_web_auth_not_configured_without_client_id(monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.delenv("GLOBUS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GLOBUS_CLIENT_SECRET", raising=False)
    assert is_globus_web_auth_configured() is False


def test_web_auth_configured_with_client_id(monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.setenv("GLOBUS_CLIENT_ID", "test-client-id")
    assert is_globus_web_auth_configured() is True


def test_globus_auth_returns_clear_error_without_client_id(client, monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.delenv("GLOBUS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GLOBUS_CLIENT_SECRET", raising=False)

    response = client.get("/globus/auth")
    assert response.status_code == 400
    data = response.get_json()
    assert data["code"] == "globus_web_auth_not_configured"
    assert "GLOBUS_CLIENT_ID" in data["error"]
    assert data["error"] == GLOBUS_WEB_AUTH_SETUP_MESSAGE
    assert "internal error" not in data["error"].lower()


def test_globus_status_reports_web_auth_flag(client, monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.delenv("GLOBUS_CLIENT_ID", raising=False)
    response = client.get("/globus/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["globus_available"] is True
    assert data["web_auth_configured"] is False


def test_inspector_shows_setup_when_web_auth_missing(client, monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.delenv("GLOBUS_CLIENT_ID", raising=False)
    response = client.get("/inspector")
    assert response.status_code == 200
    assert b"Globus web sign-in not configured" in response.data
    assert b"Sign in with Globus" not in response.data
