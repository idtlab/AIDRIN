"""Unit tests for fairness metrics: representation rate, statistical rate,
class imbalance (imbalance_degree + calc_imbalance_degree).

These tests run without Flask, Celery, or Redis.
"""

import os
import sys
import tempfile
import types
import unittest

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

# ---------------------------------------------------------------------------
# Minimal always-eager Celery app
# ---------------------------------------------------------------------------

from celery import Celery  # noqa: E402

_celery_app = Celery("tests_fairness")
_celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
_celery_app.set_default()

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from aidrin.structured_data_metrics.class_imbalance import (  # noqa: E402
    calc_imbalance_degree,
    class_distribution_plot,
    imbalance_degree,
)
from aidrin.structured_data_metrics.representation_rate import (  # noqa: E402
    calculate_representation_rate,
    create_representation_rate_vis,
)
from aidrin.structured_data_metrics.statistical_rate import (  # noqa: E402
    calculate_statistical_rates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ===========================================================================
# imbalance_degree (pure function)
# ===========================================================================


class TestImbalanceDegree(unittest.TestCase):

    def test_perfectly_balanced_binary(self):
        classes = np.array([0, 0, 0, 1, 1, 1])
        result = imbalance_degree(classes)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.0, places=5)

    def test_perfectly_balanced_multiclass(self):
        classes = np.array([0, 1, 2] * 10)
        result = imbalance_degree(classes)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.0, places=5)

    def test_completely_imbalanced(self):
        # One dominant class, others rare
        classes = np.array([0] * 90 + [1] * 5 + [2] * 5)
        result = imbalance_degree(classes)
        self.assertIsNotNone(result)
        self.assertGreater(result, 0.0)

    def test_single_class_returns_zero(self):
        classes = np.array([1, 1, 1, 1])
        result = imbalance_degree(classes)
        self.assertAlmostEqual(result, 0.0)

    def test_all_distance_metrics(self):
        classes = np.array([0, 0, 1, 1, 1, 2])
        for metric in ["EU", "CH", "KL", "HE", "TV", "CS"]:
            result = imbalance_degree(classes, distance=metric)
            self.assertIsNotNone(result, f"{metric} returned None")

    def test_invalid_distance_raises(self):
        classes = np.array([0, 1, 2])
        with self.assertRaises(ValueError):
            imbalance_degree(classes, distance="INVALID")

    def test_empty_classes_returns_none(self):
        result = imbalance_degree(np.array([]))
        self.assertIsNone(result)


# ===========================================================================
# calc_imbalance_degree (pure function, returns dict with error handling)
# ===========================================================================


class TestCalcImbalanceDegree(unittest.TestCase):

    def _balanced_df(self):
        return pd.DataFrame({"label": ["A", "B"] * 20})

    def test_balanced_returns_score(self):
        result = calc_imbalance_degree(self._balanced_df(), "label")
        self.assertNotIn("Error", result)
        self.assertIn("Imbalance Degree score", result)
        self.assertAlmostEqual(result["Imbalance Degree score"], 0.0, places=5)

    def test_imbalanced_returns_positive_score(self):
        df = pd.DataFrame({"label": ["A"] * 80 + ["B"] * 20})
        result = calc_imbalance_degree(df, "label")
        self.assertNotIn("Error", result)
        self.assertGreater(result["Imbalance Degree score"], 0.0)

    def test_missing_column_returns_error(self):
        result = calc_imbalance_degree(self._balanced_df(), "nonexistent")
        self.assertIn("Error", result)

    def test_empty_dataframe_returns_error(self):
        result = calc_imbalance_degree(pd.DataFrame(), "label")
        self.assertIn("Error", result)

    def test_single_class_returns_error(self):
        df = pd.DataFrame({"label": ["A"] * 10})
        result = calc_imbalance_degree(df, "label")
        self.assertIn("Error", result)

    def test_too_many_unique_numeric_returns_error(self):
        df = pd.DataFrame({"label": np.arange(200, dtype=np.float64)})
        result = calc_imbalance_degree(df, "label")
        self.assertIn("Error", result)

    def test_description_included(self):
        result = calc_imbalance_degree(self._balanced_df(), "label")
        self.assertIn("Description", result)

    def test_custom_distance_metric(self):
        df = pd.DataFrame({"label": ["A", "B", "C"] * 10})
        for metric in ["EU", "KL", "HE"]:
            result = calc_imbalance_degree(df, "label", dist_metric=metric)
            self.assertNotIn("Error", result, f"metric={metric} should not error")


# ===========================================================================
# calculate_representation_rate (Celery task)
# ===========================================================================


class TestRepresentationRate(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame({
            "gender": ["M", "F", "M", "F", "M", "F", "M", "F"],
            "income": [50000, 60000, 70000, 80000, 55000, 65000, 75000, 85000],
        })

    def test_binary_column_ratios(self):
        fi = _write_csv(self.df)
        try:
            result = calculate_representation_rate.apply(
                args=(["gender"], fi)
            ).get()
        finally:
            _clean(fi[0])

        self.assertIsInstance(result, dict)
        # Should have exactly one ratio pair for a binary column
        non_error_keys = [k for k in result if k != "Error"]
        self.assertEqual(len(non_error_keys), 1)
        # Equal counts → ratio should be ~1.0
        ratio = list(result.values())[0]
        self.assertAlmostEqual(ratio, 1.0, places=5)

    def test_multiple_columns(self):
        df = pd.DataFrame({
            "gender": ["M", "F", "M", "F", "M", "F"],
            "age_group": ["young", "old", "young", "old", "young", "old"],
        })
        fi = _write_csv(df)
        try:
            result = calculate_representation_rate.apply(
                args=(["gender", "age_group"], fi)
            ).get()
        finally:
            _clean(fi[0])

        self.assertIsInstance(result, dict)
        self.assertNotIn("Error", result)

    def test_missing_column_returns_error(self):
        fi = _write_csv(self.df)
        try:
            result = calculate_representation_rate.apply(
                args=(["nonexistent"], fi)
            ).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)


# ===========================================================================
# calculate_statistical_rates (Celery task)
# ===========================================================================


class TestStatisticalRates(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame({
            "outcome": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            "gender":  ["M", "M", "M", "M", "M", "M", "F", "F", "F", "F", "F", "F"],
        })

    def test_returns_expected_keys(self):
        fi = _write_csv(self.df)
        try:
            result = calculate_statistical_rates.apply(
                args=("outcome", "gender", fi)
            ).get()
        finally:
            _clean(fi[0])

        self.assertIn("Statistical Rates", result)
        self.assertIn("TSD scores", result)
        self.assertIn("Statistical Rate Visualization", result)

    def test_balanced_groups_low_tsd(self):
        # Both gender groups have 50/50 outcome → TSD ≈ 0
        fi = _write_csv(self.df)
        try:
            result = calculate_statistical_rates.apply(
                args=("outcome", "gender", fi)
            ).get()
        finally:
            _clean(fi[0])

        tsd = result["TSD scores"]
        for class_label, std_val in tsd.items():
            self.assertAlmostEqual(std_val, 0.0, places=5)

    def test_imbalanced_groups_nonzero_tsd(self):
        # M: all class 0; F: all class 1 → maximum imbalance → TSD > 0
        df = pd.DataFrame({
            "outcome": [0] * 8 + [1] * 8,
            "gender":  ["M"] * 8 + ["F"] * 8,
        })
        fi = _write_csv(df)
        try:
            result = calculate_statistical_rates.apply(
                args=("outcome", "gender", fi)
            ).get()
        finally:
            _clean(fi[0])

        tsd = result["TSD scores"]
        total_tsd = sum(tsd.values())
        self.assertGreater(total_tsd, 0.0)

    def test_visualization_is_base64(self):
        import base64
        fi = _write_csv(self.df)
        try:
            result = calculate_statistical_rates.apply(
                args=("outcome", "gender", fi)
            ).get()
        finally:
            _clean(fi[0])

        vis = result.get("Statistical Rate Visualization", "")
        self.assertTrue(len(vis) > 0)
        base64.b64decode(vis)  # raises if not valid base64

    def test_missing_column_returns_error(self):
        fi = _write_csv(self.df)
        try:
            result = calculate_statistical_rates.apply(
                args=("outcome", "nonexistent", fi)
            ).get()
        finally:
            _clean(fi[0])

        self.assertIn("Error", result)


# ===========================================================================
# class_distribution_plot (pure function, returns base64 PNG)
# ===========================================================================


class TestClassDistributionPlot(unittest.TestCase):

    def _balanced_df(self):
        return pd.DataFrame({"label": ["A", "B"] * 20})

    def test_returns_base64_string(self):
        import base64
        result = class_distribution_plot(self._balanced_df(), "label")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)
        base64.b64decode(result)  # raises if invalid

    def test_multiclass_column(self):
        import base64
        df = pd.DataFrame({"label": ["A", "B", "C", "A", "B", "C"] * 5})
        result = class_distribution_plot(df, "label")
        base64.b64decode(result)

    def test_empty_dataframe_raises(self):
        with self.assertRaises((ValueError, Exception)):
            class_distribution_plot(pd.DataFrame(), "label")

    def test_missing_column_raises(self):
        with self.assertRaises((ValueError, Exception)):
            class_distribution_plot(self._balanced_df(), "nonexistent")

    def test_single_class_raises(self):
        df = pd.DataFrame({"label": ["A"] * 10})
        with self.assertRaises((ValueError, Exception)):
            class_distribution_plot(df, "label")

    def test_none_dataframe_raises(self):
        with self.assertRaises((ValueError, Exception)):
            class_distribution_plot(None, "label")

    def test_too_many_classes_raises(self):
        # More than 50 unique values → should raise
        df = pd.DataFrame({"label": [f"class_{i}" for i in range(60)]})
        with self.assertRaises((ValueError, Exception)):
            class_distribution_plot(df, "label")

    def test_imbalanced_classes(self):
        import base64
        df = pd.DataFrame({"label": ["A"] * 40 + ["B"] * 10})
        result = class_distribution_plot(df, "label")
        base64.b64decode(result)


# ===========================================================================
# create_representation_rate_vis (Celery task, returns base64 PNG)
# ===========================================================================


class TestRepresentationRateVisualization(unittest.TestCase):

    def test_returns_base64_string(self):
        import base64
        df = pd.DataFrame({"gender": ["M", "F", "M", "F", "M", "F"] * 4})
        fi = _write_csv(df)
        try:
            result = create_representation_rate_vis.apply(
                args=(["gender"], fi)
            ).get()
        finally:
            _clean(fi[0])

        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)
        base64.b64decode(result)

    def test_multiclass_column(self):
        import base64
        df = pd.DataFrame({"age_group": ["young", "mid", "old", "young", "mid", "old"] * 3})
        fi = _write_csv(df)
        try:
            result = create_representation_rate_vis.apply(
                args=(["age_group"], fi)
            ).get()
        finally:
            _clean(fi[0])

        base64.b64decode(result)

    def test_missing_column_returns_error(self):
        df = pd.DataFrame({"gender": ["M", "F", "M"]})
        fi = _write_csv(df)
        try:
            result = create_representation_rate_vis.apply(
                args=(["nonexistent"], fi)
            ).get()
        finally:
            _clean(fi[0])

        self.assertIsInstance(result, dict)
        self.assertIn("Error", result)


if __name__ == "__main__":
    unittest.main()
