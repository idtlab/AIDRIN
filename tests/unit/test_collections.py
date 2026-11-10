"""Behavior boundaries for the shared collection pilot, using synthetic inputs."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import io
import json
from unittest.mock import patch

import pandas as pd
import pytest

from aidrin.file_handling.collection import CollectionMember, load_collection_config
from aidrin.file_handling.file_parser import read_file, using_loaded_table
from aidrin.headless.api import METRIC_REGISTRY, run_collection_metrics


@pytest.fixture(autouse=True)
def no_source_sidecars(monkeypatch):
    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "0")


def members(tmp_path, frames):
    selection = []
    for index, frame in enumerate(frames):
        path = tmp_path / f"{index}.parquet"
        frame.to_parquet(path, index=False)
        # Display names deliberately collide; identity and ordering cannot use them.
        selection.append(CollectionMember(str(index), str(path), "same.parquet"))
    return selection


def test_provenance_does_not_hide_duplicates_or_inflate_completeness(tmp_path):
    files = members(tmp_path, [pd.DataFrame({"sensor": ["A", "A"], "t": [0., .01], "value": [1., None]})] * 2)
    result = run_collection_metrics(files, [{"name": "duplicity"}, {"name": "completeness"}], "stacked")
    dataset = result["datasets"][0]
    assert dataset["status"] == "ok"
    assert dataset["metrics"]["duplicity"]["Duplicity scores"]["Overall duplicity of the dataset"] == .5
    scores = dataset["metrics"]["completeness"]["Completeness scores"]
    assert set(scores) == {"sensor", "t", "value"}
    assert scores["value"] == .5
    assert dataset["sources"] == [
        {"id": "0", "name": "same.parquet", "start_row": 0, "row_count": 2},
        {"id": "1", "name": "same.parquet", "start_row": 2, "row_count": 2},
    ]


def test_stacking_aligns_column_order_but_refuses_name_and_dtype_mismatches(tmp_path):
    frames = [pd.DataFrame({"sensor": ["A"], "t": [0.]}), pd.DataFrame({"t": [.01], "sensor": ["A"]})]
    files = members(tmp_path, frames)
    assert run_collection_metrics(files, [{"name": "completeness"}], "stacked")["summary"]["datasets_with_errors"] == 0
    pd.DataFrame({"sensor": ["A"], "other": [.01]}).to_parquet(files[1].path)
    with pytest.raises(ValueError, match="same column names"):
        run_collection_metrics(files, [{"name": "duplicity"}], "stacked")
    pd.DataFrame({"sensor": ["A"], "t": [1]}).to_parquet(files[1].path)
    with pytest.raises(ValueError, match="same parsed column dtypes"):
        run_collection_metrics(files, [{"name": "duplicity"}], "stacked")


def test_input_failure_is_visible_and_does_not_silently_reduce_a_stack(tmp_path):
    files = members(tmp_path, [pd.DataFrame({"x": [1, 1]})])
    files.append(CollectionMember("missing", str(tmp_path / "missing.csv")))
    result = run_collection_metrics(files, [{"name": "duplicity"}])
    assert [dataset["status"] for dataset in result["datasets"]] == ["ok", "error"]
    assert result["summary"]["datasets_with_errors"] == 1
    assert "missing.csv" in result["datasets"][1]["errors"]["input"]
    with pytest.raises(ValueError, match="non-empty table"):
        run_collection_metrics(files, [{"name": "duplicity"}], "stacked")


def test_reserved_source_columns_and_duplicate_member_ids_are_rejected(tmp_path):
    files = members(tmp_path, [pd.DataFrame({"__aidrin_source_id": ["spoofed"], "x": [1]})])
    result = run_collection_metrics(files, [{"name": "duplicity"}])
    assert "reserved" in result["datasets"][0]["errors"]["input"]
    with pytest.raises(ValueError, match="unique"):
        run_collection_metrics(files * 2, [{"name": "duplicity"}])


def test_new_tabular_metric_only_needs_registry_opt_in(tmp_path, monkeypatch):
    # This metric already exists but is outside the pilot. Opting in via its
    # registry contract must work without a new branch in the executor.
    monkeypatch.setitem(METRIC_REGISTRY["row_level_completeness"], "collection_modes", ("independent", "stacked"))
    files = members(tmp_path, [pd.DataFrame({"x": [1., None]})] * 2)
    result = run_collection_metrics(files, [{"name": "row_level_completeness", "parameters": {"required_columns": ["x"]}}], "stacked")
    assert result["datasets"][0]["metrics"]["row_level_completeness"]["Row-Level Completeness (%)"] == 50.


def test_loaded_table_reads_are_private_nested_and_context_local():
    frame = pd.DataFrame({"x": [1]})
    with using_loaded_table(frame) as outer:
        private = read_file(outer)
        private.loc[0, "x"] = 99
        assert read_file(outer).loc[0, "x"] == 1
        with using_loaded_table(pd.DataFrame({"x": [2]})) as inner:
            assert read_file(inner).loc[0, "x"] == 2
        assert read_file(outer).loc[0, "x"] == 1
    assert read_file(outer) is None or isinstance(read_file(outer), str)

    def read(value):
        with using_loaded_table(pd.DataFrame({"x": [value]})) as info:
            return read_file(info).loc[0, "x"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(read, [3, 4])) == [3, 4]


@pytest.mark.parametrize("metric_request", [
    {"name": "variable_unit_validation"},
    {"name": "duplicity", "parameters": {"loader": "untrusted.py:load"}},
    {"name": "duplicity", "source_columns": ["anything"]},
])
def test_unsupported_metric_and_input_overrides_fail_before_loading(tmp_path, metric_request):
    with pytest.raises(ValueError):
        run_collection_metrics([CollectionMember("missing", str(tmp_path / "missing"))], [metric_request])


def test_manifest_relative_paths_and_cli_report_actual_failures(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("sensor,t\nA,0.0\nA,0.01\n")
    config = {"files": [{"id": "a", "path": "data.csv"}], "mode": "stacked", "metrics": [{"name": "duplicity"}]}
    manifest = tmp_path / "collection.json"
    manifest.write_text(json.dumps(config))
    assert load_collection_config(manifest)["files"][0].path == str(path)
    from aidrin.headless.cli import main

    output = io.StringIO()
    with patch("sys.argv", ["aidrin", "collection", str(manifest)]), patch("sys.stdout", output):
        main()
    result = json.loads(output.getvalue())
    assert result["datasets"][0]["metrics"]["duplicity"]["Duplicity scores"]["Overall duplicity of the dataset"] == 0
    config["files"][0]["path"] = "missing.csv"
    manifest.write_text(json.dumps(config))
    with patch("sys.argv", ["aidrin", "collection", str(manifest)]), patch("sys.stdout", io.StringIO()), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_mcp_uses_the_same_collection_executor(tmp_path):
    pytest.importorskip("mcp")
    from aidrin.mcp.server import run_file_collection, list_collection_metrics

    files = members(tmp_path, [pd.DataFrame({"x": [1, 1]})])
    inputs = [{"id": member.id, "path": member.path} for member in files]
    result = json.loads(run_file_collection(inputs, [{"name": "duplicity"}]))
    assert result["datasets"][0]["metrics"]["duplicity"]["Duplicity scores"]["Overall duplicity of the dataset"] == .5
    assert "duplicity" in json.loads(list_collection_metrics())["metrics"]


@pytest.mark.parametrize("columns", [("plot_id", "missing"), ("missing", "plot_id")])
def test_collection_preserves_plot_named_scores_and_emits_strict_json(tmp_path, columns):
    path = tmp_path / "scores.csv"
    pd.DataFrame({"plot_id": [0, 1, 2, 3, 100], "missing": [None] * 5}).to_csv(path, columns=list(columns), index=False)
    result = run_collection_metrics([CollectionMember("scores", str(path))], [
        {"name": "completeness"}, {"name": "outliers"},
    ])
    scores = result["datasets"][0]["metrics"]
    assert scores["completeness"]["Completeness scores"] == {"plot_id": 1.0, "missing": 0.0}
    assert scores["outliers"]["Outlier scores"]["plot_id"] == .2
    assert scores["outliers"]["Outlier scores"]["missing"] is None
    assert not any(key.endswith(" Visualization") for metric in scores.values() for key in metric)
    json.dumps(result, allow_nan=False)


def test_collection_supports_numeric_excel_headers(tmp_path):
    path = tmp_path / "wavelengths.xlsx"
    pd.DataFrame({450: [1, 2], 650: [1, None]}).to_excel(path, index=False)
    result = run_collection_metrics([CollectionMember("wavelengths", str(path))], [{"name": "completeness"}])
    assert result["datasets"][0]["metrics"]["completeness"]["Completeness scores"] == {"450": 1.0, "650": .5}


@pytest.mark.parametrize("name", ["completeness", "duplicity", "outliers"])
def test_measurement_metrics_reject_provenance_columns(tmp_path, name):
    files = members(tmp_path, [pd.DataFrame({"x": [1, 1]})])
    with pytest.raises(ValueError, match="does not support collection source columns"):
        run_collection_metrics(files, [{"name": name, "source_columns": ["__aidrin_source_id"]}], "stacked")



def test_collection_reuses_an_existing_frame_cache_without_creating_one(tmp_path, monkeypatch):
    from aidrin.file_handling.file_parser import _frame_cache_path

    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "1")
    warm, cold = (tmp_path / name for name in ("warm.csv", "cold.csv"))
    for path in (warm, cold):
        path.write_text("x\n1\n1\n", encoding="utf-8")
    read_file((str(warm), warm.name, ".csv"))
    warm_cache = Path(_frame_cache_path(str(warm)))
    original = warm_cache.read_bytes()
    result = run_collection_metrics([CollectionMember(path.name, str(path)) for path in (warm, cold)], [{"name": "duplicity"}])
    assert result["summary"]["datasets_with_errors"] == 0
    assert warm_cache.read_bytes() == original
    assert not Path(_frame_cache_path(str(cold))).exists()


def test_stacked_duplicity_handles_nested_values_after_scalars(tmp_path):
    scalar, nested = (tmp_path / name for name in ("scalar.json", "nested.json"))
    scalar.write_text('[{"x":"a","n":1},{"x":2,"n":2}]', encoding="utf-8")
    nested.write_text('[{"x":[1,2],"n":1},{"x":[1,2],"n":1}]', encoding="utf-8")
    files = [CollectionMember(path.name, str(path)) for path in (scalar, nested)]
    for ordered in (files, files[::-1]):
        result = run_collection_metrics(ordered, [{"name": "duplicity"}], "stacked")["datasets"][0]
        assert result["status"] == "ok"
        assert result["metrics"]["duplicity"]["Duplicity scores"]["Overall duplicity of the dataset"] == .25


def test_workspace_directory_size_is_unavailable_for_directory_stores(tmp_path, monkeypatch):
    from aidrin.file_handling.workspace_summary import summarize_workspace_directory

    monkeypatch.setattr("aidrin.file_handling.workspace_summary.read_file", lambda *args, **kwargs: pd.DataFrame({"x": [1]}))
    (tmp_path / "records.zarr").mkdir()
    (tmp_path / "small.csv").write_text("x\n1\n", encoding="utf-8")
    rows = summarize_workspace_directory(str(tmp_path), 2)["files"]
    assert "size" not in rows[0]["summary"]
    assert rows[0]["summary"]["records"] == 1
    assert rows[1]["summary"]["size"] == 4


def test_stacked_duplicity_distinguishes_json_objects_from_arrays_of_pairs(tmp_path):
    mapping, array = (tmp_path / name for name in ("mapping.json", "array.json"))
    mapping.write_text('[{"payload":{"a":1},"n":42}]', encoding="utf-8")
    array.write_text('[{"payload":[["a",1]],"n":42}]', encoding="utf-8")
    files = [CollectionMember(path.name, str(path)) for path in (mapping, array)]
    for ordered in (files, files[::-1]):
        result = run_collection_metrics(ordered, [{"name": "duplicity"}], "stacked")["datasets"][0]
        assert result["metrics"]["duplicity"]["Duplicity scores"]["Overall duplicity of the dataset"] == 0
