"""Tests for JSON-safe conversion of NumPy/Pandas values."""

import json
import math
import unittest

import numpy as np

from web.routes.metrics import _finite_kpi_values, _grade_label
from web.routes.utils import ensure_json_serializable


class TestEnsureJsonSerializable(unittest.TestCase):
    def test_non_finite_numpy_floats_become_none(self):
        payload = ensure_json_serializable(
            {
                "grade": np.float64("nan"),
                "inf": np.float64("inf"),
                "ninf": np.float64("-inf"),
                "ok": np.float64(0.85),
            }
        )
        self.assertIsNone(payload["grade"])
        self.assertIsNone(payload["inf"])
        self.assertIsNone(payload["ninf"])
        self.assertEqual(payload["ok"], 0.85)
        json.dumps(payload, allow_nan=False)

    def test_non_finite_python_floats_become_none(self):
        payload = ensure_json_serializable(
            {"grade": float("nan"), "inf": float("inf"), "ok": 1.0}
        )
        self.assertIsNone(payload["grade"])
        self.assertIsNone(payload["inf"])
        self.assertEqual(payload["ok"], 1.0)
        json.dumps(payload, allow_nan=False)

    def test_ndarray_with_nan_is_recursively_cleaned(self):
        payload = ensure_json_serializable({"vals": np.array([1.0, np.nan, 3.0])})
        self.assertEqual(payload["vals"], [1.0, None, 3.0])
        json.dumps(payload, allow_nan=False)


class TestGradeLabelNonFinite(unittest.TestCase):
    def test_nan_and_inf_are_unknown_not_poor(self):
        self.assertEqual(_grade_label(None), "unknown")
        self.assertEqual(_grade_label(float("nan")), "unknown")
        self.assertEqual(_grade_label(np.float64("nan")), "unknown")
        self.assertEqual(_grade_label(float("inf")), "unknown")
        self.assertEqual(_grade_label(0.5), "poor")
        self.assertEqual(_grade_label(0.75), "warning")
        self.assertEqual(_grade_label(0.95), "good")

    def test_finite_kpi_values_skip_nan(self):
        kpis = [
            {"value": 1.0},
            {"value": float("nan")},
            {"value": None},
            {"value": 0.5},
        ]
        present = _finite_kpi_values(kpis)
        self.assertEqual(present, [1.0, 0.5])
        grade = sum(present) / len(present)
        self.assertTrue(math.isfinite(grade))
        self.assertEqual(grade, 0.75)


if __name__ == "__main__":
    unittest.main()
