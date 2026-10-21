"""Globus web OAuth configuration helpers (issue #206)."""

import pytest

from web.globus import (
    get_globus_web_client_id,
    is_globus_available,
    is_globus_web_auth_configured,
    globus_web_auth_uses_builtin_client,
)


def test_web_auth_uses_builtin_client_without_env(monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.delenv("GLOBUS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GLOBUS_CLIENT_SECRET", raising=False)
    assert get_globus_web_client_id()
    assert globus_web_auth_uses_builtin_client() is True
    assert is_globus_web_auth_configured("http://127.0.0.1:5000/globus/callback") is True


def test_web_auth_not_configured_on_non_local_without_env(monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.delenv("GLOBUS_CLIENT_ID", raising=False)
    assert is_globus_web_auth_configured("https://aidrin.example.org/globus/callback") is False


def test_web_auth_configured_with_client_id(monkeypatch):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    monkeypatch.setenv("GLOBUS_CLIENT_ID", "test-client-id")
    assert is_globus_web_auth_configured("https://aidrin.example.org/globus/callback") is True
    assert globus_web_auth_uses_builtin_client() is False
