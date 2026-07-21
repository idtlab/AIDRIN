"""Unit tests for the constant_feature_count data-quality metric."""

import os
import sys
import tempfile
import types
import unittest

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

from aidrin.structured_data_metrics.constant_feature_count import (  # noqa: E402
    constant_feature_count,
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


class TestConstantFeatureCount(unittest.TestCase):

    def test_no_constant_features(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        fi = _write_csv(df)
        try:
            result = constant_feature_count.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        self.assertEqual(result["Constant feature count"], 0)
        self.assertEqual(result["Total features"], 2)
        self.assertEqual(result["Constant features"], {})

    def test_one_constant_feature_reports_its_value(self):
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "region": ["us", "us", "us"],
        })
        fi = _write_csv(df)
        try:
            result = constant_feature_count.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        self.assertEqual(result["Constant feature count"], 1)
        self.assertEqual(result["Total features"], 2)
        self.assertEqual(result["Constant features"], {"region": "us"})

    def test_multiple_constant_features_report_their_values(self):
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "region": ["us", "us", "us"],
            "status": ["active", "active", "active"],
            "score": [3.5, 3.5, 3.5],
        })
        fi = _write_csv(df)
        try:
            result = constant_feature_count.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        self.assertEqual(result["Constant feature count"], 3)
        self.assertEqual(
            result["Constant features"],
            {"region": "us", "status": "active", "score": 3.5},
        )

    def test_value_plus_nulls_not_constant(self):
        # One real value ("us") plus nulls: null counts as its own distinct
        # value, so this column has two distinct values (("us", null)) and
        # is not constant.
        df = pd.DataFrame({
            "region": ["us", None, "us", None],
        })
        fi = _write_csv(df)
        try:
            result = constant_feature_count.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        self.assertEqual(result["Constant feature count"], 0)
        self.assertEqual(result["Constant features"], {})

    def test_all_null_column_is_constant_with_null_value(self):
        # An all-null column has exactly one distinct value (null), so it
        # counts as constant — null is treated as a value like any other,
        # and its reported value is null.
        df = pd.DataFrame({
            "region": [None, None, None],
            "id": [1, 2, 3],
        })
        fi = _write_csv(df)
        try:
            result = constant_feature_count.apply(args=(fi,)).get()
        finally:
            _clean(fi[0])

        self.assertEqual(result["Constant feature count"], 1)
        self.assertEqual(result["Constant features"], {"region": None})


if __name__ == "__main__":
    unittest.main()
