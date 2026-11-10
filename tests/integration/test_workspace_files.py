"""Workspace and cross-file Data Quality behavior through the Inspector routes."""

import io

import pytest


def upload(client, *files):
    return client.post(
        "/inspector", data={"fileTypeSelector": "auto", "file": [(io.BytesIO(body), name) for name, body in files]},
        content_type="multipart/form-data",
    )


def workspace(client):
    return client.get("/workspace/summary").get_json()["files"]


def data_quality(client, **fields):
    return client.post("/data-quality?return_type=json", data=fields).get_json()


def duplicity(result):
    return result["Duplicity scores"]["Overall duplicity of the dataset"]


def test_single_file_checks_follow_the_active_file_across_uploads(client):
    assert upload(client, ("same.csv", b"x,y\n1,2\n1,2\n")).status_code == 302
    first = workspace(client)[0]
    selected = {"completeness": "yes", "duplicity": "yes", "outliers": "yes"}
    original = data_quality(client, **selected)
    assert set(original) == {"Completeness", "Duplicity", "Outliers"}
    assert duplicity(original["Duplicity"]) == .5

    assert upload(client, ("same.csv", b"x,y\n1,2\n3,4\n")).status_code == 302
    _, second = workspace(client)
    assert first["id"] != second["id"]
    assert duplicity(data_quality(client, **selected)["Duplicity"]) == 0
    assert client.post("/inspector", data={"active_file_id": first["id"]}).status_code == 302
    reopened = data_quality(client, **selected)
    assert reopened["Completeness"]["Completeness scores"] == original["Completeness"]["Completeness scores"]
    assert reopened["Outliers"]["Outlier scores"] == original["Outliers"]["Outlier scores"]
    assert duplicity(reopened["Duplicity"]) == .5


def test_mixed_upload_overview_and_session_scoped_removal(client, app):
    assert upload(client, ("a.csv", b"x,flag\n1,true\n2,false\n"), ("b.json", b'[{"x": 5, "flag": true}]')).status_code == 302
    first, second = workspace(client)
    assert [(row["name"], row["records"], row["numerical"], row["categorical"]) for row in (first, second)] == [
        ("a.csv", 2, 1, 1), ("b.json", 1, 1, 1),
    ]
    foreign = app.test_client()
    assert foreign.post(f"/workspace/files/{first['id']}/remove").status_code == 404
    assert client.post(f"/workspace/files/{first['id']}/remove").status_code == 302
    assert [row["id"] for row in workspace(client)] == [second["id"]]
    assert client.get("/retrieve-uploaded-file").data == b'[{"x": 5, "flag": true}]'
    assert client.post(f"/workspace/files/{second['id']}/remove").status_code == 302
    assert workspace(client) == []


@pytest.mark.parametrize("mode, expected", [("independent", 0), ("stacked", .25)])
def test_cross_file_data_quality_and_other_checks_use_different_scopes(client, mode, expected):
    assert upload(client, ("a.csv", b"x,y\n1,2\n2,3\n"), ("b.csv", b"x,y\n1,2\n8,9\n")).status_code == 302
    first, second = workspace(client)
    result = data_quality(client, **{
        "completeness": "yes", "duplicity": "yes", "outliers": "yes",
        "row level completeness": "yes", "required columns for row level completeness": "x",
        "collection_scope": "all", "collection_file_order": [second["id"], first["id"]], "collection_mode": mode,
    })
    assert result["Row-Level Completeness"]["Row-Level Completeness (%)"] == 100
    assert "Duplicity" not in result
    collection = result["Cross-file Data Quality"]
    assert [row["id"] for row in collection["selection"]] == [second["id"], first["id"]]
    assert all(set(dataset["metrics"]) == {"completeness", "duplicity", "outliers"} for dataset in collection["datasets"])
    assert all(duplicity(dataset["metrics"]["duplicity"]) == expected for dataset in collection["datasets"])


def test_invalid_or_stale_selection_does_not_use_active_file(client):
    upload(client, ("a.csv", b"x\n1\n"), ("b.csv", b"x\n2\n"))
    first, _ = workspace(client)
    for fields in (
        {"collection_scope": "selected", "collection_file_id": "unknown"},
        {"collection_scope": "all", "collection_file_order": first["id"]},
    ):
        result = data_quality(client, duplicity="yes", **fields)
        assert "Error" in result["Cross-file Data Quality"]
        assert "Duplicity" not in result


def test_globus_directory_import_shares_the_inventory_without_local_reads(client, app, monkeypatch, tmp_path):
    from aidrin.compute.remote import remote_metric_runner
    from web.routes.globus import globus_bp

    if globus_bp.name not in app.blueprints:
        app.register_blueprint(globus_bp)

    source = tmp_path / "remote.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")
    listing = remote_metric_runner("workspace_directory", str(tmp_path), "", "", limit=2)
    assert [entry["name"] for entry in listing["files"]] == ["remote.csv"]

    with client.session_transaction() as session:
        session["globus_authenticated"] = True
    monkeypatch.setattr("web.routes.globus.get_compute_client", lambda tokens: object())
    monkeypatch.setattr("web.routes.globus._submission_negotiation",
                        lambda *args: ({"capabilities": ["workspace_directory_v1"]}, {}))
    monkeypatch.setattr("web.routes.globus.submit_metric", lambda *args, **kwargs: "directory-task")
    monkeypatch.setattr("web.routes.globus.check_task", lambda *args: {"status": "completed", "result": listing})

    assert upload(client, ("local.csv", b"x\n5\n")).status_code == 302
    assert client.post("/globus/import-directory", json={"endpoint_id": "endpoint", "directory": "/remote"}).json["task_id"] == "directory-task"
    assert client.get("/globus/check-task/directory-task").json == {"status": "completed", "file_count": 1}
    local, remote = workspace(client)
    assert (remote["source"], remote["records"]) == ("globus", 1)
    with client.session_transaction() as session:
        assert session["globus_file_path"] == str(source)
        assert "uploaded_file_path" not in session
    assert client.post(f"/workspace/files/{remote['id']}/remove").status_code == 302
    assert source.is_file()
    assert [file["id"] for file in workspace(client)] == [local["id"]]
    assert client.get("/retrieve-uploaded-file").data == b"x\n5\n"
