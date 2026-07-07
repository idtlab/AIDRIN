import io


def _upload(client, names):
    files = [(io.BytesIO(b"a,b\n1,2\n3,4\n"), n) for n in names]
    return client.post("/inspector", data={"file": files},
                       content_type="multipart/form-data", follow_redirects=False)


def test_multi_upload_builds_list_and_activates_first(client):
    r = _upload(client, ["two.csv", "one.csv"])
    assert r.status_code == 302
    files = client.get("/files").get_json()
    assert {f["name"] for f in files["files"]} == {"one.csv", "two.csv"}
    assert files["active_file_id"] is not None
    # first NEW file by name is "one.csv" -> active
    active = next(f for f in files["files"] if f["id"] == files["active_file_id"])
    assert active["name"] == "one.csv"


def test_upload_infers_type_from_extension(client):
    _upload(client, ["data.csv"])
    f = client.get("/files").get_json()["files"][0]
    assert f["type"] == ".csv"


def test_single_file_upload_still_works(client):
    r = _upload(client, ["solo.csv"])
    assert r.status_code == 302
    files = client.get("/files").get_json()
    assert len(files["files"]) == 1
    assert files["active_file_id"] is not None


def test_globus_active_file_not_wiped_by_local_existence_check(app, client):
    from web.routes.utils import save_uploaded_files
    with app.test_request_context("/"):
        from flask import session
        session["user_id"] = "u-g"
        save_uploaded_files([{
            "id": "g1", "name": "r.csv", "type": ".csv",
            "path": "/remote/only/r.csv", "source": "globus", "endpoint_id": "ep",
        }])
    with client.session_transaction() as sess:
        sess["user_id"] = "u-g"
        sess["active_file_id"] = "g1"
        sess["uploaded_file_path"] = "/remote/only/r.csv"
        sess["uploaded_file_name"] = "r.csv"
        sess["uploaded_file_type"] = ".csv"
        sess["globus_file_path"] = "/remote/only/r.csv"
        sess["globus_file_name"] = "r.csv"
        sess["globus_file_type"] = ".csv"
        sess["globus_endpoint_id"] = "ep"
    r = client.get("/inspector")
    assert r.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("active_file_id") == "g1"
        assert sess.get("uploaded_file_path") == "/remote/only/r.csv"


def test_too_many_files_rejected(client, app):
    app.config["AIDRIN_MAX_UPLOAD_FILES"] = 2
    r = _upload(client, ["a.csv", "b.csv", "c.csv"])
    assert r.status_code == 400
    data = r.get_json()
    assert data and data["success"] is False
    assert "2" in data["message"] or "many" in data["message"].lower()


def test_under_file_limit_ok(client, app):
    app.config["AIDRIN_MAX_UPLOAD_FILES"] = 5
    r = _upload(client, ["a.csv", "b.csv"])
    assert r.status_code == 302


def test_unsupported_file_rejected_with_clear_message(client):
    import io as _io
    r = client.post(
        "/inspector",
        data={"file": [(_io.BytesIO(b"hello"), "notes.txt")]},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert r.status_code == 400
    data = r.get_json()
    assert data["success"] is False
    assert "unsupported" in data["message"].lower()
    assert "notes.txt" in data["message"]
    # nothing was saved into the file list
    assert client.get("/files").get_json()["files"] == []


def test_batch_with_one_unsupported_file_rejected(client):
    import io as _io
    r = client.post(
        "/inspector",
        data={"file": [
            (_io.BytesIO(b"a,b\n1,2\n"), "good.csv"),
            (_io.BytesIO(b"x"), "bad.txt"),
        ]},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert client.get("/files").get_json()["files"] == []


def test_multi_upload_lands_on_batch_overview(client):
    """A fresh multi-file upload renders the inspector landing on Batch Overview."""
    r = _upload(client, ["one.csv", "two.csv"])
    assert r.status_code == 302
    # the flag is set in the session by the upload POST
    with client.session_transaction() as sess:
        assert sess.get("land_on_batch") is True
    # ...and the next inspector render consumes it and emits the landing block.
    # Use the unique comment marker — the sidebar button also calls showPanel.
    marker = "surface the batch overview as the landing"
    html = client.get("/inspector").get_data(as_text=True)
    assert marker in html
    # flag is one-shot: a second render no longer lands on batch overview
    html2 = client.get("/inspector").get_data(as_text=True)
    assert marker not in html2


def test_single_upload_does_not_land_on_batch_overview(client):
    r = _upload(client, ["solo.csv"])
    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get("land_on_batch") is not True
    html = client.get("/inspector").get_data(as_text=True)
    assert "surface the batch overview as the landing" not in html
