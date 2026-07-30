"""Tests for the shared unhashable-value normalization helper.

Regression coverage for datasets whose object columns hold arrays/lists/dicts
(routine in parquet, HDF5 and JSON). Before this helper, nunique()/duplicated()/
value_counts() raised TypeError on such columns, breaking the duplicity metric
and the web summary.
"""

import os
import sys
import tempfile
import types
import unittest

import numpy as np
import pandas as pd

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

from aidrin.file_handling.hashable_utils import (  # noqa: E402
    hashable_frame,
    hashable_series,
    is_unhashable_column,
    make_hashable,
    safe_nunique,
)


class TestMakeHashable(unittest.TestCase):
    def test_ndarray_becomes_tuple(self):
        self.assertEqual(make_hashable(np.array([1, 2, 3])), (1, 2, 3))

    def test_nested_ndarray(self):
        self.assertEqual(make_hashable(np.array([[1, 2], [3, 4]])), ((1, 2), (3, 4)))

    def test_list_and_dict_and_set(self):
        self.assertEqual(make_hashable([1, [2, 3]]), (1, (2, 3)))
        self.assertEqual(make_hashable({"b": 1, "a": 2}), (("a", 2), ("b", 1)))
        self.assertEqual(make_hashable({3, 1, 2}), (1, 2, 3))

    def test_scalars_pass_through(self):
        for v in (1, "x", 2.5, None, True):
            self.assertEqual(make_hashable(v), v)

    def test_equal_arrays_convert_equal(self):
        # Distinct-counting must stay correct after conversion.
        self.assertEqual(make_hashable(np.array([1, 2])), make_hashable(np.array([1, 2])))


class TestColumnHelpers(unittest.TestCase):
    def test_detects_unhashable_column(self):
        arr = pd.Series([np.array([1, 2]), np.array([3, 4])])
        self.assertTrue(is_unhashable_column(arr))
        self.assertFalse(is_unhashable_column(pd.Series([1, 2, 3])))
        self.assertFalse(is_unhashable_column(pd.Series(["a", "b"])))
        self.assertFalse(is_unhashable_column(pd.Series([], dtype=object)))

    def test_hashable_series_enables_nunique(self):
        s = pd.Series([np.array([1, 2]), np.array([1, 2]), np.array([3, 4])])
        with self.assertRaises(TypeError):
            s.nunique()
        self.assertEqual(hashable_series(s).nunique(), 2)

    def test_hashable_frame_enables_duplicated(self):
        df = pd.DataFrame({
            "arr": [np.array([1, 2]), np.array([1, 2]), np.array([9, 9])],
            "x": [1, 1, 2],
        })
        with self.assertRaises(TypeError):
            df.duplicated()
        self.assertEqual(int(hashable_frame(df).duplicated().sum()), 1)

    def test_safe_nunique_handles_both_paths(self):
        self.assertEqual(safe_nunique(pd.Series([1, 1, 2])), 2)
        self.assertEqual(safe_nunique(pd.Series([np.array([1]), np.array([1])])), 1)

    def test_safe_nunique_handles_mixed_column(self):
        # First value is hashable, a later one is not — the first-value probe
        # alone would miss this, so safe_nunique must fall back on TypeError.
        s = pd.Series(["a", np.array([1, 2])], dtype=object)
        self.assertEqual(safe_nunique(s), 2)


class TestDuplicityOnArrayColumns(unittest.TestCase):
    """End-to-end regression: duplicity previously crashed on parquet arrays."""

    def test_duplicity_runs_on_ndarray_parquet(self):
        from celery import Celery

        app = Celery("tests")
        app.conf.update(task_always_eager=True, task_eager_propagates=True)
        app.set_default()
        from aidrin.structured_data_metrics.duplicity import duplicity

        df = pd.DataFrame({
            "arr": [np.array([1, 2]), np.array([1, 2]), np.array([3, 4])],
            "x": [1, 1, 2],
        })
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        df.to_parquet(tmp.name, index=False)
        tmp.close()
        try:
            result = duplicity.apply(
                args=((tmp.name, os.path.basename(tmp.name), ".parquet"),)
            ).get()
        finally:
            os.unlink(tmp.name)
        self.assertIn("Duplicity scores", result)
        score = result["Duplicity scores"]["Overall duplicity of the dataset"]
        self.assertAlmostEqual(float(score), 1 / 3, places=4)


if __name__ == "__main__":
    unittest.main()
