import json
import os
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

import aidrin.structured_data_metrics.file_reference_validation as validation_module
from aidrin.structured_data_metrics.file_reference_validation import (
    _creation_time,
    _is_within_roots,
    calculate_file_reference_validation,
)


EXCEL_TYPE = ".xls, .xlsb, .xlsx, .xlsm"


def _file_info(path, file_type=None):
    return (str(path), path.name, file_type or path.suffix)


def test_validates_references_and_deduplicates_metadata(tmp_path):
    referenced = tmp_path / "target.txt"
    referenced.write_text("hello", encoding="utf-8")
    directory = tmp_path / "folder"
    directory.mkdir()
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({
        "path": [str(referenced), " target.txt ", "missing.txt", "", str(directory)],
    }).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(_file_info(manifest), ["path"])

    summary = result["Summary"]
    assert summary == {
        "candidate_values": 5,
        "scanned_values": 5,
        "unscanned_values": 0,
        "scan_limit": None,
        "scan_complete": True,
        "valid_references": 2,
        "invalid_references": 2,
        "missing_references": 1,
        "unique_reference_values": 4,
        "unique_resolved_paths": 3,
        "unique_valid_files": 1,
        "validity_rate": 0.4,
        "all_references_valid": False,
        "invalid_details_truncated": False,
        "metadata_details_truncated": False,
    }
    assert [item["reason"] for item in result["Invalid references"]] == ["not_found", "not_a_file"]
    assert result["Invalid references"][0]["location"] == {
        "row_index": 2,
        "display": "row 2",
        "source_line": 4,
    }
    assert result["File metadata"][0]["resolved_path"] == str(referenced)
    assert result["File metadata"][0]["occurrences"] == 2
    assert result["File metadata"][0]["size_bytes"] == 5


def test_scan_limit_is_global_across_targets(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("1", encoding="utf-8")
    second.write_text("2", encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({
        "a_path": [str(first), str(second)],
        "b_path": [str(first), str(second)],
    }).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(
        _file_info(manifest), ["a_path", "b_path"], scan_limit=3
    )

    assert result["Summary"]["candidate_values"] == 4
    assert result["Summary"]["scanned_values"] == 3
    assert result["Summary"]["unscanned_values"] == 1
    assert result["Summary"]["scan_complete"] is False
    assert result["Summary"]["all_references_valid"] is False
    assert result["Target summaries"]["a_path"]["scan_complete"] is True
    assert result["Target summaries"]["b_path"]["scanned_values"] == 1
    assert result["Target summaries"]["b_path"]["unscanned_values"] == 1


@pytest.mark.parametrize("limit", [None, 0])
def test_unlimited_scan_reports_all_valid(tmp_path, limit):
    target = tmp_path / "target.txt"
    target.write_text("ok", encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"path": [str(target), str(target)]}).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(
        _file_info(manifest), "path", scan_limit=limit
    )

    assert result["Summary"]["scan_complete"] is True
    assert result["Summary"]["all_references_valid"] is True
    assert result["Summary"]["validity_rate"] == 1.0


def test_detail_caps_do_not_change_complete_counts(tmp_path):
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"path": ["missing-1", "missing-2", "missing-3"]}).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(
        _file_info(manifest), "path", max_results=1
    )

    assert result["Summary"]["invalid_references"] == 3
    assert result["Summary"]["invalid_details_truncated"] is True
    assert len(result["Invalid references"]) == 1


def test_outside_root_is_rejected_before_explicit_stat(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    manifest = allowed / "manifest.csv"
    pd.DataFrame({"path": [str(outside)]}).to_csv(manifest, index=False)

    def unexpected_lstat(_path):
        raise AssertionError("outside-root path reached explicit lstat")

    monkeypatch.setattr(validation_module, "_lstat_target", unexpected_lstat)
    result = calculate_file_reference_validation(
        _file_info(manifest), "path", allowed_roots=[allowed]
    )

    assert result["Invalid references"][0]["reason"] == "outside_allowed_root"


def test_permission_error_is_scoped_to_reference(tmp_path, monkeypatch):
    target = tmp_path / "target.txt"
    target.write_text("secret", encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"path": [str(target)]}).to_csv(manifest, index=False)

    def denied(_path):
        raise PermissionError(errno_value := 13, os.strerror(errno_value))

    monkeypatch.setattr(validation_module, "_lstat_target", denied)
    result = calculate_file_reference_validation(_file_info(manifest), "path")

    assert result["Invalid references"][0]["reason"] == "permission_denied"


def test_symlink_and_direct_alias_share_metadata(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("hello", encoding="utf-8")
    link = tmp_path / "target-link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"path": [str(target), str(link)]}).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(_file_info(manifest), "path")

    assert result["Summary"]["unique_valid_files"] == 1
    assert result["File metadata"][0]["occurrences"] == 2
    assert result["File metadata"][0]["referenced_via_symlink"] is True


def test_broken_symlink_has_specific_reason(tmp_path):
    link = tmp_path / "broken.txt"
    try:
        link.symlink_to(tmp_path / "missing.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"path": [str(link)]}).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(_file_info(manifest), "path")

    assert result["Invalid references"][0]["reason"] == "broken_symlink"


def test_symlink_escape_is_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = allowed / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    manifest = allowed / "manifest.csv"
    pd.DataFrame({"path": [str(link)]}).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(
        _file_info(manifest), "path", allowed_roots=[allowed]
    )

    assert result["Invalid references"][0]["reason"] == "outside_allowed_root"


def test_invalid_and_unsupported_values(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("unused\n", encoding="utf-8")
    target = {
        "name": "path",
        "target_type": "column",
        "dtype": "object",
        "shape": [4],
    }
    block = {
        "target": "path",
        "target_type": "column",
        "values": np.array([b"\xff", 42, "bad\x00path", "https://example.com/file"], dtype=object),
        "offset": None,
        "locate": lambda index: {"row_index": index[0]},
    }
    monkeypatch.setattr(validation_module, "iter_targets", lambda _file_info: [target])
    monkeypatch.setattr(validation_module, "iter_value_blocks", lambda _file_info, _target: [block])

    result = calculate_file_reference_validation(_file_info(manifest), "path", max_results=0)

    assert [item["reason"] for item in result["Invalid references"]] == [
        "unsupported_value",
        "unsupported_value",
        "invalid_path",
        "invalid_path",
    ]


def test_target_errors_are_scoped_and_prevent_all_valid(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("ok", encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"path": [str(target)], "count": [1]}).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(
        _file_info(manifest), ["path", "count", "absent"]
    )

    assert result["Summary"]["valid_references"] == 1
    assert result["Summary"]["all_references_valid"] is False
    assert len(result["Errors"]) == 2
    assert "dtype" in result["Errors"][0]["error"]
    assert result["Errors"][1]["error"] == "Target not found: absent"


def test_regex_targets_expand_in_discovery_order_and_deduplicate(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("ok", encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({
        "primary_path": [target.name],
        "backup_path": [target.name],
        "count": [1],
    }).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(
        _file_info(manifest),
        [r".*_[a-z]{1,4}", r"primary_.*"],
        target_match="regex",
    )

    assert list(result["Target summaries"]) == ["primary_path", "backup_path"]
    assert result["Summary"]["valid_references"] == 2
    assert result["Errors"] == []


def test_regex_string_preserves_commas_in_quantifiers(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("ok", encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"file_12_path": [target.name]}).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(
        _file_info(manifest), r"file_[0-9]{1,3}_path", target_match="regex"
    )

    assert list(result["Target summaries"]) == ["file_12_path"]
    assert result["Summary"]["all_references_valid"] is True


def test_regex_target_reports_no_path_bearing_matches(tmp_path):
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"path": ["missing.txt"], "count": [1]}).to_csv(manifest, index=False)

    result = calculate_file_reference_validation(
        _file_info(manifest), r"count|absent", target_match="regex"
    )

    assert result["Target summaries"] == {}
    assert result["Errors"] == [{
        "target": "count|absent",
        "error": "No path-bearing targets matched regex: count|absent",
    }]


@pytest.mark.parametrize(
    ("target_match", "message"),
    [("glob", "Unsupported target_match"), ("regex", "Invalid target regex")],
)
def test_invalid_target_match_is_rejected(tmp_path, target_match, message):
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"path": ["missing.txt"]}).to_csv(manifest, index=False)
    target = "[" if target_match == "regex" else "path"

    with pytest.raises(ValueError, match=message):
        calculate_file_reference_validation(
            _file_info(manifest), target, target_match=target_match
        )


def test_commonpath_value_error_is_outside_root(monkeypatch):
    monkeypatch.setattr(os.path, "commonpath", lambda _paths: (_ for _ in ()).throw(ValueError("different drives")))
    assert _is_within_roots("C:/data/file", ["D:/data"]) is False


def test_creation_time_platform_rules():
    birth = SimpleNamespace(st_birthtime=100, st_ctime=200)
    created, source = _creation_time(birth)
    assert source == "birthtime"
    assert created.endswith("Z")

    windows = SimpleNamespace(st_ctime=200)
    created, source = _creation_time(windows, os_name="nt")
    assert source == "windows_ctime"
    assert created.endswith("Z")

    assert _creation_time(windows, os_name="posix") == (None, "unavailable")


@pytest.mark.parametrize("format_name", ["csv", "excel", "parquet", "json", "npz", "hdf5"])
def test_supported_string_formats(tmp_path, format_name):
    target = tmp_path / "target.txt"
    target.write_text("ok", encoding="utf-8")

    if format_name == "csv":
        manifest = tmp_path / "manifest.csv"
        pd.DataFrame({"path": [str(target)]}).to_csv(manifest, index=False)
        file_info = _file_info(manifest)
        path_target = "path"
    elif format_name == "excel":
        manifest = tmp_path / "manifest.xlsx"
        pd.DataFrame({"path": [str(target)]}).to_excel(manifest, index=False)
        file_info = _file_info(manifest, EXCEL_TYPE)
        path_target = "path"
    elif format_name == "parquet":
        manifest = tmp_path / "manifest.parquet"
        pd.DataFrame({"path": [str(target)]}).to_parquet(manifest, index=False)
        file_info = _file_info(manifest)
        path_target = "path"
    elif format_name == "json":
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps([{"path": str(target)}]), encoding="utf-8")
        file_info = _file_info(manifest)
        path_target = "path"
    elif format_name == "npz":
        manifest = tmp_path / "manifest.npz"
        np.savez(manifest, path=np.array([str(target)]))
        file_info = _file_info(manifest)
        path_target = "path"
    else:
        manifest = tmp_path / "manifest.h5"
        with h5py.File(manifest, "w") as handle:
            handle.create_dataset("paths", data=np.array([str(target).encode("utf-8")]))
        file_info = _file_info(manifest)
        path_target = "/paths"

    result = calculate_file_reference_validation(file_info, path_target)

    assert result["Summary"]["valid_references"] == 1
    assert result["Summary"]["all_references_valid"] is True
