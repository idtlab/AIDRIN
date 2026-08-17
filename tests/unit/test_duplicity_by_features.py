"""Unit tests for the duplicity_by_features data-quality metric."""

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

from aidrin.structured_data_metrics.duplicity_by_features import (  # noqa: E402
    duplicity_by_features,
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


class TestDuplicityByFeatures(unittest.TestCase):

    def test_happy_path(self):
        # 6 rows, subset ["dept", "region"]:
        #   ("eng","us") x2 (rows 0,1) -> duplicate group, 1 duplicate row
        #   ("eng","eu") x1 (row 2)
        #   ("sales","us") x2 (rows 3,4) -> duplicate group, 1 duplicate row
        #   ("hr","eu") x1 (row 5)
        # -> 2 duplicate rows / 6 total = 33.33%
        df = pd.DataFrame({
            "dept": ["eng", "eng", "eng", "sales", "sales", "hr"],
            "region": ["us", "us", "eu", "us", "us", "eu"],
            "id": [1, 2, 3, 4, 5, 6],
        })
        fi = _write_csv(df)
        try:
            result = duplicity_by_features.apply(
                args=(["dept", "region"], fi)).get()
        finally:
            _clean(fi[0])

        self.assertNotIn("Error", result)
        self.assertEqual(result["Duplicate count"], 2)
        self.assertEqual(result["Total rows"], 6)
        self.assertAlmostEqual(result["Duplicate percentage"], 33.333333, places=4)

        groups = result["Duplicate groups"]
        self.assertEqual(len(groups), 2)
        seen = {
            (g["Feature values"]["dept"], g["Feature values"]["region"]): g["Row count"]
            for g in groups
        }
        self.assertEqual(seen, {("eng", "us"): 2, ("sales", "us"): 2})

    def test_no_duplicates(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        fi = _write_csv(df)
        try:
            result = duplicity_by_features.apply(args=(["a", "b"], fi)).get()
        finally:
            _clean(fi[0])

        self.assertEqual(result["Duplicate count"], 0)
        self.assertAlmostEqual(result["Duplicate percentage"], 0.0)
        self.assertEqual(result["Duplicate groups"], [])

    def test_empty_features_error(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        fi = _write_csv(df)
        try:
            result = duplicity_by_features.apply(args=([], fi)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)

    def test_missing_column_error(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        fi = _write_csv(df)
        try:
            result = duplicity_by_features.apply(
                args=(["a", "does_not_exist"], fi)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)

    def test_empty_dataset_error(self):
        df = pd.DataFrame({"a": [], "b": []})
        fi = _write_csv(df)
        try:
            result = duplicity_by_features.apply(args=(["a", "b"], fi)).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)

    def test_top_n_capping(self):
        # 1 group of size 5 ("big"), plus 15 groups of size 2 each
        # ("g0".."g14") = 16 duplicate groups total, more than the default
        # top_n=10. The "big" group must survive the cap since it's strictly
        # larger than every other group.
        rows = ["big"] * 5
        for i in range(15):
            rows += [f"g{i}"] * 2
        df = pd.DataFrame({"k": rows})
        fi = _write_csv(df)
        try:
            result = duplicity_by_features.apply(args=(["k"], fi)).get()
        finally:
            _clean(fi[0])

        groups = result["Duplicate groups"]
        self.assertEqual(len(groups), 10)
        self.assertEqual(groups[0]["Feature values"]["k"], "big")
        self.assertEqual(groups[0]["Row count"], 5)

    def test_nan_values_grouped_together(self):
        # Rows with NaN in the selected feature should still be grouped
        # (dropna=False), not silently excluded from duplicate detection.
        df = pd.DataFrame({"a": [None, None, 1, 2], "b": [1, 1, 2, 3]})
        fi = _write_csv(df)
        try:
            result = duplicity_by_features.apply(args=(["a", "b"], fi)).get()
        finally:
            _clean(fi[0])

        self.assertEqual(result["Duplicate count"], 1)
        groups = result["Duplicate groups"]
        self.assertEqual(len(groups), 1)
        self.assertIsNone(groups[0]["Feature values"]["a"])
        self.assertEqual(groups[0]["Row count"], 2)


if __name__ == "__main__":
    unittest.main()
