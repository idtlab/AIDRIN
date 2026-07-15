"""Unit tests for the newly-added data-quality metrics.

Covers row_level_completeness, feature_coverage_ratio, temporal_completeness,
and null_count_trend.  Mirrors the style of test_data_quality.py: a minimal
always-eager Celery app, the ``_write_csv`` / ``_clean`` helpers, and invoking
the task via ``metric.apply(args=(...)).get()``.
"""

import base64
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

from aidrin.structured_data_metrics.row_level_completeness import (  # noqa: E402
    row_level_completeness,
)
from aidrin.structured_data_metrics.feature_coverage_ratio import (  # noqa: E402
    feature_coverage_ratio,
)
from aidrin.structured_data_metrics.temporal_completeness import (  # noqa: E402
    temporal_completeness,
)
from aidrin.structured_data_metrics.null_count_trend import (  # noqa: E402
    null_count_trend,
)


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


def _is_base64(s):
    """True if *s* is a non-empty, decodable base64 string."""
    if not s:
        return False
    base64.b64decode(s)
    return True


# ===========================================================================
# row_level_completeness
# ===========================================================================


class TestRowLevelCompleteness(unittest.TestCase):

    def test_happy_path(self):
        # 4 rows; required cols age+income. Rows missing any required col:
        #   row0: both present
        #   row1: age missing
        #   row2: income missing
        #   row3: both present
        # → 2 complete rows / 4 = 50%
        df = pd.DataFrame({
            "age": [25, None, 35, 40],
            "income": [50000, 60000, None, 80000],
            "note": ["a", "b", "c", "d"],
        })
        fi = _write_csv(df)
        try:
            result = row_level_completeness.apply(
                args=(["age", "income"], fi)).get()
        finally:
            _clean(fi[0])

        self.assertNotIn("Error", result)
        self.assertAlmostEqual(result["Row-Level Completeness (%)"], 50.0)
        self.assertEqual(result["Complete rows"], 2)
        self.assertEqual(result["Total rows"], 4)

    def test_all_rows_complete(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        fi = _write_csv(df)
        try:
            result = row_level_completeness.apply(args=(["a", "b"], fi)).get()
        finally:
            _clean(fi[0])

        self.assertAlmostEqual(result["Row-Level Completeness (%)"], 100.0)
        self.assertEqual(result["Complete rows"], 3)

    def test_empty_required_columns(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        fi = _write_csv(df)
        try:
            result = row_level_completeness.apply(args=([], fi)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)

    def test_missing_required_column(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        fi = _write_csv(df)
        try:
            result = row_level_completeness.apply(
                args=(["a", "does_not_exist"], fi)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)


# ===========================================================================
# feature_coverage_ratio
# ===========================================================================


class TestFeatureCoverageRatio(unittest.TestCase):

    def _mixed_df(self):
        # 10 rows, 4 columns with distinct non-null rates:
        #   full    : 10/10 = 1.00  (>= 0.9)
        #   high    :  9/10 = 0.90  (>= 0.9)
        #   mid     :  5/10 = 0.50  (<  0.9)
        #   low     :  0/10 = 0.00  (<  0.9)
        return pd.DataFrame({
            "full": list(range(10)),
            "high": [1] * 9 + [None],
            "mid": [1] * 5 + [None] * 5,
            "low": [None] * 10,
        })

    def test_threshold_090(self):
        fi = _write_csv(self._mixed_df())
        try:
            result = feature_coverage_ratio.apply(args=(0.9, fi)).get()
        finally:
            _clean(fi[0])

        self.assertNotIn("Error", result)
        # full + high qualify → 2 of 4
        self.assertEqual(result["Covered features"], 2)
        self.assertEqual(result["Total features"], 4)
        self.assertAlmostEqual(result["Feature Coverage Ratio (%)"], 50.0)
        self.assertTrue(
            _is_base64(result["Feature Coverage Ratio Visualization"]))

    def test_threshold_100_counts_only_full(self):
        fi = _write_csv(self._mixed_df())
        try:
            result = feature_coverage_ratio.apply(args=(1.0, fi)).get()
        finally:
            _clean(fi[0])

        # only 'full' is 100% complete
        self.assertEqual(result["Covered features"], 1)
        self.assertAlmostEqual(result["Feature Coverage Ratio (%)"], 25.0)

    def test_threshold_out_of_range(self):
        fi = _write_csv(self._mixed_df())
        try:
            result = feature_coverage_ratio.apply(args=(1.5, fi)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)


# ===========================================================================
# temporal_completeness
# ===========================================================================


class TestTemporalCompleteness(unittest.TestCase):

    def test_daily_with_gap(self):
        # 10 consecutive days, drop one → 9 present / 10 expected = 90%
        days = pd.date_range("2024-01-01", periods=10, freq="D")
        days = days.delete(4)  # remove one interior day
        df = pd.DataFrame({"ts": days.astype(str)})
        fi = _write_csv(df)
        try:
            result = temporal_completeness.apply(args=("ts", "D", fi)).get()
        finally:
            _clean(fi[0])

        self.assertNotIn("Error", result)
        self.assertEqual(result["Expected intervals"], 10)
        self.assertEqual(result["Present intervals"], 9)
        self.assertAlmostEqual(result["Temporal Completeness (%)"], 90.0)
        self.assertTrue(
            _is_base64(result["Temporal Completeness Visualization"]))

    def _two_years_sparse(self):
        # ~2 years of daily timestamps, ~1/3 of days randomly removed. Every
        # month and every week still contains many days, so anchored-frequency
        # completeness must be ~100%.
        rng = np.random.default_rng(42)
        days = pd.date_range("2022-01-01", "2023-12-31", freq="D")
        keep = rng.random(len(days)) > (1 / 3)
        kept = days[keep]
        return pd.DataFrame({"ts": kept.astype(str)})

    def test_anchored_month_end_regression(self):
        # Regression guard: anchored "ME" must not undercount to ~70%.
        fi = _write_csv(self._two_years_sparse())
        try:
            result = temporal_completeness.apply(args=("ts", "ME", fi)).get()
        finally:
            _clean(fi[0])

        self.assertNotIn("Error", result)
        self.assertGreaterEqual(result["Temporal Completeness (%)"], 99.9)

    def test_anchored_weekly_regression(self):
        fi = _write_csv(self._two_years_sparse())
        try:
            result = temporal_completeness.apply(args=("ts", "W", fi)).get()
        finally:
            _clean(fi[0])

        self.assertNotIn("Error", result)
        self.assertGreaterEqual(result["Temporal Completeness (%)"], 99.9)

    def test_subsecond_frequency_no_hang(self):
        # Small dataset with a sub-second frequency must complete quickly and
        # return a numeric percentage (guards the arithmetic-vs-materialize
        # path against exploding for fine frequencies).
        ts = pd.date_range("2024-01-01 00:00:00", periods=20, freq="s")
        df = pd.DataFrame({"ts": ts.astype(str)})
        fi = _write_csv(df)
        try:
            result = temporal_completeness.apply(args=("ts", "s", fi)).get()
        finally:
            _clean(fi[0])

        self.assertNotIn("Error", result)
        self.assertIsInstance(result["Temporal Completeness (%)"], float)

    def test_numeric_column_rejected(self):
        df = pd.DataFrame({"ts": [1704067200, 1704153600, 1704240000]})
        fi = _write_csv(df)
        try:
            result = temporal_completeness.apply(args=("ts", "D", fi)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)


# ===========================================================================
# null_count_trend
# ===========================================================================


class TestNullCountTrend(unittest.TestCase):

    def test_groups_by_batch(self):
        # Two batches; count nulls in a+b per batch.
        #   batch A: a has 1 null, b has 0 → 1
        #   batch B: a has 0 null, b has 1 → 1
        df = pd.DataFrame({
            "batch": ["A", "A", "B", "B"],
            "a": [None, 1, 2, 3],
            "b": [1, 2, 3, None],
        })
        fi = _write_csv(df)
        try:
            result = null_count_trend.apply(
                args=("batch", ["a", "b"], fi)).get()
        finally:
            _clean(fi[0])

        self.assertNotIn("Error", result)
        trend = result["Null counts by batch"]
        self.assertEqual(trend["A"], 1)
        self.assertEqual(trend["B"], 1)

    def test_empty_target_columns_uses_all_others(self):
        # target_columns empty → count nulls across every non-batch column.
        #   batch A: a(1) + b(0) + c(1) = 2
        #   batch B: a(0) + b(1) + c(0) = 1
        df = pd.DataFrame({
            "batch": ["A", "A", "B", "B"],
            "a": [None, 1, 2, 3],
            "b": [1, 2, 3, None],
            "c": [None, 1, 2, 3],
        })
        fi = _write_csv(df)
        try:
            result = null_count_trend.apply(args=("batch", [], fi)).get()
        finally:
            _clean(fi[0])

        trend = result["Null counts by batch"]
        self.assertEqual(trend["A"], 2)
        self.assertEqual(trend["B"], 1)

    def test_high_cardinality_batch_rejected(self):
        # >50 distinct batch values → guarded error.
        df = pd.DataFrame({
            "batch": list(range(60)),
            "v": list(range(60)),
        })
        fi = _write_csv(df)
        try:
            result = null_count_trend.apply(args=("batch", ["v"], fi)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)


if __name__ == "__main__":
    unittest.main()
