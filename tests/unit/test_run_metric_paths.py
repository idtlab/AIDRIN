"""Round-trip coverage for the two ``run_metric`` branches that inline ``_finalize``.

``aidrin.headless.api.run_metric`` has three shapes of exit: the fast-path metrics,
the custom-metric path, and the registry path that calls ``_finalize``.  The first
two inline a copy of ``_finalize``'s body, and neither had any test exercising it —
``test_cli.py`` covers only argument validation for three registry metrics, and
``test_compute_executor.py``'s ``completeness`` calls go through ``RemoteExecutor``.

These are characterisation tests: they pin current behaviour so the consolidation
of those inlined copies into ``_finalize`` can be shown to change nothing.
"""

import os
import sys
import tempfile
import types
import unittest

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

from aidrin.headless.api import generate_metric_template, run_metric  # noqa: E402


def _write_csv() -> str:
    df = pd.DataFrame(
        {
            "age": [31, 42, None, 25, 42],
            "city": ["Berkeley", "Oakland", "Berkeley", None, "Oakland"],
            "score": [0.5, 0.7, 0.2, 0.9, 0.7],
        }
    )
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return tmp.name


def _clean(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


class TestFastPathMetrics(unittest.TestCase):
    """The 7 metrics that return before ``_finalize`` is defined."""

    FAST_PATH = [
        "completeness",
        "duplicity",
        "outliers",
        "constant_feature_count",
        "max_pairwise_correlation",
        "skewness",
        "kurtosis",
    ]

    def setUp(self):
        self.csv = _write_csv()

    def tearDown(self):
        _clean(self.csv)

    def test_every_fast_path_metric_returns_a_dict(self):
        for name in self.FAST_PATH:
            with self.subTest(metric=name):
                result = run_metric(name, self.csv, save_images=False)
                self.assertIsInstance(result, dict)
                self.assertNotIn("Error", result)

    def test_completeness_reports_its_headline_score(self):
        result = run_metric("completeness", self.csv, save_images=False)
        self.assertIn("Overall Completeness", result)
        self.assertIsInstance(result["Overall Completeness"], float)

    def test_dashed_metric_name_is_normalised(self):
        dashed = run_metric("constant-feature-count", self.csv, save_images=False)
        underscored = run_metric("constant_feature_count", self.csv, save_images=False)
        self.assertEqual(dashed, underscored)

    def test_strip_visualizations_removes_the_chart(self):
        kept = run_metric("completeness", self.csv, save_images=False)
        stripped = run_metric(
            "completeness", self.csv, save_images=False, strip_visualizations=True
        )
        self.assertIn("Completeness Visualization", kept)
        self.assertNotIn("Completeness Visualization", stripped)

    def test_result_is_json_serialisable(self):
        """_sanitize must run on this path — numpy types would break json.dumps."""
        import json

        result = run_metric("completeness", self.csv, save_images=False)
        json.dumps(result)


class TestCustomMetricPath(unittest.TestCase):
    """The branch guarded by ``except FileNotFoundError -> ValueError``."""

    def setUp(self):
        self.csv = _write_csv()
        self.dir = tempfile.mkdtemp()
        generate_metric_template("roundtrip_probe", self.dir)
        # run_custom_metric_logic resolves scripts by searching the cwd
        self._prev_cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self._prev_cwd)
        _clean(self.csv)

    def test_custom_metric_runs_through_run_metric(self):
        result = run_metric("roundtrip_probe", self.csv, save_images=False)
        self.assertIsInstance(result, dict)

    def test_unknown_metric_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            run_metric("no_such_metric_anywhere", self.csv, save_images=False)
        self.assertIn("Unknown metric", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
