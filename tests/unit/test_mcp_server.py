"""Tests for the MCP custom-outlier rule-file interfaces."""

import json
import os
import tempfile

import pandas as pd
import pytest

pytest.importorskip("mcp")

from aidrin.mcp.server import run_aidrin_metric, run_custom_outlier_check  # noqa: E402


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
