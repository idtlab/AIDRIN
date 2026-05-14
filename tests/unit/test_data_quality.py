"""Unit tests for data quality metrics: completeness, duplicity, outliers.

These tests run without Flask, Celery, or Redis.  Celery tasks are invoked via
.apply() after configuring a minimal always-eager Celery app so the task
decorator is satisfied without a running broker.
"""

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


# ---------------------------------------------------------------------------
# Minimal always-eager Celery app so shared_task decorators resolve cleanly
# ---------------------------------------------------------------------------

from celery import Celery  # noqa: E402

_celery_app = Celery("tests")
_celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
_celery_app.set_default()

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from aidrin.structured_data_metrics.completeness import completeness  # noqa: E402
from aidrin.structured_data_metrics.duplicity import duplicity  # noqa: E402
from aidrin.structured_data_metrics.outliers import outliers  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv(df: pd.DataFrame) -> tuple:
    """Write *df* to a temp CSV and return a file_info tuple."""
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return (tmp.name, os.path.basename(tmp.name), ".csv")


def _clean(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ===========================================================================
# completeness
# ===========================================================================


class TestCompleteness(unittest.TestCase):

    def setUp(self):
        self.df_full = pd.DataFrame({
            "age": [25, 30, 35, 40],
            "income": [50000, 60000, 70000, 80000],
        })
        self.df_missing = pd.DataFrame({
            "age": [25, None, 35, None],
            "income": [50000, 60000, None, 80000],
        })

    def test_perfect_completeness(self):
        fi = _write_csv(self.df_full)
        try:
            result = completeness.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Completeness scores", result)
        self.assertIn("Overall Completeness", result)
        scores = result["Completeness scores"]
        for col in ["age", "income"]:
            self.assertAlmostEqual(scores[col], 1.0)
        self.assertAlmostEqual(result["Overall Completeness"], 1.0)

    def test_partial_completeness(self):
        fi = _write_csv(self.df_missing)
        try:
            result = completeness.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        scores = result["Completeness scores"]
        # 2 out of 4 missing in 'age' → 0.5
        self.assertAlmostEqual(scores["age"], 0.5)
        # 1 out of 4 missing in 'income' → 0.75
        self.assertAlmostEqual(scores["income"], 0.75)
        # overall: rows with any missing / total = 3/4 missing → 0.25 complete
        self.assertAlmostEqual(result["Overall Completeness"], 0.25)

    def test_visualization_is_base64(self):
        fi = _write_csv(self.df_full)
        try:
            result = completeness.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        import base64
        vis = result.get("Completeness Visualization", "")
        self.assertTrue(len(vis) > 0)
        # Should be valid base64
        base64.b64decode(vis)

    def test_all_missing_column(self):
        df = pd.DataFrame({"a": [None, None, None], "b": [1, 2, 3]})
        fi = _write_csv(df)
        try:
            result = completeness.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        scores = result["Completeness scores"]
        self.assertAlmostEqual(scores["a"], 0.0)
        self.assertAlmostEqual(scores["b"], 1.0)


# ===========================================================================
# duplicity
# ===========================================================================


class TestDuplicity(unittest.TestCase):

    def test_no_duplicates(self):
        df = pd.DataFrame({"x": [1, 2, 3, 4], "y": ["a", "b", "c", "d"]})
        fi = _write_csv(df)
        try:
            result = duplicity.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Duplicity scores", result)
        score = result["Duplicity scores"]["Overall duplicity of the dataset"]
        self.assertAlmostEqual(score, 0.0)

    def test_all_duplicates(self):
        df = pd.DataFrame({"x": [1, 1, 1, 1], "y": ["a", "a", "a", "a"]})
        fi = _write_csv(df)
        try:
            result = duplicity.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        score = result["Duplicity scores"]["Overall duplicity of the dataset"]
        # 3 out of 4 rows are duplicates
        self.assertAlmostEqual(score, 0.75)

    def test_partial_duplicates(self):
        df = pd.DataFrame({"x": [1, 2, 1, 3], "y": ["a", "b", "a", "c"]})
        fi = _write_csv(df)
        try:
            result = duplicity.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        score = result["Duplicity scores"]["Overall duplicity of the dataset"]
        # 1 duplicate row out of 4
        self.assertAlmostEqual(score, 0.25)

    def test_single_row(self):
        df = pd.DataFrame({"x": [42]})
        fi = _write_csv(df)
        try:
            result = duplicity.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        score = result["Duplicity scores"]["Overall duplicity of the dataset"]
        self.assertAlmostEqual(score, 0.0)


# ===========================================================================
# outliers
# ===========================================================================


class TestOutliers(unittest.TestCase):

    def test_no_outliers(self):
        # Tightly clustered data — no IQR outliers
        df = pd.DataFrame({"val": [10, 11, 10, 12, 11, 10, 11, 12] * 5})
        fi = _write_csv(df)
        try:
            result = outliers.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Outlier scores", result)
        score = result["Outlier scores"]["val"]
        self.assertAlmostEqual(score, 0.0)

    def test_clear_outlier(self):
        # Spread data with one extreme value — IQR > 0 so outlier is detected
        values = list(range(1, 21)) + [1000]
        df = pd.DataFrame({"val": values})
        fi = _write_csv(df)
        try:
            result = outliers.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        score = result["Outlier scores"]["val"]
        self.assertGreater(score, 0.0)

    def test_no_numerical_columns(self):
        df = pd.DataFrame({"name": ["Alice", "Bob", "Carol"]})
        fi = _write_csv(df)
        try:
            result = outliers.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)

    def test_zero_iqr_column(self):
        # Constant column → IQR = 0 → no outliers
        df = pd.DataFrame({"const": [5, 5, 5, 5, 5, 5]})
        fi = _write_csv(df)
        try:
            result = outliers.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        score = result["Outlier scores"]["const"]
        self.assertAlmostEqual(score, 0.0)

    def test_multiple_numerical_columns(self):
        df = pd.DataFrame({
            "a": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "b": [1, 1, 1, 1, 1, 1, 1, 1, 1, 100],
        })
        fi = _write_csv(df)
        try:
            result = outliers.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        scores = result["Outlier scores"]
        self.assertIn("a", scores)
        self.assertIn("b", scores)
        self.assertIn("Overall outlier score", scores)


if __name__ == "__main__":
    unittest.main()
