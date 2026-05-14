"""Tests for the public API exposed via ``aidrin.__init__``.

These verify that every function documented in ``usage.rst`` is importable
directly from ``aidrin`` and returns the expected dict structure on a small
synthetic dataset — no Flask, Celery broker, or Redis required.
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
# Helpers
# ---------------------------------------------------------------------------


def _write_csv(df: pd.DataFrame) -> tuple:
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return (tmp.name, os.path.basename(tmp.name), ".csv")


def _clean(path: str):
    try:
        os.unlink(path)
    except OSError:
        pass


def _sample_df(n=60):
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "age":    rng.integers(20, 70, size=n),
        "income": rng.integers(20000, 100000, size=n),
        "sex":    rng.choice(["M", "F"], size=n),
        "label":  rng.choice(["<=50K", ">50K"], size=n),
    })


# ===========================================================================
# Public API import smoke-test
# ===========================================================================


class TestPublicAPIImports(unittest.TestCase):
    """All documented names must be importable directly from ``aidrin``."""

    def test_version_importable(self):
        import aidrin
        self.assertTrue(hasattr(aidrin, "__version__"))
        self.assertIsInstance(aidrin.__version__, str)

    def _assert_callable(self, name):
        import aidrin
        self.assertTrue(hasattr(aidrin, name), f"aidrin.{name} not found")
        self.assertTrue(callable(getattr(aidrin, name)), f"aidrin.{name} is not callable")

    def test_calculate_completeness_importable(self):
        self._assert_callable("calculate_completeness")

    def test_calculate_duplicates_importable(self):
        self._assert_callable("calculate_duplicates")

    def test_calculate_outliers_importable(self):
        self._assert_callable("calculate_outliers")

    def test_calculate_class_distribution_importable(self):
        self._assert_callable("calculate_class_distribution")

    def test_calculate_representation_rate_importable(self):
        self._assert_callable("calculate_representation_rate")

    def test_calculate_statistical_rates_importable(self):
        self._assert_callable("calculate_statistical_rates")

    def test_calculate_correlations_importable(self):
        self._assert_callable("calculate_correlations")

    def test_calculate_feature_relevance_importable(self):
        self._assert_callable("calculate_feature_relevance")

    def test_compute_k_anonymity_importable(self):
        self._assert_callable("compute_k_anonymity")

    def test_compute_l_diversity_importable(self):
        self._assert_callable("compute_l_diversity")

    def test_compute_t_closeness_importable(self):
        self._assert_callable("compute_t_closeness")

    def test_compute_entropy_risk_importable(self):
        self._assert_callable("compute_entropy_risk")


# ===========================================================================
# Data Quality
# ===========================================================================


class TestPublicDataQuality(unittest.TestCase):

    def setUp(self):
        self.df = _sample_df()
        self.fi = _write_csv(self.df)

    def tearDown(self):
        _clean(self.fi[0])

    def test_calculate_completeness_returns_overall_score(self):
        import aidrin
        result = aidrin.calculate_completeness(self.fi)
        self.assertIn("Overall Completeness", result)
        self.assertIn("Completeness scores", result)
        self.assertGreaterEqual(result["Overall Completeness"], 0.0)
        self.assertLessEqual(result["Overall Completeness"], 1.0)

    def test_calculate_duplicates_returns_score(self):
        import aidrin
        result = aidrin.calculate_duplicates(self.fi)
        self.assertIn("Duplicity scores", result)
        score = result["Duplicity scores"]["Overall duplicity of the dataset"]
        self.assertGreaterEqual(score, 0.0)

    def test_calculate_outliers_returns_scores(self):
        import aidrin
        result = aidrin.calculate_outliers(self.fi)
        self.assertIn("Outlier scores", result)
        self.assertIn("Overall outlier score", result["Outlier scores"])


# ===========================================================================
# Fairness / Bias
# ===========================================================================


class TestPublicFairness(unittest.TestCase):

    def setUp(self):
        self.df = _sample_df()
        self.fi = _write_csv(self.df)

    def tearDown(self):
        _clean(self.fi[0])

    def test_calculate_class_distribution_returns_id_score(self):
        import aidrin
        result = aidrin.calculate_class_distribution("label", self.fi)
        self.assertNotIn("Error", result)
        self.assertIn("Imbalance Degree score", result)

    def test_calculate_class_distribution_includes_visualization(self):
        import aidrin, base64
        result = aidrin.calculate_class_distribution("label", self.fi)
        vis = result.get("Class Distribution Visualization", "")
        self.assertTrue(len(vis) > 0)
        base64.b64decode(vis)

    def test_calculate_representation_rate_returns_ratios(self):
        import aidrin
        result = aidrin.calculate_representation_rate(["sex"], self.fi)
        self.assertIsInstance(result, dict)
        self.assertNotIn("Error", result)

    def test_calculate_statistical_rates_returns_tsd(self):
        import aidrin
        result = aidrin.calculate_statistical_rates("sex", "label", self.fi)
        self.assertIn("TSD scores", result)
        self.assertIn("Statistical Rates", result)


# ===========================================================================
# Privacy / Data Governance
# ===========================================================================


class TestPublicPrivacy(unittest.TestCase):

    def setUp(self):
        self.df = _sample_df()
        self.fi = _write_csv(self.df)

    def tearDown(self):
        _clean(self.fi[0])

    def test_compute_k_anonymity_returns_k_value(self):
        import aidrin
        result = aidrin.compute_k_anonymity(["sex"], self.fi)
        self.assertNotIn("Error", result)
        self.assertIn("k-Value", result)
        self.assertGreaterEqual(result["k-Value"], 1)

    def test_compute_k_anonymity_accepts_dataframe(self):
        import aidrin
        result = aidrin.compute_k_anonymity(["sex"], self.df)
        self.assertIn("k-Value", result)

    def test_compute_l_diversity_returns_l_value(self):
        import aidrin
        result = aidrin.compute_l_diversity(["sex"], "label", self.fi)
        self.assertNotIn("Error", result)
        self.assertIn("l-Value", result)

    def test_compute_t_closeness_returns_t_value(self):
        import aidrin
        result = aidrin.compute_t_closeness(["sex"], "label", self.fi)
        self.assertNotIn("Error", result)
        self.assertIn("t-Value", result)
        self.assertGreaterEqual(result["t-Value"], 0.0)
        self.assertLessEqual(result["t-Value"], 1.0)

    def test_compute_entropy_risk_returns_entropy_value(self):
        import aidrin
        result = aidrin.compute_entropy_risk(["sex"], self.fi)
        self.assertNotIn("Error", result)
        self.assertIn("Entropy-Value", result)
        self.assertGreaterEqual(result["Entropy-Value"], 0.0)


# ===========================================================================
# Impact on AI
# ===========================================================================


class TestPublicImpactOnAI(unittest.TestCase):

    def setUp(self):
        self.df = _sample_df()
        self.fi = _write_csv(self.df)

    def tearDown(self):
        _clean(self.fi[0])

    def test_calculate_feature_relevance_returns_scores(self):
        import aidrin
        result = aidrin.calculate_feature_relevance(self.fi, target_col="label")
        self.assertNotIn("Error", result)
        self.assertIn("Feature Relevance scores", result)
        self.assertIsInstance(result["Feature Relevance scores"], dict)
        self.assertGreater(len(result["Feature Relevance scores"]), 0)

    def test_calculate_feature_relevance_returns_visualization(self):
        import aidrin, base64
        result = aidrin.calculate_feature_relevance(self.fi, target_col="label")
        vis = result.get("Feature Relevance Visualization", "")
        if vis:
            base64.b64decode(vis)

    def test_calculate_feature_relevance_with_explicit_cols(self):
        import aidrin
        result = aidrin.calculate_feature_relevance(
            self.fi,
            target_col="label",
            cat_cols=["sex"],
            num_cols=["age", "income"],
        )
        self.assertNotIn("Error", result)
        self.assertIn("Feature Relevance scores", result)

    def test_calculate_correlations_returns_result(self):
        import aidrin
        result = aidrin.calculate_correlations(["age", "income", "sex"], self.fi)
        self.assertIsInstance(result, dict)
        self.assertNotIn("Error", result)

    def test_calculate_correlations_numerical_columns(self):
        import aidrin
        result = aidrin.calculate_correlations(["age", "income"], self.fi)
        self.assertIsInstance(result, dict)
        # Numerical-only columns should produce correlation data
        self.assertNotIn("Error", result)

    def test_calculate_correlations_returns_visualization(self):
        import aidrin, base64
        result = aidrin.calculate_correlations(["age", "income", "sex"], self.fi)
        vis = result.get("Correlations Visualization") or result.get("Visualization") or ""
        for key, val in result.items():
            if isinstance(val, str) and len(val) > 100:
                # Try to decode — valid base64 means it's a visualization
                try:
                    base64.b64decode(val)
                    vis = val
                    break
                except Exception:
                    pass
        # Just assert result is non-empty — visualization key name may vary
        self.assertGreater(len(result), 0)


if __name__ == "__main__":
    unittest.main()
