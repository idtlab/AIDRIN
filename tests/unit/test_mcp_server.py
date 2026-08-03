"""Tests for the MCP custom-outlier rule-file interfaces."""

import json
import os
import tempfile

import pandas as pd
import pytest

pytest.importorskip("mcp")

from aidrin.mcp.server import (  # noqa: E402
    run_aidrin_metric,
    run_custom_outlier_check,
    verify_file_references,
)


def _write_csv() -> str:
    file = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    path = file.name
    file.close()
    pd.DataFrame({"age": [18, 30, 70]}).to_csv(path, index=False)
    return path


def _write_rules() -> str:
    file = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump([{
        "id": "valid-age",
        "target": "age",
        "target_type": "column",
        "criteria": {"type": "range", "min": 20, "max": 60},
    }], file)
    file.close()
    return file.name


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def test_dedicated_mcp_tool_accepts_rules_file():
    csv_path = _write_csv()
    rules_path = _write_rules()
    try:
        result = json.loads(run_custom_outlier_check(csv_path, rules_file=rules_path))
    finally:
        _remove(csv_path)
        _remove(rules_path)
    assert "valid-age" in result["Rule summaries"]


def test_generic_mcp_tool_accepts_rules_file():
    csv_path = _write_csv()
    rules_path = _write_rules()
    try:
        result = json.loads(
            run_aidrin_metric(csv_path, "outliers-custom", rules_file=rules_path)
        )
    finally:
        _remove(csv_path)
        _remove(rules_path)
    assert "valid-age" in result["Rule summaries"]


def test_dedicated_mcp_tool_rejects_multiple_rule_sources():
    csv_path = _write_csv()
    rules_path = _write_rules()
    try:
        with pytest.raises(ValueError, match="Provide exactly one custom-outlier rule source"):
            run_custom_outlier_check(csv_path, rules_json="[]", rules_file=rules_path)
    finally:
        _remove(csv_path)
        _remove(rules_path)


def test_file_reference_tools_return_equivalent_results(tmp_path):
    referenced_file = tmp_path / "artifact.bin"
    referenced_file.write_bytes(b"aidrin")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"file_path": [referenced_file.name]}).to_csv(manifest, index=False)

    dedicated = json.loads(
        verify_file_references(
            str(manifest),
            "file_path",
            base_dir=str(tmp_path),
            max_results=1,
        )
    )
    generic = json.loads(
        run_aidrin_metric(
            str(manifest),
            "file-reference-validation",
            path_targets="file_path",
            base_dir=str(tmp_path),
            max_results=1,
        )
    )

    assert dedicated == generic
    assert dedicated["Summary"]["all_references_valid"] is True
    assert dedicated["File metadata"][0]["size_bytes"] == 6


def test_file_reference_tools_support_regex_targets(tmp_path):
    referenced_file = tmp_path / "artifact.bin"
    referenced_file.write_bytes(b"aidrin")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"primary_path": [referenced_file.name]}).to_csv(manifest, index=False)

    dedicated = json.loads(
        verify_file_references(
            str(manifest), r"primary_[a-z]{1,4}", base_dir=str(tmp_path), target_match="regex"
        )
    )
    generic = json.loads(
        run_aidrin_metric(
            str(manifest),
            "file-reference-validation",
            path_targets=r"primary_[a-z]{1,4}",
            base_dir=str(tmp_path),
            target_match="regex",
        )
    )

    assert dedicated == generic
    assert list(dedicated["Target summaries"]) == ["primary_path"]


def test_file_reference_mcp_tool_accepts_explicit_regex_pattern_list(tmp_path):
    referenced_file = tmp_path / "artifact.bin"
    referenced_file.write_bytes(b"aidrin")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({
        "primary_path": [referenced_file.name],
        "backup_path": [referenced_file.name],
    }).to_csv(manifest, index=False)

    result = json.loads(
        verify_file_references(
            str(manifest),
            [r"primary_[a-z]{1,4}", r"backup_[a-z]{1,4}"],
            base_dir=str(tmp_path),
            target_match="regex",
        )
    )

    assert list(result["Target summaries"]) == ["primary_path", "backup_path"]
