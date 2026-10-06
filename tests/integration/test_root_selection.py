"""Exercise ROOT tree selection with real uploaded TTrees."""

import numpy as np
import pytest

from aidrin.file_handling.file_parser import read_file
from web.routes.utils import build_file_info

uproot = pytest.importorskip("uproot")


def upload_root(client, tmp_path, multi=True):
    path = tmp_path / "trees.root"
    with uproot.recreate(path) as handle:
        handle.mktree("events", {"energy": np.array([1., 2., 3.])})
        if multi:
            handle.mktree("nested/meta", {"run": np.array([10., 20.])})
    with path.open("rb") as source:
        response = client.post("/inspector", data={
            "file": (source, "trees.root"), "fileTypeSelector": ".root",
        })
    assert response.status_code == 302


def test_root_picker_and_metrics(client, app, tmp_path):
    upload_root(client, tmp_path)
    picker = client.get("/summary-statistics").get_json()
    assert picker["needs_dataset_selection"]
    assert picker["file_type"] == ".root"
    assert [ds["path"] for ds in picker["datasets"]] == ["events", "nested/meta"]
    assert picker["datasets"][0]["shape"] == [3, 1]
    assert client.post("/filter-file", json={"keys": ["events"]}).get_json()["success"]
    summary = client.get("/summary-statistics").get_json()
    assert summary["success"]
    assert summary["records_count"] == 3
    assert summary["root_tree_selected"]
    assert summary["selected_dataset_keys"] == ["events"]
    assert summary["summary_statistics"]["energy"]["mean"] == 2
    assert client.post("/feature-set").get_json()["success"]
    result = client.post("/data-quality?return_type=json", data={"completeness": "yes"}).get_json()
    assert "Completeness" in result
    assert "energy" in str(result)
    assert "Error" not in result["Completeness"]
    # Worker payload keeps the selection after leaving the request context.
    with client.session_transaction() as sess:
        stored = dict(sess)
    with app.test_request_context():
        from flask import session
        session.update(stored)
        info = build_file_info(stored["uploaded_file_path"], "trees.root", ".root")
    assert info[3] == ["events"]
    assert list(read_file(info).columns) == ["energy"]
    reset = client.post("/clear-dataset-selection").get_json()
    assert reset["needs_dataset_selection"]
    assert reset["file_type"] == ".root"
    assert reset["current_checked_keys"] == ["events"]
    assert client.get("/summary-statistics").get_json()["needs_dataset_selection"]
    client.post("/filter-file", json={"keys": ["nested/meta"]})
    changed = client.get("/summary-statistics").get_json()
    assert changed["records_count"] == 2
    assert changed["numerical_features"] == ["run"]
    assert changed["summary_statistics"]["run"]["mean"] == 15


def test_root_rejects_invalid_selection(client, tmp_path):
    upload_root(client, tmp_path)
    for keys in [["missing"], ["events", "nested/meta"], ["events", "events"], []]:
        response = client.post("/filter-file", json={"keys": keys})
        assert response.status_code == 400
        assert not response.get_json()["success"]
    with client.session_transaction() as sess:
        assert not sess.get("selected_keys")


def test_single_root_tree_loads_automatically(client, tmp_path):
    upload_root(client, tmp_path, multi=False)
    summary = client.get("/summary-statistics").get_json()
    assert summary["success"]
    assert summary["records_count"] == 3
    assert not summary.get("needs_dataset_selection")
