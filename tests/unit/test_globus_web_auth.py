"""Globus web OAuth configuration helpers (issue #206)."""

import pytest

from web.globus import is_globus_available, is_globus_web_auth_configured


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
