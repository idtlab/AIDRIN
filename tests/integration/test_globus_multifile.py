"""Tests that a Globus file selection (via /globus/submit) feeds the shared file list.

This test patches the Globus SDK availability flag so the blueprint is registered
even in environments where globus-compute-sdk is not installed, and mocks the
external Globus calls so no real endpoint is needed.
"""

from unittest.mock import MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def globus_app():
    """Flask app with the Globus blueprint force-registered via patching."""
    import web.globus as _globus_mod
    # Patch the availability flag at the module level BEFORE create_app() calls
    # register_blueprints(), which checks is_globus_available() at import time.
    _orig = _globus_mod._globus_available
    _globus_mod._globus_available = True
    try:
        from web import create_app
        app = create_app()
        app.config.update(TESTING=True)
        app.config["CELERY"]["task_always_eager"] = True
        app.config["CELERY"]["task_eager_propagates"] = True
        yield app
    finally:
        _globus_mod._globus_available = _orig


@pytest.fixture
def globus_client(globus_app):
    """Test client for the app with the Globus blueprint registered."""
    return globus_app.test_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_globus_auth(client):
    """Set session state that the /globus/submit route requires."""
    with client.session_transaction() as sess:
        sess["globus_authenticated"] = True
        sess["globus_tokens"] = {"fake_rs": {"access_token": "tok"}}


def _get_uploaded_files_via_route(client):
    """Return the file list from the /files endpoint."""
    r = client.get("/files")
    assert r.status_code == 200
    return r.get_json()


# ---------------------------------------------------------------------------
# The actual test (must FAIL before implementation, PASS after)
# ---------------------------------------------------------------------------


def test_globus_submit_appends_to_file_list(globus_client):
    """POSTing to /globus/submit should add the file to the shared file list
    and mark it as the active file.
    """
    client = globus_client

    # Arrange: authenticate and mock Globus SDK calls
    _set_globus_auth(client)

    mock_client = MagicMock()
    fake_task_id = "task-abc-123"

    with patch("web.routes.globus.get_compute_client", return_value=mock_client), \
         patch("web.routes.globus.submit_metric", return_value=fake_task_id):
        # Act: call the submit route with a sample Globus file selection
        response = client.post(
            "/globus/submit",
            json={
                "endpoint_id": "ep-test-uuid",
                "file_path": "/remote/data/sample.csv",
                "file_name": "sample.csv",
                "file_type": ".csv",
                "metric_name": "completeness",
            },
        )

    # The route should still succeed (task submitted)
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.get_json()
    assert data.get("task_id") == fake_task_id

    # Assert: the file now appears in GET /files with source="globus"
    # (GET /files only exposes id, name, type, source — path/endpoint_id are
    # server-side only; we verify those via get_uploaded_files() below)
    files_data = _get_uploaded_files_via_route(client)
    file_list = files_data["files"]
    globus_files = [f for f in file_list if f.get("source") == "globus"]
    assert len(globus_files) >= 1, (
        f"Expected at least one globus file in /files, got: {file_list}"
    )
    public_entry = globus_files[0]
    assert public_entry["name"] == "sample.csv"
    assert public_entry["type"] == ".csv"
    assert public_entry["source"] == "globus"

    # Verify full entry (path, endpoint_id) via the server-side helper
    from web.routes.utils import get_uploaded_files
    with globus_client.application.test_request_context("/"):
        # We need the same user_id as the test session to read the right cache key
        from flask import session as _sess
        with globus_client.session_transaction() as s:
            _sess["user_id"] = s.get("user_id")
        all_entries = get_uploaded_files()
    globus_entries = [e for e in all_entries if e.get("source") == "globus"]
    assert len(globus_entries) >= 1
    full_entry = globus_entries[0]
    assert full_entry["path"] == "/remote/data/sample.csv"
    assert full_entry.get("endpoint_id") == "ep-test-uuid"

    # Assert: the file is the active file
    active_id = files_data.get("active_file_id")
    assert active_id == public_entry["id"], (
        f"Expected active_file_id={public_entry['id']!r}, got {active_id!r}"
    )


def test_globus_submit_sets_legacy_session_keys(globus_client):
    """After /globus/submit, the globus_file_* session keys should still be set
    (set_active_file repopulates them; existing Globus code that reads those keys
    keeps working).
    """
    client = globus_client
    _set_globus_auth(client)

    mock_client = MagicMock()
    with patch("web.routes.globus.get_compute_client", return_value=mock_client), \
         patch("web.routes.globus.submit_metric", return_value="task-xyz"):
        client.post(
            "/globus/submit",
            json={
                "endpoint_id": "ep-456",
                "file_path": "/remote/other.parquet",
                "file_name": "other.parquet",
                "file_type": ".parquet",
                "metric_name": "completeness",
            },
        )

    with client.session_transaction() as sess:
        assert sess.get("globus_file_path") == "/remote/other.parquet"
        assert sess.get("globus_file_name") == "other.parquet"
        assert sess.get("globus_file_type") == ".parquet"
        assert sess.get("globus_endpoint_id") == "ep-456"


# ---------------------------------------------------------------------------
# /globus/add-files — file or directory, server-side type inference
# ---------------------------------------------------------------------------


def _add_files(client, path, files_result, endpoint="ep-dir"):
    """POST /globus/add-files with the remote listing mocked to files_result."""
    with patch("web.routes.globus.get_compute_client", return_value=MagicMock()), \
         patch("web.routes.globus.submit_list_files", return_value="list-task"), \
         patch("web.routes.globus.check_task",
               return_value={"status": "completed", "result": {"files": files_result}}):
        return client.post(
            "/globus/add-files", json={"endpoint_id": endpoint, "path": path}
        )


def test_globus_add_directory_adds_supported_skips_others(globus_client):
    client = globus_client
    _set_globus_auth(client)
    r = _add_files(client, "/remote/data/", [
        "/remote/data/a.csv",
        "/remote/data/b.json",
        "/remote/data/notes.txt",  # unsupported -> skipped
    ])
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    assert set(data["added"]) == {"a.csv", "b.json"}
    assert data["skipped"] == ["notes.txt"]
    files = client.get("/files").get_json()
    names = {f["name"]: f["type"] for f in files["files"]}
    assert names == {"a.csv": ".csv", "b.json": ".json"}  # types inferred
    assert files["active_file_id"] == data["active_file_id"]


def test_globus_add_single_file(globus_client):
    client = globus_client
    _set_globus_auth(client)
    r = _add_files(client, "/remote/data/x.csv", ["/remote/data/x.csv"])
    assert r.status_code == 200
    assert r.get_json()["added"] == ["x.csv"]
    files = client.get("/files").get_json()["files"]
    assert [f["name"] for f in files] == ["x.csv"]


def test_globus_add_all_unsupported_errors(globus_client):
    client = globus_client
    _set_globus_auth(client)
    r = _add_files(client, "/remote/data/", ["/remote/a.txt", "/remote/b.bin"])
    assert r.status_code == 400
    assert "supported" in r.get_json()["error"].lower()
    assert client.get("/files").get_json()["files"] == []


def test_globus_add_requires_auth(globus_client):
    r = globus_client.post(
        "/globus/add-files", json={"endpoint_id": "e", "path": "/p"}
    )
    assert r.status_code == 401


def test_remote_list_files_operation(tmp_path):
    """The __list_files__ op of remote_metric_runner lists files (stdlib only)."""
    from web.globus import remote_metric_runner
    (tmp_path / "a.csv").write_text("x")
    (tmp_path / "b.json").write_text("x")
    (tmp_path / "sub").mkdir()  # subdirectory excluded (non-recursive)
    out = remote_metric_runner("__list_files__", str(tmp_path), "", "")
    assert sorted(p.split("/")[-1] for p in out["files"]) == ["a.csv", "b.json"]
    one = remote_metric_runner("__list_files__", str(tmp_path / "a.csv"), "", "")
    assert one["files"] == [str(tmp_path / "a.csv")]
    assert "error" in remote_metric_runner("__list_files__", "/no/such/path", "", "")
