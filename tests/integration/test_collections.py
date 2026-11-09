"""Collection upload, selection and execution across Flask session boundaries."""

import io

import pytest


def upload(client, names=("a.csv", "a.csv")):
    response = client.post("/collections/files", data={
        "file": [(io.BytesIO(b"sensor,t,value\nA,0.0,1\nA,0.01,1\n"), name) for name in names],
    }, content_type="multipart/form-data")
    assert response.status_code == 200
    return response.get_json()["files"]


def test_selected_subset_order_and_modes_reach_the_same_engine(client):
    assert client.get("/collections").status_code == 200
    files = upload(client, ("same.csv", "same.csv", "exclude.csv"))
    assert files[0]["id"] != files[1]["id"]
    assert all("path" not in member for member in files)
    selected = [files[1]["id"], files[0]["id"]]
    payload = {"file_ids": selected, "mode": "independent", "metrics": [{"name": "duplicity"}]}
    independent = client.post("/collections/run", json=payload)
    assert independent.status_code == 200
    assert [dataset["sources"][0]["id"] for dataset in independent.get_json()["datasets"]] == selected
    payload["mode"] = "stacked"
    stacked = client.post("/collections/run", json=payload).get_json()
    assert stacked["summary"]["datasets"] == 1
    assert [source["id"] for source in stacked["datasets"][0]["sources"]] == selected
    assert stacked["datasets"][0]["metrics"]["duplicity"]["Duplicity scores"]["Overall duplicity of the dataset"] == .5


def test_sequence_boundary_choice_and_unrelated_upload_loader(client):
    files = upload(client)
    with client.session_transaction() as session:
        session["custom_loader_spec"] = "/private/unrelated/loader.py:load"
        previous = dict(session)
    metric = {"name": "grouped_time_series", "source_columns": ["__aidrin_source_id"],
              "parameters": {"group_columns": ["__aidrin_source_id", "sensor"], "timestamp_column": "t", "expected_cadence": .01}}
    payload = {"file_ids": [member["id"] for member in files], "mode": "stacked", "metrics": [metric]}
    response = client.post("/collections/run", json=payload)
    assert response.status_code == 200
    result = response.get_json()["datasets"][0]["metrics"]["grouped_time_series"]
    assert result["summary"]["group_count"] == 2
    assert result["summary"]["finding_counts"] == {}
    metric["source_columns"] = []
    metric["parameters"]["group_columns"] = ["sensor"]
    result = client.post("/collections/run", json=payload).get_json()["datasets"][0]["metrics"]["grouped_time_series"]
    assert result["summary"]["finding_counts"] == {"duplicate_time": 2, "out_of_order": 1}
    with client.session_transaction() as session:
        assert dict(session) == previous


def test_another_session_cannot_select_inputs_or_supply_paths(client, app):
    files = upload(client)
    other = app.test_client()
    payload = {"file_ids": [files[0]["id"]], "metrics": [{"name": "duplicity"}]}
    response = other.post("/collections/run", json=payload)
    assert response.status_code == 400
    assert "not in this session" in response.get_json()["error"]
    payload["files"] = [{"path": "/etc/passwd", "id": "x"}]
    assert client.post("/collections/run", json=payload).status_code == 400


def test_confined_stored_paths_and_missing_files_are_not_silently_dropped(client, tmp_path):
    import json

    files = upload(client)
    with client.session_transaction() as session:
        manifest = session["collection_manifest"]
    with open(manifest) as handle:
        entries = json.load(handle)
    from pathlib import Path

    Path(entries[0]["path"]).unlink()
    payload = {"file_ids": [member["id"] for member in files], "metrics": [{"name": "duplicity"}]}
    response = client.post("/collections/run", json=payload)
    assert response.get_json()["summary"]["datasets_with_errors"] == 1
    payload["mode"] = "stacked"
    assert client.post("/collections/run", json=payload).status_code == 400
    entries[0]["path"] = str(tmp_path / "outside.csv")
    with open(manifest, "w") as handle:
        json.dump(entries, handle)
    assert client.post("/collections/run", json=payload).status_code == 400


def test_failed_upload_preserves_inventory_and_count_limit(client, app, monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "1")
    files = upload(client)
    before = set(Path(app.config["UPLOAD_FOLDER"]).iterdir())
    response = client.post("/collections/files", data={
        "file": [(io.BytesIO(b"x\n1\n"), "new.csv"), (io.BytesIO(b"not a table"), "unknown.bin")],
    }, content_type="multipart/form-data")
    assert response.status_code == 400
    assert client.get("/collections/files").get_json()["files"] == files
    assert set(Path(app.config["UPLOAD_FOLDER"]).iterdir()) == before
    response = client.post("/collections/files", data={"file": (io.BytesIO(b"x\n"), "empty.csv")}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert set(Path(app.config["UPLOAD_FOLDER"]).iterdir()) == before

    app.config["AIDRIN_MAX_UPLOAD_FILES"] = 2
    response = client.post("/collections/files", data={"file": (io.BytesIO(b"x\n1\n"), "extra.csv")}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert client.get("/collections/files").get_json()["files"] == files


def test_clear_collection_preserves_other_workspace_uploads(uploaded_client, app, monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "1")
    upload(uploaded_client)
    with uploaded_client.session_transaction() as session:
        workspace_path = session["uploaded_file_path"]
    collection_paths = set(Path(app.config["UPLOAD_FOLDER"]).iterdir()) - {Path(workspace_path)}
    assert uploaded_client.post("/collections/clear").status_code == 200
    assert Path(workspace_path).is_file()
    assert all(not Path(path).exists() for path in collection_paths)
    assert uploaded_client.get("/collections/files").get_json()["files"] == []


def test_many_files_keep_inventory_out_of_cookies_and_clear_with_session(client, app):
    from pathlib import Path

    files = upload(client, tuple(f"{index}.csv" for index in range(20)))
    with client.session_transaction() as session:
        assert set(session) == {"collection_manifest"}
    assert len(files) == 20
    assert client.post("/clear").status_code == 302
    assert client.get("/collections/files").get_json()["files"] == []
    assert not list(Path(app.config["UPLOAD_FOLDER"]).iterdir())


@pytest.mark.parametrize("ids", [[], ["unknown"], ["same", "same"], [1]])
def test_invalid_selection_fails_before_metric_execution(client, ids):
    assert client.post("/collections/run", json={"file_ids": ids, "metrics": [{"name": "duplicity"}]}).status_code == 400
