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


def _write_json(value) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump(value, tmp)
    tmp.close()
    return tmp.name


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
        self.assertIn("outliers-custom", text)
        self.assertIn("file-reference-validation", text)

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

    def test_run_outliers_custom_returns_json(self):
        rules = json.dumps([{
            "id": "age-range",
            "target": "age",
            "target_type": "column",
            "criteria": {"type": "range", "min": 20, "max": 60},
        }])
        stdout, _, code = _run_cli(
            "run",
            "outliers-custom",
            self.csv,
            rules,
            "--max-outliers",
            "0",
        )
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertIn("Rule summaries", data)
        self.assertEqual(data["Rule summaries"]["age-range"]["preview_limit"], 0)

    def test_run_outliers_custom_accepts_rule_shorthand(self):
        stdout, _, code = _run_cli(
            "run",
            "outliers-custom",
            self.csv,
            "--rule",
            "age >= 20 && age <= 60",
            "--max-outliers",
            "0",
        )
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertIn("age-1", data["Rule summaries"])
        self.assertEqual(data["Rule summaries"]["age-1"]["preview_limit"], 0)

    def test_run_outliers_custom_rejects_mixed_target_shorthand(self):
        _, stderr, code = _run_cli(
            "run",
            "outliers-custom",
            self.csv,
            "--rule",
            "age >= 20 && income <= 100000",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("same target", stderr)

    def test_run_outliers_custom_accepts_rules_file(self):
        rules_path = _write_json([{
            "id": "age-range",
            "target": "age",
            "target_type": "column",
            "criteria": {"type": "range", "min": 20, "max": 60},
        }])
        try:
            stdout, _, code = _run_cli(
                "run",
                "outliers-custom",
                self.csv,
                "--rules-file",
                rules_path,
            )
        finally:
            _clean(rules_path)
        self.assertEqual(code, 0)
        self.assertIn("age-range", json.loads(stdout)["Rule summaries"])

    def test_run_outliers_custom_rejects_rules_file_with_rule(self):
        rules_path = _write_json([])
        try:
            _, stderr, code = _run_cli(
                "run",
                "outliers-custom",
                self.csv,
                "--rules-file",
                rules_path,
                "--rule",
                "age >= 20",
            )
        finally:
            _clean(rules_path)
        self.assertNotEqual(code, 0)
        self.assertIn("exactly one custom-outlier rule source", stderr)

    def test_run_correlations_exits_zero(self):
        _, _, code = _run_cli("run", "correlations", self.csv, "age,income,sex")
        self.assertEqual(code, 0)

    def test_shortcut_metric_name(self):
        """aidrin completeness <file> maps to aidrin run completeness <file>."""
        _, _, code = _run_cli("completeness", self.csv)
        self.assertEqual(code, 0)

    # --- hipaa-compliance wiring ------------------------------------------

    def test_run_hipaa_compliance_exits_zero(self):
        _, _, code = _run_cli("run", "hipaa-compliance", self.csv, "age,income,sex")
        self.assertEqual(code, 0)

    def test_run_hipaa_compliance_no_phi_returns_empty(self):
        # age (2-digit) and sex (M/F) match no PHI pattern. NB: income is
        # deliberately excluded — 5-digit incomes can match the postal-code
        # candidate regex and validate as real ZIPs (a detector false positive).
        stdout, _, _ = _run_cli("run", "hipaa-compliance", self.csv, "age,sex")
        self.assertEqual(json.loads(stdout), {})

    def test_run_hipaa_compliance_detects_phi(self):
        csv = _write_csv(pd.DataFrame({
            "contact": ["a@b.com", "c@d.org"],
            "age": [30, 40],
        }))
        try:
            stdout, _, code = _run_cli("run", "hipaa-compliance", csv, "contact")
            self.assertEqual(code, 0)
            data = json.loads(stdout)
            self.assertIn("contact", data)
            self.assertIn("EMAIL_ADDRESS", data["contact"]["potential_types_detected"])
        finally:
            _clean(csv)

    def test_shortcut_multiword_metric(self):
        """aidrin hipaa-compliance <file> ... routes to `run` (guards the
        multi-word shortcut fix: the old code passed underscore form to the
        dash-only `run` subparser and errored)."""
        _, _, code = _run_cli("hipaa-compliance", self.csv, "age,income,sex")
        self.assertEqual(code, 0)

    def test_shortcut_underscore_form_resolves(self):
        """Underscore shortcut form also resolves after dash normalization."""
        _, _, code = _run_cli("hipaa_compliance", self.csv, "age,income,sex")
        self.assertEqual(code, 0)


# ===========================================================================
# hipaa summary line (_summarize_metric)
# ===========================================================================


class TestSummarizeHipaa(unittest.TestCase):

    def _capture(self, metric_name: str, result: dict) -> str:
        from aidrin.headless.cli import _summarize_metric
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _summarize_metric(metric_name, result)
        return buf.getvalue()

    def test_no_phi_message(self):
        out = self._capture("hipaa_compliance", {})
        self.assertIn("No PHI detected", out)

    def test_findings_printed(self):
        out = self._capture("hipaa_compliance", {
            "contact": {
                "total_flags": 2,
                "potential_types_detected": ["EMAIL_ADDRESS"],
                "examples": ["a@b.com"],
            },
        })
        self.assertIn("contact", out)
        self.assertIn("2 flag", out)
        self.assertIn("EMAIL_ADDRESS", out)


# ===========================================================================
# run_metric metric-name resolution (dash / underscore)
# ===========================================================================


class TestRunMetricNameResolution(unittest.TestCase):

    def setUp(self):
        self.csv = _write_csv(_sample_df())

    def tearDown(self):
        _clean(self.csv)

    def test_hipaa_in_registry(self):
        from aidrin.headless.api import METRIC_REGISTRY
        self.assertIn("hipaa_compliance", METRIC_REGISTRY)

    def test_dash_form_resolves(self):
        from aidrin.headless.api import run_metric
        result = run_metric(
            "hipaa-compliance", self.csv, columns="age,income,sex", save_images=False
        )
        self.assertIsInstance(result, dict)

    def test_underscore_form_resolves(self):
        from aidrin.headless.api import run_metric
        result = run_metric(
            "hipaa_compliance", self.csv, columns="age,income,sex", save_images=False
        )
        self.assertIsInstance(result, dict)

    def test_dash_and_underscore_equivalent(self):
        from aidrin.headless.api import run_metric
        dash = run_metric("hipaa-compliance", self.csv, columns="age", save_images=False)
        under = run_metric("hipaa_compliance", self.csv, columns="age", save_images=False)
        self.assertEqual(dash, under)

    def test_missing_columns_raises(self):
        from aidrin.headless.api import run_metric
        with self.assertRaises(ValueError):
            run_metric("hipaa-compliance", self.csv, save_images=False)


class TestFileReferenceValidationInterfaces(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = self.temp_dir.name
        self.target_path = os.path.join(self.base_dir, "artifact.bin")
        with open(self.target_path, "wb") as handle:
            handle.write(b"aidrin")
        self.csv = os.path.join(self.base_dir, "manifest.csv")
        pd.DataFrame({"file_path": ["artifact.bin", "missing.bin"]}).to_csv(self.csv, index=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_forwards_targets_base_dir_and_caps(self):
        stdout, stderr, code = _run_cli(
            "run",
            "file-reference-validation",
            self.csv,
            "file_path",
            "--base-dir",
            self.base_dir,
            "--max-results",
            "1",
            "--scan-limit",
            "1",
        )
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(result["Summary"]["scanned_values"], 1)
        self.assertEqual(result["Summary"]["unscanned_values"], 1)
        self.assertEqual(result["File metadata"][0]["size_bytes"], 6)

    def test_cli_supports_regex_target_matching(self):
        stdout, stderr, code = _run_cli(
            "run",
            "file-reference-validation",
            self.csv,
            r"file_[a-z]{1,4}",
            "--target-match",
            "regex",
            "--base-dir",
            self.base_dir,
        )
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(list(result["Target summaries"]), ["file_path"])

    def test_string_api_preserves_regex_target_commas(self):
        from aidrin.headless.api import run_metric

        result = run_metric(
            "file-reference-validation",
            self.csv,
            path_targets=r"file_[a-z]{1,4}",
            target_match="regex",
            base_dir=self.base_dir,
            save_images=False,
        )

        self.assertEqual(list(result["Target summaries"]), ["file_path"])

    def test_run_metric_requires_path_targets(self):
        from aidrin.headless.api import run_metric

        with self.assertRaisesRegex(ValueError, "path_targets is required"):
            run_metric("file-reference-validation", self.csv, save_images=False)

    def test_batch_normalizes_and_forwards_file_reference_options(self):
        from aidrin.headless.api import run_batch_metrics
        from aidrin.headless.config import HeadlessConfig

        config = HeadlessConfig.from_dict({
            "file-path": self.csv,
            "metrics": ["file-reference-validation"],
            "path-targets": r"file_[a-z]{1,4}",
            "base-dir": self.base_dir,
            "max-results": 1,
            "scan-limit": 1,
            "target-match": "regex",
            "save-images": False,
        })
        self.assertEqual(config.path_targets, [r"file_[a-z]{1,4}"])
        self.assertEqual(config.target_match, "regex")
        result = run_batch_metrics(config)
        metric_result = result["file_reference_validation"]
        self.assertEqual(metric_result["Summary"]["scanned_values"], 1)
        self.assertEqual(metric_result["Summary"]["unscanned_values"], 1)
        self.assertEqual(len(metric_result["File metadata"]), 1)


class TestCustomOutlierRulesFile(unittest.TestCase):

    def setUp(self):
        self.csv = _write_csv(_sample_df())
        self.rules = [{
            "id": "age-range",
            "target": "age",
            "target_type": "column",
            "criteria": {"type": "range", "min": 20, "max": 60},
        }]

    def tearDown(self):
        _clean(self.csv)

    def test_run_metric_accepts_rules_file(self):
        from aidrin.headless.api import run_metric

        rules_path = _write_json(self.rules)
        try:
            result = run_metric("outliers-custom", self.csv, rules_file=rules_path, save_images=False)
        finally:
            _clean(rules_path)
        self.assertIn("age-range", result["Rule summaries"])

    def test_rules_file_errors_are_specific(self):
        from aidrin.headless.api import run_metric

        with self.assertRaisesRegex(ValueError, "Unable to read custom-outlier rules file"):
            run_metric("outliers-custom", self.csv, rules_file="/not/a/rules-file.json", save_images=False)

        malformed_path = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        malformed_path.write("{")
        malformed_path.close()
        try:
            with self.assertRaisesRegex(ValueError, "Invalid JSON in custom-outlier rules file"):
                run_metric("outliers-custom", self.csv, rules_file=malformed_path.name, save_images=False)
        finally:
            _clean(malformed_path.name)

        object_path = _write_json({"rules": self.rules})
        try:
            with self.assertRaisesRegex(ValueError, "must contain a JSON array"):
                run_metric("outliers-custom", self.csv, rules_file=object_path, save_images=False)
        finally:
            _clean(object_path)

    def test_empty_rules_file_reaches_existing_validator(self):
        from aidrin.headless.api import run_metric

        rules_path = _write_json([])
        try:
            with self.assertRaisesRegex(ValueError, "non-empty list"):
                run_metric("outliers-custom", self.csv, rules_file=rules_path, save_images=False)
        finally:
            _clean(rules_path)

    def test_rule_sources_must_not_be_mixed(self):
        from aidrin.headless.api import run_metric

        rules_path = _write_json(self.rules)
        inline_rules = json.dumps(self.rules)
        try:
            with self.assertRaisesRegex(ValueError, "Provide exactly one custom-outlier rule source"):
                run_metric(
                    "outliers-custom",
                    self.csv,
                    rules_json=inline_rules,
                    rules_file=rules_path,
                    save_images=False,
                )
        finally:
            _clean(rules_path)


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
# Custom loader (--loader / add-custom-loader)
# ===========================================================================


class TestCustomLoaderCLI(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.csv_path = _write_csv(_sample_df(20))
        self.loader_path = os.path.join(self.tmpdir, "fake_loader.py")
        with open(self.loader_path, "w", encoding="utf-8") as handle:
            handle.write(
                "import pandas as pd\n"
                "def load(path, **kwargs):\n"
                "    return pd.DataFrame({'loader_col': [1, 2, 3], 'y': [0.1, 0.2, 0.3]})\n"
            )

    def tearDown(self):
        import shutil
        _clean(self.csv_path)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_custom_loader_creates_template(self):
        out, err, code = _run_cli(
            "add-custom-loader", "my_ingest", "--dir", self.tmpdir
        )
        self.assertEqual(code, 0, msg=err or out)
        path = os.path.join(self.tmpdir, "my_ingest.py")
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("def load", body)

    def test_run_completeness_with_loader(self):
        out, err, code = _run_cli(
            "run",
            "completeness",
            self.csv_path,
            "--loader",
            f"{self.loader_path}:load",
        )
        self.assertEqual(code, 0, msg=err or out)
        payload = json.loads(out)
        blob = json.dumps(payload)
        self.assertIn("loader_col", blob)

    def test_failed_loader_exits_nonzero(self):
        bad = os.path.join(self.tmpdir, "bad_loader.py")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("def load(path, **kwargs):\n    return None\n")
        # Use an unsupported extension so success cannot come from a built-in reader.
        weird = os.path.join(self.tmpdir, "data.weird")
        with open(weird, "w", encoding="utf-8") as handle:
            handle.write("x")
        out, err, code = _run_cli(
            "run",
            "completeness",
            weird,
            "--loader",
            f"{bad}:load",
        )
        self.assertNotEqual(code, 0)
        combined = (err or "") + (out or "")
        self.assertIn("Custom loader", combined)
        self.assertIn("None", combined)


# ===========================================================================
# Frame cache cleanup
# ===========================================================================


def _frame_cache_siblings(path: str) -> list[str]:
    directory = os.path.dirname(path) or "."
    prefix = os.path.basename(path)
    return [f for f in os.listdir(directory) if f.startswith(prefix) and f.endswith(".aidrin.feather")]


class TestFrameCacheCleanup(unittest.TestCase):
    """The CLI reads files from arbitrary disk locations with no periodic
    reaper (unlike the web app's managed upload folder), so it must remove
    its own ``.aidrin.feather`` cache sidecar after each invocation."""

    def setUp(self):
        self.csv = _write_csv(_sample_df())

    def tearDown(self):
        for name in _frame_cache_siblings(self.csv):
            _clean(os.path.join(os.path.dirname(self.csv) or ".", name))
        _clean(self.csv)

    def test_no_cache_sidecar_left_after_run_command(self):
        _run_cli("run", "completeness", self.csv)
        self.assertEqual(_frame_cache_siblings(self.csv), [])

    def test_no_cache_sidecar_left_after_data_quality_command(self):
        _run_cli("data-quality", self.csv)
        self.assertEqual(_frame_cache_siblings(self.csv), [])

    def test_no_cache_sidecar_left_after_failed_run(self):
        # Nonexistent target column still exercises read_file() before failing.
        _run_cli("run", "class-imbalance", self.csv, "not_a_real_column")
        self.assertEqual(_frame_cache_siblings(self.csv), [])


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
