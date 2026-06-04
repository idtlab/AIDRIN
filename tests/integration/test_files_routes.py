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


def test_cache_key_uses_active_file_id_not_display_name(app):
    from web.routes.utils import (
        save_uploaded_files, set_active_file, generate_metric_cache_key,
    )
    with app.test_request_context("/"):
        save_uploaded_files([
            {"id": "f1", "name": "dup.csv", "type": ".csv", "path": "/a/dup.csv", "source": "local"},
            {"id": "f2", "name": "dup.csv", "type": ".csv", "path": "/b/dup.csv", "source": "local"},
        ])
        set_active_file("f1")
        k1 = generate_metric_cache_key("dup.csv", "classimbalance", classes="y")
        set_active_file("f2")
        k2 = generate_metric_cache_key("dup.csv", "classimbalance", classes="y")
        assert k1 != k2  # same display name, different files -> different keys


def _seed(app, client, entries):
    from web.routes.utils import save_uploaded_files
    with client.session_transaction() as sess:
        sess["user_id"] = "u-test"
    with app.test_request_context("/"):
        from flask import session
        session["user_id"] = "u-test"
        save_uploaded_files(entries)


def test_files_list_and_activate(app, client):
    _seed(app, client, [
        {"id": "f1", "name": "a.csv", "type": ".csv", "path": "/a.csv", "source": "local"},
        {"id": "f2", "name": "b.csv", "type": ".csv", "path": "/b.csv", "source": "local"},
    ])
    r = client.get("/files")
    data = r.get_json()
    assert {f["id"] for f in data["files"]} == {"f1", "f2"}
    r = client.post("/files/f2/activate")
    assert r.get_json()["success"] is True
    with client.session_transaction() as sess:
        assert sess["active_file_id"] == "f2"


def test_files_activate_unknown_404(app, client):
    _seed(app, client, [])
    r = client.post("/files/nope/activate")
    assert r.status_code == 404


def test_files_remove_active_activates_next(app, client, tmp_path):
    p = tmp_path / "a.csv"; p.write_text("x\n1\n")
    _seed(app, client, [
        {"id": "f1", "name": "a.csv", "type": ".csv", "path": str(p), "source": "local"},
        {"id": "f2", "name": "b.csv", "type": ".csv", "path": "/b.csv", "source": "local"},
    ])
    client.post("/files/f1/activate")
    r = client.post("/files/f1/remove")
    assert r.get_json()["success"] is True
    with client.session_transaction() as sess:
        assert sess["active_file_id"] == "f2"
    assert not p.exists()


def test_files_summary_local(app, client, tmp_path):
    a = tmp_path / "a.csv"; a.write_text("x,y\n1,2\n3,4\n")
    _seed(app, client, [
        {"id": "f1", "name": "a.csv", "type": ".csv", "path": str(a), "source": "local"},
    ])
    r = client.get("/files/summary")
    data = r.get_json()
    assert data["totals"]["file_count"] == 1
    row = data["files"][0]
    assert row["records"] == 2 and row["features"] == 2
    assert row["source"] == "local"
    assert row["id"] == "f1"
    assert "completeness" not in row


def test_files_summary_mixed_local_globus(app, client, tmp_path):
    a = tmp_path / "a.csv"; a.write_text("x\n1\n")
    _seed(app, client, [
        {"id": "f1", "name": "a.csv", "type": ".csv", "path": str(a), "source": "local"},
        {"id": "g1", "name": "r.csv", "type": ".csv", "path": "/remote/r.csv",
         "source": "globus", "endpoint_id": "ep"},
    ])
    data = client.get("/files/summary").get_json()
    assert data["totals"]["file_count"] == 2
    assert data["totals"]["by_source"] == {"local": 1, "globus": 1}
    g = next(f for f in data["files"] if f["id"] == "g1")
    assert g["source"] == "globus"
    assert g["records"] is None and g["features"] is None
    assert g["status"] == "remote"
