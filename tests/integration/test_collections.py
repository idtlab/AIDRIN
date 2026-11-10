"""Multi-file uploads and grouped analysis in the standard Inspector workflow."""

import io
import json
from pathlib import Path

import pytest


def upload(client, *files):
    return client.post("/inspector", data={
        "fileTypeSelector": ".csv",
        "file": [(io.BytesIO(content), name) for name, content in files],
    }, content_type="multipart/form-data")


def inventory(client):
    with client.session_transaction() as session:
        return json.loads(Path(session["collection_manifest"]).read_text(encoding="utf-8"))


def run_grouped(client, ids, mode="independent", **fields):
    data = {
        "grouped time series": "yes",
        "collection_scope": "selected",
        "collection_file_id": ids,
        "collection_mode": mode,
        "grouped_file_boundaries": "yes",
        "timestamp column for grouped time series": "t",
        "cadence for grouped time series": ".01",
        **fields,
    }
    return client.post("/data-quality?return_type=json", data=data).get_json()


CLEAN = b"sensor,t,value\nA,0.0,1\nA,0.01,1\n"
GAP = b"sensor,t,value\nA,0.0,3\nA,0.02,4\n"


def test_main_uploader_and_existing_data_quality_route_use_selected_files(client):
    landing = client.get("/inspector").get_data(as_text=True)
    assert 'type="file" class="hidden" multiple required' in landing
    assert upload(client, ("same.csv", CLEAN), ("same.csv", GAP), ("exclude.csv", CLEAN)).status_code == 302
    first, second, excluded = inventory(client)
    assert first["id"] != second["id"]
    page = client.get("/inspector").get_data(as_text=True)
    assert "Upload more files" in page
    assert 'id="collection-scope"' in page
    assert client.get("/collections").status_code == 404

    ids = [second["id"], first["id"]]
    response = run_grouped(client, ids, completeness="yes")
    completeness = response["Cross-file Data Quality"]
    assert [source["id"] for source in completeness["selection"]] == ids
    assert all("completeness" in dataset["metrics"] for dataset in completeness["datasets"])
    independent = response["Grouped Time Series"]
    assert [item["id"] for item in independent["selection"]] == ids
    assert [d["metrics"]["grouped_time_series"]["summary"]["finding_counts"]
            for d in independent["datasets"]] == [{"cadence_gap": 1}, {}]

    stacked = run_grouped(client, ids, mode="stacked")["Grouped Time Series"]
    assert stacked["summary"] == {"selected_files": 2, "datasets": 1, "datasets_with_errors": 0}
    dataset = stacked["datasets"][0]
    assert [(source["id"], source["start_row"]) for source in dataset["sources"]] == [(ids[0], 0), (ids[1], 2)]
    assert dataset["metrics"]["grouped_time_series"]["summary"]["finding_counts"] == {"cadence_gap": 1}
    assert excluded["id"] not in {source["id"] for source in dataset["sources"]}

    with client.session_transaction() as session:
        assert session["uploaded_file_path"] == first["path"]
    cached = client.get("/cached-result/data_quality").get_json()
    assert cached["data"]["Grouped Time Series"] == stacked


def test_upload_more_and_open_active_file_use_the_same_workspace(client):
    assert upload(client, ("clean.csv", CLEAN)).status_code == 302
    with client.session_transaction() as session:
        first_path = session["uploaded_file_path"]
    upload_view = client.get("/inspector?upload=1").get_data(as_text=True)
    assert 'id="uploadForm"' in upload_view and "Back to workspace" in upload_view
    assert upload(client, ("gap.csv", GAP)).status_code == 302
    first = inventory(client)[0]
    assert first["path"] == first_path
    assert client.post("/inspector", data={"active_file_id": first["id"]}).status_code == 302
    assert client.get("/retrieve-uploaded-file").data == CLEAN

    result = client.post("/data-quality?return_type=json", data={
        "grouped time series": "yes",
        "group columns for grouped time series": "sensor",
        "timestamp column for grouped time series": "t",
        "cadence for grouped time series": ".01",
    }).get_json()["Grouped Time Series"]
    assert result["format"] == "aidrin.grouped-time-series"
    assert result["summary"]["finding_counts"] == {}


def test_all_uploaded_files_uses_the_complete_workspace_and_keeps_stack_order(client):
    regular = b"t,value\n0,1\n.01,2\n.02,3\n"
    assert upload(client, ("first.csv", regular), ("second.csv", regular), ("third.csv", regular)).status_code == 302
    ids = [entry["id"] for entry in inventory(client)]
    result = run_grouped(client, [], collection_scope="all", grouped_series="file")["Grouped Time Series"]
    assert result["mode"] == "independent"
    assert [source["id"] for source in result["selection"]] == ids
    assert len(result["datasets"]) == 3

    preview = client.post("/data-quality", data={
        "action": "detect_grouped_timing", "collection_scope": "all", "grouped_series": "file",
        "timestamp column for grouped time series": "t",
    }).get_json()
    assert preview == {"time_kind": "numeric", "interval": .01, "sampled_files": 3, "total_files": 3}

    order = ids[::-1]
    stacked = run_grouped(client, [], mode="stacked", collection_scope="all", grouped_series="file",
                          collection_file_order=order)["Grouped Time Series"]
    assert [(source["id"], source["start_row"]) for source in stacked["datasets"][0]["sources"]] == list(zip(order, [0, 3, 6]))
    stale = run_grouped(client, [], collection_scope="all", grouped_series="file",
                        collection_file_order=ids[:-1])["Grouped Time Series"]
    assert "Reload the Inspector" in stale["Error"]


@pytest.mark.parametrize("continue_value, findings", [
    ("", {}),
    ("no", {"duplicate_time": 2, "out_of_order": 1}),
])
def test_cross_file_boundaries_are_explicit_and_scoped_to_grouped_check(client, continue_value, findings):
    upload(client, ("a.csv", CLEAN), ("b.csv", CLEAN))
    ids = [entry["id"] for entry in inventory(client)]
    separate = run_grouped(client, ids, mode="stacked")["Grouped Time Series"]
    assert separate["datasets"][0]["metrics"]["grouped_time_series"]["summary"]["finding_counts"] == {}
    together = run_grouped(client, ids, mode="stacked", **{
        "grouped_file_boundaries": continue_value,
        "group columns for grouped time series": "sensor",
    })["Grouped Time Series"]
    summary = together["datasets"][0]["metrics"]["grouped_time_series"]["summary"]
    assert summary["finding_counts"] == findings
    assert client.get("/retrieve-uploaded-file").data == CLEAN


def test_one_series_per_file_keeps_boundaries_in_both_collection_modes(client):
    clean = b"t,value\n0,1\n.01,2\n"
    upload(client, ("a.csv", clean), ("b.csv", clean))
    ids = [entry["id"] for entry in inventory(client)]
    for mode, expected_groups in [("independent", [1, 1]), ("stacked", [2])]:
        result = run_grouped(client, ids, mode=mode, grouped_series="file", grouped_file_boundaries="")
        audits = [dataset["metrics"]["grouped_time_series"] for dataset in result["Grouped Time Series"]["datasets"]]
        assert [audit["summary"]["group_count"] for audit in audits] == expected_groups
        assert all(audit["summary"]["finding_counts"] == {} for audit in audits)


def test_independent_files_auto_detect_time_format_for_each_dataset(client):
    numeric = b"t,value\n0,1\n.01,2\n"
    datetime = b"t,value\n2026-01-01T00:00:00Z,1\n2026-01-01T00:00:00.02Z,2\n"
    assert upload(client, ("numeric.csv", numeric), ("datetime.csv", datetime)).status_code == 302
    ids = [entry["id"] for entry in inventory(client)]
    result = run_grouped(client, ids, grouped_series="file", **{"time kind for grouped time series": "auto"})
    audits = [dataset["metrics"]["grouped_time_series"] for dataset in result["Grouped Time Series"]["datasets"]]
    assert [audit["parameters"]["time_kind"] for audit in audits] == ["numeric", "datetime"]
    assert [audit["summary"]["finding_counts"] for audit in audits] == [{}, {"cadence_gap": 1}]


def test_interval_suggestion_samples_only_a_few_files_and_requires_agreement(client):
    common = b"t,value\n0,1\n.01,2\n.02,3\n"
    different = b"t,value\n0,1\n.02,2\n.04,3\n"
    files = [(f"{index}.csv", common) for index in range(8)] + [("different.csv", different)]
    assert upload(client, *files).status_code == 302
    ids = [entry["id"] for entry in inventory(client)]
    form = {"action": "suggest_grouped_interval", "collection_scope": "selected", "grouped_series": "file",
            "timestamp column for grouped time series": "t"}
    response = client.post("/data-quality", data={**form, "collection_file_id": ids[:-1]})
    assert response.status_code == 200
    assert response.get_json() == {"interval": .01, "time_kind": "numeric", "sampled_files": 6, "total_files": 8}
    response = client.post("/data-quality", data={**form, "collection_file_id": ids})
    assert response.status_code == 400
    assert "different intervals" in response.get_json()["error"]


def test_file_ids_are_session_owned(client, app):
    upload(client, ("a.csv", CLEAN), ("b.csv", GAP))
    foreign = app.test_client()
    file_id = inventory(client)[0]["id"]
    assert foreign.post("/inspector", data={"active_file_id": file_id}).status_code == 404
    assert "not in this workspace" in run_grouped(foreign, [file_id])["Grouped Time Series"]["Error"]
    assert "not in this workspace" in run_grouped(client, ["/etc/passwd"])["Grouped Time Series"]["Error"]


def test_missing_file_is_reported_for_selected_file_not_silently_skipped(client):
    upload(client, ("a.csv", CLEAN), ("b.csv", GAP))
    first, second = inventory(client)
    Path(second["path"]).unlink()
    ids = [first["id"], second["id"]]
    independent = run_grouped(client, ids)["Grouped Time Series"]
    assert [dataset["status"] for dataset in independent["datasets"]] == ["ok", "error"]
    assert "Error" in run_grouped(client, ids, mode="stacked")["Grouped Time Series"]


def test_failed_batch_leaves_existing_inventory_and_active_file(client, app):
    upload(client, ("a.csv", CLEAN), ("b.csv", GAP))
    files = inventory(client)
    before = set(Path(app.config["UPLOAD_FOLDER"]).iterdir())
    response = upload(client, ("new.csv", CLEAN), ("unknown.bin", b"not a table"))
    assert response.status_code == 302
    assert "Choose files matching the selected file type" in client.get(response.location).get_data(as_text=True)
    assert inventory(client) == files
    assert set(Path(app.config["UPLOAD_FOLDER"]).iterdir()) == before
    assert client.get("/retrieve-uploaded-file").data == CLEAN

    app.config["AIDRIN_MAX_UPLOAD_FILES"] = 2
    response = upload(client, ("extra.csv", GAP))
    assert "Workspace file limit: 2." in client.get(response.location).get_data(as_text=True)
    assert inventory(client) == files
    assert set(Path(app.config["UPLOAD_FOLDER"]).iterdir()) == before


def test_many_files_keep_inventory_off_cookie_and_clear_only_session_files(client, app, monkeypatch):
    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "1")
    other = app.test_client()
    upload(other, ("other.csv", CLEAN))
    other_files = set(Path(app.config["UPLOAD_FOLDER"]).iterdir())
    response = upload(client, *((f"{i}.csv", CLEAN) for i in range(20)))
    assert response.status_code == 302
    assert len(response.headers["Set-Cookie"]) < 4093
    entries = inventory(client)
    assert len(entries) == 20
    assert run_grouped(client, [entries[0]["id"]])["Grouped Time Series"]["summary"]["datasets_with_errors"] == 0
    assert client.post("/clear").status_code == 302
    assert set(Path(app.config["UPLOAD_FOLDER"]).iterdir()) == other_files
    assert other.get("/retrieve-uploaded-file").data == CLEAN


@pytest.mark.parametrize("ids", [[], ["unknown"], ["same", "same"]])
def test_invalid_selection_does_not_fall_back_to_active_file(client, ids):
    upload(client, ("a.csv", CLEAN))
    assert "Error" in run_grouped(client, ids)["Grouped Time Series"]



def test_grouped_and_existing_collection_checks_share_one_input_read(client, monkeypatch):
    from aidrin.file_handling.collection import CollectionMember

    upload(client, ("a.csv", CLEAN), ("b.csv", GAP))
    ids = [entry["id"] for entry in inventory(client)]
    reads = []
    load = CollectionMember.load

    def count_read(member):
        reads.append(member.id)
        return load(member)

    monkeypatch.setattr(CollectionMember, "load", count_read)
    result = run_grouped(client, ids, duplicity="yes")
    assert reads == ids
    grouped = result["Grouped Time Series"]
    ordinary = result["Cross-file Data Quality"]
    assert grouped["selection"] == ordinary["selection"]
    assert all(set(dataset["metrics"]) == {"grouped_time_series"} for dataset in grouped["datasets"])
    assert all(set(dataset["metrics"]) == {"duplicity"} for dataset in ordinary["datasets"])



def test_grouped_active_and_ordinary_checks_share_one_source_read(client, monkeypatch):
    from aidrin.file_handling.readers.csv_reader import csvReader

    upload(client, ("active.csv", CLEAN))
    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "0")
    read = csvReader.read
    paths = []

    def count_read(reader):
        paths.append(reader.file_path)
        return read(reader)

    monkeypatch.setattr(csvReader, "read", count_read)
    result = run_grouped(client, [], collection_scope="active", grouped_series="file",
                         completeness="yes", duplicity="yes", outliers="yes")
    assert len(paths) == 1
    assert set(result) == {"Grouped Time Series", "Completeness", "Duplicity", "Outliers"}
    assert result["Grouped Time Series"]["summary"]["finding_counts"] == {}


def test_grouped_column_choices_follow_selected_files_and_preserve_labels(client):
    content = b" station,t,value\n9007199254740992,0.0,1\n9007199254740992,0.01,1\n9007199254740993,0.0,1\n9007199254740993,0.02,1\n"
    upload(client, ("unrelated.csv", b"age,temperature\n10,12\n"), ("a.csv", content), ("b.csv", content))
    ids = [entry["id"] for entry in inventory(client)[1:]]
    assert "t" not in client.post("/feature-set").get_json()["grouped_columns"]
    preview = client.post("/data-quality", data={
        "action": "preview_grouped_columns", "collection_scope": "selected", "collection_file_id": ids,
    }).get_json()
    assert preview == {"columns": [" station", "t", "value"], "suggested_time_column": "t", "complete": True,
                       "previewed_files": 2, "total_files": 2}
    result = run_grouped(client, ids, grouped_series="columns", **{"group columns for grouped time series": [" station"]})
    for dataset in result["Grouped Time Series"]["datasets"]:
        groups = dataset["metrics"]["grouped_time_series"]["groups"]
        assert [group["group"][" station"] for group in groups] == [{"integer": "9007199254740992"}, {"integer": "9007199254740993"}]
        assert [group["finding_counts"] for group in groups] == [{}, {"cadence_gap": 1}]



def test_grouped_column_preview_uses_a_bounded_sample_and_keeps_readable_files(client):
    upload(client, *((f"{i}.csv", CLEAN) for i in range(7)))
    entries = inventory(client)
    form = {"action": "preview_grouped_columns", "collection_scope": "all"}
    result = client.post("/data-quality", data=form).get_json()
    assert result == {"columns": ["sensor", "t", "value"], "suggested_time_column": "t", "complete": False,
                      "previewed_files": 6, "total_files": 7}

    Path(entries[0]["path"]).unlink()
    response = client.post("/data-quality", data={**form, "collection_scope": "selected",
                                                  "collection_file_id": [entry["id"] for entry in entries[:2]]})
    assert response.status_code == 200
    assert response.get_json() == {"columns": ["sensor", "t", "value"], "suggested_time_column": None, "complete": False,
                                   "previewed_files": 1, "total_files": 2}
