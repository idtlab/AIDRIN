"""Unit tests for non-CSV file readers: JSON and NPZ.

These tests run without Flask, Celery, or Redis.

jsonReader.filter() is excluded — it calls session/current_app and requires
a full Flask application context.
"""

import json
import logging
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from aidrin.file_handling.readers.json_reader import jsonReader
from aidrin.file_handling.readers.npz_reader import npzReader

_log = logging.getLogger("test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(data) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump(data, tmp)
    tmp.close()
    return tmp.name


def _write_npz(**arrays) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".npz", delete=False)
    tmp.close()
    np.savez(tmp.name, **arrays)
    # np.savez appends .npz if not already present; handle both cases
    path = tmp.name if os.path.exists(tmp.name) else tmp.name + ".npz"
    return path


def _clean(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ===========================================================================
# jsonReader
# ===========================================================================


class TestJsonReaderRead(unittest.TestCase):

    def test_flat_list_of_dicts(self):
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        path = _write_json(data)
        try:
            df = jsonReader(path, _log).read()
        finally:
            _clean(path)

        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(list(df.columns), ["a", "b"])
        self.assertEqual(len(df), 2)
        self.assertEqual(df["a"].tolist(), [1, 3])

    def test_nested_dict_with_list_values(self):
        # Typical JSON: top-level dict whose values are lists of records
        data = {
            "group1": [{"x": 1}, {"x": 2}],
            "group2": [{"x": 3}, {"x": 4}],
        }
        path = _write_json(data)
        try:
            df = jsonReader(path, _log).read()
        finally:
            _clean(path)

        self.assertIsInstance(df, pd.DataFrame)
        self.assertIn("x", df.columns)
        self.assertEqual(len(df), 4)

    def test_empty_list_returns_empty_dataframe(self):
        path = _write_json([])
        try:
            df = jsonReader(path, _log).read()
        finally:
            _clean(path)

        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), 0)

    def test_single_record_list(self):
        path = _write_json([{"name": "Alice", "score": 95}])
        try:
            df = jsonReader(path, _log).read()
        finally:
            _clean(path)

        self.assertEqual(len(df), 1)
        self.assertEqual(df["name"].iloc[0], "Alice")

    def test_extra_fields_become_nan(self):
        data = [{"a": 1, "b": 2}, {"a": 3}]  # second record missing "b"
        path = _write_json(data)
        try:
            df = jsonReader(path, _log).read()
        finally:
            _clean(path)

        self.assertEqual(len(df), 2)
        self.assertTrue(pd.isna(df["b"].iloc[1]))

    def test_missing_file_raises(self):
        with self.assertRaises(Exception):
            jsonReader("/nonexistent/path/file.json", _log).read()


class TestJsonReaderParse(unittest.TestCase):

    def test_dict_returns_keys(self):
        data = {"alpha": [1, 2], "beta": [3, 4], "gamma": [5, 6]}
        path = _write_json(data)
        try:
            keys = jsonReader(path, _log).parse()
        finally:
            _clean(path)

        self.assertIsNotNone(keys)
        self.assertCountEqual(keys, ["alpha", "beta", "gamma"])

    def test_keys_are_strings(self):
        # Even numeric-like keys should come back as strings
        data = {"1": [1], "2": [2]}
        path = _write_json(data)
        try:
            keys = jsonReader(path, _log).parse()
        finally:
            _clean(path)

        for k in keys:
            self.assertIsInstance(k, str)

    def test_list_input_returns_none(self):
        # parse() only handles top-level dicts
        path = _write_json([{"a": 1}])
        try:
            result = jsonReader(path, _log).parse()
        finally:
            _clean(path)

        self.assertIsNone(result)

    def test_empty_dict_returns_empty_list(self):
        path = _write_json({})
        try:
            keys = jsonReader(path, _log).parse()
        finally:
            _clean(path)

        # Empty dict → empty key list (or None — either is acceptable)
        self.assertTrue(keys is None or keys == [])


# ===========================================================================
# npzReader
# ===========================================================================


class TestNpzReaderRead(unittest.TestCase):

    def test_basic_arrays(self):
        path = _write_npz(x=np.array([1, 2, 3]), y=np.array([4, 5, 6]))
        try:
            df = npzReader(path, _log).read()
        finally:
            _clean(path)

        self.assertIsInstance(df, pd.DataFrame)
        self.assertIn("x", df.columns)
        self.assertIn("y", df.columns)
        self.assertEqual(len(df), 3)

    def test_column_names_are_strings(self):
        path = _write_npz(a=np.array([1, 2]), b=np.array([3, 4]))
        try:
            df = npzReader(path, _log).read()
        finally:
            _clean(path)

        for col in df.columns:
            self.assertIsInstance(col, str)

    def test_float_array(self):
        path = _write_npz(vals=np.array([1.1, 2.2, 3.3]))
        try:
            df = npzReader(path, _log).read()
        finally:
            _clean(path)

        self.assertAlmostEqual(df["vals"].iloc[0], 1.1, places=5)

    def test_2d_array_flattened_to_list_column(self):
        # 2-D arrays get converted via .tolist() → column of lists
        path = _write_npz(mat=np.array([[1, 2], [3, 4], [5, 6]]))
        try:
            df = npzReader(path, _log).read()
        finally:
            _clean(path)

        self.assertIsInstance(df, pd.DataFrame)
        self.assertIn("mat", df.columns)

    def test_multiple_arrays_same_length(self):
        n = 10
        path = _write_npz(
            age=np.arange(n),
            score=np.random.default_rng(0).random(n),
        )
        try:
            df = npzReader(path, _log).read()
        finally:
            _clean(path)

        self.assertEqual(len(df), n)
        self.assertIn("age", df.columns)
        self.assertIn("score", df.columns)

    def test_missing_file_raises(self):
        with self.assertRaises(Exception):
            npzReader("/nonexistent/path/file.npz", _log).read()


if __name__ == "__main__":
    unittest.main()
