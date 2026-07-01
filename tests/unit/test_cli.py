"""Unit tests for the aidrin CLI (aidrin.headless.cli).

Covers argument parsing, helper utilities, and command dispatch using
sys.argv patching + stdout capture — no subprocess or network required.
"""

import io
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# pkg_resources stub (mirrors other unit test files)
# ---------------------------------------------------------------------------

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_csv(df: pd.DataFrame) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return tmp.name


def _clean(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _sample_df(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "age": rng.integers(20, 70, size=n),
            "income": rng.integers(20_000, 100_000, size=n),
            "sex": rng.choice(["M", "F"], size=n),
            "label": rng.choice(["<=50K", ">50K"], size=n),
        }
    )


def _run_cli(*argv: str) -> tuple[str, str, int]:
    """Invoke main() with the given argv, returning (stdout, stderr, exit_code)."""
    from aidrin.headless.cli import main

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    exit_code = 0
    with patch("sys.argv", ["aidrin", *argv]), \
         patch("sys.stdout", out_buf), \
         patch("sys.stderr", err_buf):
        try:
            main()
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
    return out_buf.getvalue(), err_buf.getvalue(), exit_code


# ===========================================================================
# Helper-function unit tests
# ===========================================================================


class TestParseList(unittest.TestCase):

    def setUp(self):
        from aidrin.headless.cli import _parse_list
        self._parse_list = _parse_list

    def test_none_returns_none(self):
        self.assertIsNone(self._parse_list(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(self._parse_list(""))

    def test_single_item(self):
        self.assertEqual(self._parse_list("age"), ["age"])

    def test_multiple_items(self):
        self.assertEqual(self._parse_list("age,income,sex"), ["age", "income", "sex"])

    def test_whitespace_stripped(self):
        self.assertEqual(self._parse_list(" age , income "), ["age", "income"])


class TestFmt(unittest.TestCase):

    def setUp(self):
        from aidrin.headless.cli import _fmt
        self._fmt = _fmt

    def test_float_formatted_to_4dp(self):
        self.assertEqual(self._fmt(0.123456789), "0.1235")

    def test_integer_as_string(self):
        self.assertEqual(self._fmt(42), "42")

    def test_string_passthrough(self):
        self.assertEqual(self._fmt("N/A"), "N/A")


class TestRoundFloats(unittest.TestCase):

    def setUp(self):
        from aidrin.headless.cli import _round_floats
        self._round_floats = _round_floats

    def test_rounds_top_level_float(self):
        self.assertEqual(self._round_floats(3.141592653), 3.1416)

    def test_rounds_nested_dict(self):
        result = self._round_floats({"a": 1.23456789, "b": "x"})
        self.assertAlmostEqual(result["a"], 1.2346, places=4)
        self.assertEqual(result["b"], "x")

    def test_rounds_list_elements(self):
        result = self._round_floats([1.11111, 2.22222])
        self.assertAlmostEqual(result[0], 1.1111, places=4)

    def test_integers_unchanged(self):
        self.assertEqual(self._round_floats(7), 7)

    def test_deeply_nested(self):
        data = {"outer": {"inner": 0.999999}}
        result = self._round_floats(data)
        self.assertAlmostEqual(result["outer"]["inner"], 1.0, places=4)


# ===========================================================================
# list command
# ===========================================================================


class TestListCommand(unittest.TestCase):

    def test_list_exits_zero(self):
        _, _, code = _run_cli("list")
        self.assertEqual(code, 0)

    def test_list_returns_valid_json(self):
        stdout, _, _ = _run_cli("list")
        data = json.loads(stdout)
        self.assertIsInstance(data, (dict, list))

    def test_list_contains_known_metrics(self):
        stdout, _, _ = _run_cli("list")
        text = stdout.lower()
        self.assertIn("completeness", text)
        self.assertIn("duplicity", text)
        self.assertIn("outliers", text)

    def test_list_category_filter(self):
        stdout, _, _ = _run_cli("list", "--category", "data-quality")
        data = json.loads(stdout)
        self.assertIsInstance(data, (dict, list))


# ===========================================================================
# data-quality command
# ===========================================================================


class TestDataQualityCommand(unittest.TestCase):

    def setUp(self):
        self.csv = _write_csv(_sample_df())

    def tearDown(self):
        _clean(self.csv)

    def test_data_quality_exits_zero(self):
        _, _, code = _run_cli("data-quality", self.csv)
        self.assertEqual(code, 0)

    def test_data_quality_summary_contains_expected_sections(self):
        stdout, _, _ = _run_cli("data-quality", self.csv)
        self.assertIn("Completeness", stdout)
        self.assertIn("Duplicity", stdout)
        self.assertIn("Outliers", stdout)

    def test_data_quality_detail_returns_valid_json(self):
        stdout, _, _ = _run_cli("data-quality", self.csv, "--detail")
        data = json.loads(stdout)
        self.assertIsInstance(data, dict)

    def test_data_quality_detail_contains_expected_keys(self):
        stdout, _, _ = _run_cli("data-quality", self.csv, "--detail")
        data = json.loads(stdout)
        for key in ("completeness", "duplicity", "outliers"):
            self.assertIn(key, data, f"Missing key: {key}")

    def test_data_quality_detail_completeness_score_in_range(self):
        stdout, _, _ = _run_cli("data-quality", self.csv, "--detail")
        data = json.loads(stdout)
        score = data["completeness"].get("Overall Completeness")
        self.assertIsNotNone(score)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


# ===========================================================================
# run <metric> command
# ===========================================================================


class TestRunCommand(unittest.TestCase):

    def setUp(self):
        self.csv = _write_csv(_sample_df())

    def tearDown(self):
        _clean(self.csv)

    def test_run_completeness_exits_zero(self):
        _, _, code = _run_cli("run", "completeness", self.csv)
        self.assertEqual(code, 0)

    def test_run_completeness_returns_json(self):
        stdout, _, _ = _run_cli("run", "completeness", self.csv)
        data = json.loads(stdout)
        self.assertIn("Overall Completeness", data)

    def test_run_duplicity_exits_zero(self):
        _, _, code = _run_cli("run", "duplicity", self.csv)
        self.assertEqual(code, 0)

    def test_run_duplicity_returns_json(self):
        stdout, _, _ = _run_cli("run", "duplicity", self.csv)
        data = json.loads(stdout)
        self.assertIn("Duplicity scores", data)

    def test_run_outliers_exits_zero(self):
        _, _, code = _run_cli("run", "outliers", self.csv)
        self.assertEqual(code, 0)

    def test_run_outliers_returns_json(self):
        stdout, _, _ = _run_cli("run", "outliers", self.csv)
        data = json.loads(stdout)
        self.assertIn("Outlier scores", data)

    def test_run_correlations_exits_zero(self):
        _, _, code = _run_cli("run", "correlations", self.csv, "age,income,sex")
        self.assertEqual(code, 0)

    def test_shortcut_metric_name(self):
        """aidrin completeness <file> maps to aidrin run completeness <file>."""
        _, _, code = _run_cli("completeness", self.csv)
        self.assertEqual(code, 0)


# ===========================================================================
# add-custom-module command
# ===========================================================================


class TestAddCustomModuleCommand(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_template_file(self):
        _, _, code = _run_cli("add-custom-module", "mymetric", "--dir", self.tmpdir)
        self.assertEqual(code, 0)
        files = os.listdir(self.tmpdir)
        self.assertTrue(any("mymetric" in f for f in files), f"No template file found in {files}")

    def test_duplicate_name_does_not_crash(self):
        _run_cli("add-custom-module", "mymetric", "--dir", self.tmpdir)
        _, _, code = _run_cli("add-custom-module", "mymetric", "--dir", self.tmpdir)
        # Should print a message but not raise — exit 0
        self.assertEqual(code, 0)


# ===========================================================================
# Error handling
# ===========================================================================


class TestCLIErrorHandling(unittest.TestCase):

    def test_missing_file_exits_nonzero(self):
        _, _, code = _run_cli("run", "completeness", "/nonexistent/path/data.csv")
        self.assertNotEqual(code, 0)

    def test_missing_file_writes_to_stderr(self):
        _, stderr, _ = _run_cli("run", "completeness", "/nonexistent/path/data.csv")
        self.assertIn("Error", stderr)

    def test_no_command_exits_nonzero(self):
        _, _, code = _run_cli()
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
