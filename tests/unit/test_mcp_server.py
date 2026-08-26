"""Tests for the MCP custom-outlier rule-file interfaces."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

pytest.importorskip("mcp")

from aidrin.mcp.server import (  # noqa: E402
    run_aidrin_metric,
    run_custom_metric,
    run_custom_outlier_check,
    run_custom_remedy,
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


# ---------------------------------------------------------------------------
# File reference validation
# ---------------------------------------------------------------------------


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


class TestMcpRemoteRouting(unittest.TestCase):
    """endpoint/profile route through RemoteExecutor; absence stays local."""

    def setUp(self):
        # Redirect both profile locations into temp dirs, so the tests never
        # read (or depend on the shape of) a real ~/.aidrin/config.json.
        self.home = tempfile.mkdtemp()
        self.project = tempfile.mkdtemp()
        self._env = patch.dict(os.environ, {"AIDRIN_CONFIG_DIR": self.home}, clear=False)
        self._env.start()
        os.environ.pop("AIDRIN_GLOBUS_ENDPOINT", None)
        self._cwd = patch.object(Path, "cwd", staticmethod(lambda: Path(self.project)))
        self._cwd.start()

    def tearDown(self):
        self._cwd.stop()
        self._env.stop()

    def test_summarize_local_by_default(self):
        from aidrin.mcp import server

        with patch("aidrin.headless.api.summarize_dataset", return_value={"ok": 1}) as local:
            server.summarize_dataset(file_path="/x.csv")
        local.assert_called_once()

    def test_summarize_routes_to_endpoint(self):
        from aidrin.mcp import server

        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={"shape": {"rows": 4, "columns": 1}}):
            out = server.summarize_dataset(file_path="/scratch/x.csv", endpoint="uuid-9")
        self.assertEqual(json.loads(out)["shape"]["rows"], 4)
        self.assertEqual(submit.call_args[0][1], "uuid-9")

    def test_metric_routes_to_endpoint(self):
        from aidrin.mcp import server

        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={"Completeness scores": {}}):
            server.run_aidrin_metric(file_path="/x.csv", metric="completeness", endpoint="uuid-9")
        self.assertEqual(submit.call_args[0][2], "run_metric")

    def test_file_reference_metric_routes_arguments_to_endpoint(self):
        from aidrin.mcp import server

        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={"Summary": {}}):
            server.run_aidrin_metric(
                file_path="/manifest.csv",
                metric="file-reference-validation",
                path_targets="file_path",
                base_dir="/data/project",
                endpoint="uuid-9",
            )

        payload = submit.call_args[0][3]
        self.assertEqual(payload["path_targets"], "file_path")
        self.assertEqual(payload["base_dir"], "/data/project")

    def test_list_remote_profiles_returns_json(self):
        from aidrin.mcp import server

        out = server.list_remote_profiles()
        self.assertIn("profiles", json.loads(out))
