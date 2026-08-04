"""Tests for the MCP custom-outlier rule-file interfaces."""

import json
import os
import tempfile

import pandas as pd
import pytest

pytest.importorskip("mcp")

from aidrin.mcp.server import (  # noqa: E402
    run_aidrin_metric,
    run_custom_metric,
    run_custom_outlier_check,
    run_custom_remedy,
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


# ---------------------------------------------------------------------------
# Custom metrics — multi-format support
# ---------------------------------------------------------------------------

_CUSTOM_SCRIPT = """
from aidrin.custom_metrics.base_dr import BaseDRAgent

class CustomDR(BaseDRAgent):
    def metric(self, **kwargs):
        return {"row_count": len(self.dataset)}

    def remedy(self, **kwargs):
        return self.dataset.copy()
"""


def _write_script(tmp_path) -> str:
    path = os.path.join(tmp_path, "my_audit.py")
    with open(path, "w") as f:
        f.write(_CUSTOM_SCRIPT)
    return path


def _write_parquet(tmp_path) -> str:
    path = os.path.join(tmp_path, "data.parquet")
    pd.DataFrame({"age": [18, 30, 70]}).to_parquet(path)
    return path


def test_run_custom_metric_accepts_non_csv_format(tmp_path):
    script_path = _write_script(str(tmp_path))
    parquet_path = _write_parquet(str(tmp_path))
    result = json.loads(run_custom_metric(script_path, parquet_path, file_type="parquet"))
    assert result["row_count"] == 3


def test_run_custom_remedy_saves_csv_for_non_csv_input(tmp_path):
    script_path = _write_script(str(tmp_path))
    parquet_path = _write_parquet(str(tmp_path))
    output_dir = str(tmp_path / "remedy_out")
    result = json.loads(
        run_custom_remedy(script_path, parquet_path, output_dir=output_dir, file_type="parquet")
    )
    assert result["remedied_file"].endswith(".csv")
    assert os.path.exists(result["remedied_file"])
