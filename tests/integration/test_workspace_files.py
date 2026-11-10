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
    import os
    import time
    from aidrin.compute.remote import remote_metric_runner
    from web.routes.globus import globus_bp
    from worker.tasks import prune_upload_folder

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
    monkeypatch.setattr("web.routes.globus._fresh_negotiation",
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
        manifest = session["collection_manifest"]
    old = time.time() - 3590
    os.utime(manifest, (old, old))
    assert [file["id"] for file in workspace(client)] == [local["id"], remote["id"]]
    prune_upload_folder(app.config["UPLOAD_FOLDER"], max_age_seconds=3600, now=time.time() + 20)
    assert [file["id"] for file in workspace(client)] == [local["id"], remote["id"]]
    assert client.post(f"/workspace/files/{remote['id']}/remove").status_code == 302
    assert source.is_file()
    assert [file["id"] for file in workspace(client)] == [local["id"]]
    assert client.get("/retrieve-uploaded-file").data == b"x\n5\n"


def test_workspace_tab_and_cache_are_scoped_to_active_id(client, app):
    upload(client, ("same.csv", b"x\n1\n1\n"), ("same.csv", b"x\n1\n2\n"))
    first, second = workspace(client)
    page = client.get("/inspector").get_data(as_text=True)
    assert f'data-workspace-file-id="{first["id"]}"' in page
    stale_header = {"X-AIDRIN-Workspace-File": first["id"]}
    assert duplicity(data_quality(client, duplicity="yes")["Duplicity"]) == .5
    old_worker_cache = dict(app.TEMP_RESULTS_CACHE)
    assert client.post("/inspector", data={"active_file_id": second["id"]}).status_code == 302
    app.TEMP_RESULTS_CACHE.update(old_worker_cache)  # Another worker did not see the switch.
    assert client.get("/cached-result/data_quality").json == {"cached": False}

    response = client.post("/data-quality?return_type=json", data={"duplicity": "yes"}, headers=stale_header)
    assert response.status_code == 409
    assert response.headers["X-AIDRIN-Workspace-Stale"] == "1"
    assert client.get("/readiness-report/pdf", headers=stale_header).status_code == 409
    response = client.post("/data-quality?return_type=json", data={"duplicity": "yes"},
                           headers={"X-AIDRIN-Workspace-File": second["id"]})
    assert duplicity(response.json["Duplicity"]) == 0


def test_active_hdf5_selection_is_ignored_by_collection_and_batch_overview(client, tmp_path):
    h5py = pytest.importorskip("h5py")
    files = []
    for name, values in (("a.h5", [1, 1]), ("b.h5", [1, 2])):
        path = tmp_path / name
        with h5py.File(path, "w") as handle:
            handle["x"] = values
            handle["y"] = [2, 3, 4]
        files.append((name, path.read_bytes()))
    files.append(("c.csv", b"x\n1\n2\n"))
    upload(client, *files)
    _, second, third = workspace(client)
    assert client.post("/filter-file", json={"keys": ["x"]}).json["success"]
    assert duplicity(data_quality(client, duplicity="yes")["Duplicity"]) == .5
    assert workspace(client)[1]["error"]
    result = data_quality(client, duplicity="yes", collection_scope="selected",
                          collection_file_id=[second["id"], third["id"]])["Cross-file Data Quality"]
    assert [dataset["status"] for dataset in result["datasets"]] == ["error", "ok"]


def test_expired_uploads_do_not_block_replacement(client, app):
    import json
    from pathlib import Path

    app.config["AIDRIN_MAX_UPLOAD_FILES"] = 2
    upload(client, ("expired.csv", b"x\n1\n"), ("kept.csv", b"x\n2\n"))
    with client.session_transaction() as session:
        manifest = Path(session["collection_manifest"])
    Path(json.loads(manifest.read_text(encoding="utf-8"))[0]["path"]).unlink()
    assert upload(client, ("new.csv", b"x\n3\n")).status_code == 302
    assert [row["name"] for row in workspace(client)] == ["kept.csv", "new.csv"]


def test_globus_directory_capability_is_refreshed_and_reserved(client, app, monkeypatch):
    from web.routes.globus import globus_bp

    if globus_bp.name not in app.blueprints:
        app.register_blueprint(globus_bp)
    calls = []
    with client.session_transaction() as session:
        session["globus_authenticated"] = True
        session["globus_endpoint_negotiation"] = {"endpoint_id": "endpoint", "checked_at": 0, "capabilities": []}
    monkeypatch.setattr("web.routes.globus.get_compute_client", lambda tokens: object())

    def probe(*args):
        calls.append("probe")
        return {"compatible": True, "remote": {"capabilities": ["workspace_directory_v1"]}}

    def submit(*args, **kwargs):
        calls.append(kwargs["limit"])
        return "directory-task"

    monkeypatch.setattr("web.routes.globus.check_endpoint_compatibility", probe)
    monkeypatch.setattr("web.routes.globus.submit_metric", submit)
    data = {"endpoint_id": "endpoint", "file_path": "/remote", "file_type": ".csv", "metric_name": "workspace_directory"}
    assert client.post("/globus/submit", json=data).status_code == 400
    assert calls == []
    assert client.post("/globus/import-directory", json={"endpoint_id": "endpoint", "directory": "/remote"}).status_code == 200
    assert calls == ["probe", 50]


def test_cached_collection_expires_when_another_worker_removes_a_file(client, app):
    upload(client, ("a.csv", b"x\n1\n"), ("b.csv", b"x\n2\n"))
    first, second = workspace(client)
    header = {"X-AIDRIN-Workspace-File": first["id"]}
    data_quality(client, duplicity="yes", collection_scope="all", collection_mode="stacked")
    assert client.get("/cached-result/data_quality", headers=header).json["cached"]
    old_worker_cache = dict(app.TEMP_RESULTS_CACHE)
    assert client.post(f"/workspace/files/{second['id']}/remove").status_code == 302
    app.TEMP_RESULTS_CACHE.update(old_worker_cache)
    assert client.get("/cached-result/data_quality", headers=header).json == {"cached": False}
