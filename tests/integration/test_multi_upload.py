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
