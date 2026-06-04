"""Tests for the server-side file list and active-file shim (Task 3)."""


def test_set_active_file_mirrors_legacy_keys(app):
    from web.routes.utils import (
        save_uploaded_files, set_active_file, get_uploaded_files,
    )
    with app.test_request_context("/"):
        from flask import session
        save_uploaded_files([
            {"id": "f1", "name": "a.csv", "type": ".csv",
             "path": "/tmp/a.csv", "source": "local"},
            {"id": "f2", "name": "b.csv", "type": ".csv",
             "path": "/tmp/b.csv", "source": "local"},
        ])
        ok = set_active_file("f2")
        assert ok is True
        assert session["active_file_id"] == "f2"
        assert session["uploaded_file_path"] == "/tmp/b.csv"
        assert session["uploaded_file_name"] == "b.csv"
        assert session["uploaded_file_type"] == ".csv"
        assert len(get_uploaded_files()) == 2


def test_set_active_globus_mirrors_globus_keys(app):
    from web.routes.utils import save_uploaded_files, set_active_file
    with app.test_request_context("/"):
        from flask import session
        save_uploaded_files([
            {"id": "g1", "name": "r.csv", "type": ".csv",
             "path": "/remote/r.csv", "source": "globus",
             "endpoint_id": "ep-123"},
        ])
        set_active_file("g1")
        assert session["uploaded_file_path"] == "/remote/r.csv"
        assert session["globus_file_path"] == "/remote/r.csv"
        assert session["globus_file_name"] == "r.csv"
        assert session["globus_file_type"] == ".csv"
        assert session["globus_endpoint_id"] == "ep-123"


def test_set_active_local_clears_globus_keys(app):
    from web.routes.utils import save_uploaded_files, set_active_file
    with app.test_request_context("/"):
        from flask import session
        session["globus_file_path"] = "/old/remote.csv"
        save_uploaded_files([
            {"id": "f1", "name": "a.csv", "type": ".csv",
             "path": "/tmp/a.csv", "source": "local"},
        ])
        set_active_file("f1")
        assert "globus_file_path" not in session


def test_set_active_unknown_id_returns_false(app):
    from web.routes.utils import save_uploaded_files, set_active_file
    with app.test_request_context("/"):
        save_uploaded_files([])
        assert set_active_file("nope") is False
