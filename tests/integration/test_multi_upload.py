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
