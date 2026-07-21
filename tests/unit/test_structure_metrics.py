"""Unit tests for the P3 data-structure metrics.

Covers max_pairwise_correlation, skewness, kurtosis.
Mirrors test_completeness_extras.py: a minimal always-eager Celery app, a
``_write_csv`` helper, and invoking each task via ``.apply(args=(...)).get()``.
"""

import base64
import binascii
import os
import sys
import tempfile
import types
import unittest

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Stubs — must be installed before any aidrin import
# ---------------------------------------------------------------------------

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

from celery import Celery  # noqa: E402

_celery_app = Celery("tests")
_celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
_celery_app.set_default()

from aidrin.structured_data_metrics.max_pairwise_correlation import (  # noqa: E402
    max_pairwise_correlation,
)
from aidrin.structured_data_metrics.skewness import skewness  # noqa: E402
from aidrin.structured_data_metrics.kurtosis import kurtosis  # noqa: E402


def _write_csv(df: pd.DataFrame) -> tuple:
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return (tmp.name, os.path.basename(tmp.name), ".csv")


def _clean(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _is_base64(s):
    try:
        return isinstance(s, str) and len(base64.b64decode(s, validate=True)) > 0
    except (binascii.Error, ValueError):
        return False


class TestMaxPairwiseCorrelation(unittest.TestCase):
    def test_detects_perfect_collinearity(self):
        base = np.arange(50, dtype=float)
        df = pd.DataFrame({
            "a": base,
            "b": base * 2 + 1,   # perfectly correlated with a
            "c": np.sin(base),
        })
        fi = _write_csv(df)
        try:
            result = max_pairwise_correlation.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])
        self.assertAlmostEqual(result["Max Pairwise Correlation"], 1.0, places=6)
        self.assertIn("a ~ b", result["Most Correlated Pair"])
        self.assertTrue(_is_base64(result["Max Pairwise Correlation Visualization"]))

    def test_insufficient_numeric_features_errors(self):
        df = pd.DataFrame({"only": [1, 2, 3], "text": ["a", "b", "c"]})
        fi = _write_csv(df)
        try:
            result = max_pairwise_correlation.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])
        self.assertIn("Error", result)

    def test_disjoint_columns_return_error_not_raise(self):
        # Two non-constant numeric columns with no overlapping non-null rows:
        # every pairwise correlation is NaN. Must return {"Error"}, not raise.
        df = pd.DataFrame({
            "a": [1.0, 2.0, 3.0, np.nan, np.nan, np.nan],
            "b": [np.nan, np.nan, np.nan, 4.0, 5.0, 6.0],
        })
        fi = _write_csv(df)
        try:
            result = max_pairwise_correlation.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])
        self.assertIn("Error", result)


class TestSkewness(unittest.TestCase):
    def test_no_numeric_features_errors(self):
        df = pd.DataFrame({"text": ["a", "b", "c"], "const": [5, 5, 5]})
        fi = _write_csv(df)
        try:
            result = skewness.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])
        self.assertIn("Error", result)

    def test_reports_skew(self):
        df = pd.DataFrame({
            "symmetric": [-2, -1, 0, 1, 2] * 4,
            "right_tail": [1, 1, 1, 1, 100] * 4,
        })
        fi = _write_csv(df)
        try:
            result = skewness.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])
        self.assertIn("right_tail", result["Skewness"])
        self.assertEqual(result["Most Skewed Feature"], "right_tail")
        self.assertGreater(result["Max Absolute Skewness"], 1.0)
        self.assertTrue(_is_base64(result["Skewness Visualization"]))


class TestKurtosis(unittest.TestCase):
    def test_reports_kurtosis(self):
        df = pd.DataFrame({
            "heavy_tail": [0, 0, 0, 0, 0, 0, 0, 0, 50, -50] * 3,
            "uniform_ish": list(range(30)),
        })
        fi = _write_csv(df)
        try:
            result = kurtosis.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])
        self.assertIn("heavy_tail", result["Kurtosis"])
        self.assertEqual(result["Most Extreme Kurtosis Feature"], "heavy_tail")
        self.assertGreater(result["Max Absolute Excess Kurtosis"], 0.0)
        self.assertTrue(_is_base64(result["Kurtosis Visualization"]))

    def test_no_numeric_features_errors(self):
        df = pd.DataFrame({"text": ["a", "b", "c"], "const": [5, 5, 5]})
        fi = _write_csv(df)
        try:
            result = kurtosis.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])
        self.assertIn("Error", result)


if __name__ == "__main__":
    unittest.main()
