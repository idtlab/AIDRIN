"""Unit tests for privacy metrics: MM risk scores (privacy_measure.py).

Tests run without Flask, Celery, or Redis.
The generate_single_attribute_MM_risk_scores function is a plain Python
function (not a Celery task) so it is called directly with DataFrames.
"""

import sys
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
# Imports under test
# ---------------------------------------------------------------------------

from aidrin.structured_data_metrics.privacy_measure import (  # noqa: E402
    generate_single_attribute_MM_risk_scores,
    generate_multiple_attribute_MM_risk_scores,
    compute_k_anonymity,
    compute_l_diversity,
    compute_t_closeness,
    compute_entropy_risk,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n_rows=20, n_categories=4):
    """Return a simple DataFrame suitable for MM risk scoring."""
    rng = np.random.default_rng(42)
    ids = np.arange(n_rows)
    qi = rng.choice([f"cat_{i}" for i in range(n_categories)], size=n_rows)
    return pd.DataFrame({"id": ids, "qi": qi})


# ===========================================================================
# generate_single_attribute_MM_risk_scores
# ===========================================================================


class TestMMRiskScores(unittest.TestCase):

    def test_returns_expected_keys(self):
        df = _make_df()
        result = generate_single_attribute_MM_risk_scores(df, "id", ["qi"])
        self.assertIn("Descriptive statistics of the risk scores", result)
        self.assertIn("Description", result)

    def test_risk_scores_range(self):
        df = _make_df()
        result = generate_single_attribute_MM_risk_scores(df, "id", ["qi"])
        stats = result["Descriptive statistics of the risk scores"]["qi"]
        self.assertGreaterEqual(stats["min"], 0.0)
        self.assertLessEqual(stats["max"], 1.0)

    def test_empty_dataframe_returns_error(self):
        df = pd.DataFrame({"id": [], "qi": []})
        result = generate_single_attribute_MM_risk_scores(df, "id", ["qi"])
        self.assertIn("Error", result)

    def test_missing_id_column_returns_error(self):
        df = _make_df()
        result = generate_single_attribute_MM_risk_scores(df, "nonexistent", ["qi"])
        self.assertIn("Error", result)

    def test_missing_qi_column_returns_error(self):
        df = _make_df()
        result = generate_single_attribute_MM_risk_scores(df, "id", ["nonexistent"])
        self.assertIn("Error", result)

    def test_non_unique_id_column_returns_error(self):
        df = pd.DataFrame({
            "id": [1, 1, 2, 3],
            "qi": ["A", "B", "A", "C"],
        })
        result = generate_single_attribute_MM_risk_scores(df, "id", ["qi"])
        self.assertIn("Error", result)

    def test_single_value_qi_returns_error(self):
        df = pd.DataFrame({
            "id": np.arange(10),
            "qi": ["same_value"] * 10,
        })
        result = generate_single_attribute_MM_risk_scores(df, "id", ["qi"])
        self.assertIn("Error", result)

    def test_high_cardinality_numeric_qi_returns_error(self):
        n = 200
        df = pd.DataFrame({
            "id": np.arange(n),
            "qi": np.arange(n, dtype=np.float64),
        })
        result = generate_single_attribute_MM_risk_scores(df, "id", ["qi"])
        self.assertIn("Error", result)
        self.assertIn("numerical", result["Error"].lower())

    def test_multiple_qi_columns(self):
        rng = np.random.default_rng(0)
        n = 30
        df = pd.DataFrame({
            "id": np.arange(n),
            "qi1": rng.choice(["A", "B", "C"], size=n),
            "qi2": rng.choice(["X", "Y"], size=n),
        })
        result = generate_single_attribute_MM_risk_scores(df, "id", ["qi1", "qi2"])
        self.assertNotIn("Error", result)
        stats = result["Descriptive statistics of the risk scores"]
        self.assertIn("qi1", stats)
        self.assertIn("qi2", stats)

    def test_task_progress_callback_optional(self):
        """task=None is the default and must not raise."""
        df = _make_df()
        result = generate_single_attribute_MM_risk_scores(df, "id", ["qi"], task=None)
        self.assertNotIn("Error", result)

    def test_visualization_is_base64(self):
        import base64
        df = _make_df()
        result = generate_single_attribute_MM_risk_scores(df, "id", ["qi"])
        vis = result.get("Single attribute risk scoring Visualization", "")
        if vis:
            base64.b64decode(vis)

    def test_descriptive_stats_keys(self):
        df = _make_df()
        result = generate_single_attribute_MM_risk_scores(df, "id", ["qi"])
        stats = result["Descriptive statistics of the risk scores"]["qi"]
        for key in ["mean", "std", "min", "25%", "50%", "75%", "max"]:
            self.assertIn(key, stats)

    def test_narrow_dtypes_rejected(self):
        """float32 / int32 columns with high cardinality must be rejected."""
        n = 200
        for dtype in [np.float32, np.int32, np.uint16]:
            df = pd.DataFrame({
                "id": np.arange(n),
                "qi": np.arange(n, dtype=dtype),
            })
            result = generate_single_attribute_MM_risk_scores(df, "id", ["qi"])
            self.assertIn("Error", result, f"dtype={dtype} should be rejected")


# ===========================================================================
# generate_multiple_attribute_MM_risk_scores
# ===========================================================================


class TestMultipleAttributeMMRiskScores(unittest.TestCase):

    def _make_df(self, n=30):
        rng = np.random.default_rng(7)
        return pd.DataFrame({
            "id": np.arange(n),
            "qi1": rng.choice(["A", "B", "C"], size=n),
            "qi2": rng.choice(["X", "Y"], size=n),
        })

    def test_returns_expected_keys(self):
        df = self._make_df()
        result = generate_multiple_attribute_MM_risk_scores(df, "id", ["qi1", "qi2"])
        self.assertNotIn("Error", result)
        for key in [
            "Descriptive statistics of the risk scores",
            "Multiple attribute risk scoring Visualization",
            "Dataset Risk Score",
            "Description",
        ]:
            self.assertIn(key, result)

    def test_risk_score_in_range(self):
        df = self._make_df()
        result = generate_multiple_attribute_MM_risk_scores(df, "id", ["qi1", "qi2"])
        stats = result["Descriptive statistics of the risk scores"]
        self.assertGreaterEqual(stats["min"], 0.0)
        self.assertLessEqual(stats["max"], 1.0)

    def test_dataset_risk_score_in_range(self):
        df = self._make_df()
        result = generate_multiple_attribute_MM_risk_scores(df, "id", ["qi1", "qi2"])
        score = result["Dataset Risk Score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_single_qi_column(self):
        df = self._make_df()
        result = generate_multiple_attribute_MM_risk_scores(df, "id", ["qi1"])
        self.assertNotIn("Error", result)

    def test_string_eval_cols(self):
        df = self._make_df()
        result = generate_multiple_attribute_MM_risk_scores(df, "id", "qi1,qi2")
        self.assertNotIn("Error", result)

    def test_empty_dataframe_returns_error(self):
        df = pd.DataFrame({"id": [], "qi1": [], "qi2": []})
        result = generate_multiple_attribute_MM_risk_scores(df, "id", ["qi1", "qi2"])
        self.assertIn("Error", result)

    def test_missing_id_column_returns_error(self):
        df = self._make_df()
        result = generate_multiple_attribute_MM_risk_scores(df, "missing", ["qi1"])
        self.assertIn("Error", result)

    def test_missing_qi_column_returns_error(self):
        df = self._make_df()
        result = generate_multiple_attribute_MM_risk_scores(df, "id", ["nonexistent"])
        self.assertIn("Error", result)

    def test_non_unique_id_returns_error(self):
        df = pd.DataFrame({
            "id": [1, 1, 2, 3],
            "qi1": ["A", "B", "A", "C"],
        })
        result = generate_multiple_attribute_MM_risk_scores(df, "id", ["qi1"])
        self.assertIn("Error", result)

    def test_visualization_is_base64(self):
        import base64
        df = self._make_df()
        result = generate_multiple_attribute_MM_risk_scores(df, "id", ["qi1", "qi2"])
        vis = result.get("Multiple attribute risk scoring Visualization", "")
        if vis:
            base64.b64decode(vis)


# ===========================================================================
# compute_k_anonymity
# ===========================================================================


class TestKAnonymity(unittest.TestCase):

    def _make_df(self):
        return pd.DataFrame({
            "age":    ["20-30", "20-30", "30-40", "30-40", "30-40", "40-50"],
            "gender": ["M",     "F",     "M",     "M",     "F",     "F"],
            "salary": ["low",   "high",  "low",   "high",  "low",   "high"],
        })

    def test_returns_expected_keys(self):
        result = compute_k_anonymity(["age", "gender"], self._make_df())
        self.assertNotIn("Error", result)
        for key in ["k-Value", "descriptive_statistics", "k-Anonymity Visualization"]:
            self.assertIn(key, result)

    def test_k_value_is_min_group_size(self):
        result = compute_k_anonymity(["age", "gender"], self._make_df())
        # (20-30,M)=1, (20-30,F)=1, (30-40,M)=2, (30-40,F)=1, (40-50,F)=1 → min=1
        self.assertEqual(result["k-Value"], 1)

    def test_high_k_with_homogeneous_groups(self):
        df = pd.DataFrame({
            "group": ["A"] * 5 + ["B"] * 5,
        })
        result = compute_k_anonymity(["group"], df)
        self.assertEqual(result["k-Value"], 5)

    def test_empty_dataframe_returns_error(self):
        result = compute_k_anonymity(["age"], pd.DataFrame({"age": []}))
        self.assertIn("Error", result)

    def test_missing_qi_column_returns_error(self):
        result = compute_k_anonymity(["nonexistent"], self._make_df())
        self.assertIn("Error", result)

    def test_placeholder_missing_values_handled(self):
        df = pd.DataFrame({"qi": ["A", "?", "A", "B", "B"]})
        result = compute_k_anonymity(["qi"], df)
        self.assertNotIn("Error", result)
        # "?" rows dropped → A:2, B:2 → k=2
        self.assertEqual(result["k-Value"], 2)

    def test_descriptive_stats_present(self):
        result = compute_k_anonymity(["age"], self._make_df())
        stats = result["descriptive_statistics"]
        for key in ["min", "max", "mean", "median"]:
            self.assertIn(key, stats)

    def test_visualization_is_base64(self):
        import base64
        result = compute_k_anonymity(["age", "gender"], self._make_df())
        vis = result.get("k-Anonymity Visualization", "")
        if vis:
            base64.b64decode(vis)

    def test_accepts_dataframe_directly(self):
        result = compute_k_anonymity(["age"], self._make_df())
        self.assertNotIn("Error", result)


# ===========================================================================
# compute_l_diversity
# ===========================================================================


class TestLDiversity(unittest.TestCase):

    def _make_df(self):
        return pd.DataFrame({
            "age":     ["young", "young", "young", "old", "old", "old"],
            "gender":  ["M",     "F",     "M",     "F",   "M",   "F"],
            "disease": ["flu",   "cold",  "fever", "flu", "cold","fever"],
        })

    def test_returns_expected_keys(self):
        result = compute_l_diversity(["age"], "disease", self._make_df())
        self.assertNotIn("Error", result)
        for key in ["l-Value", "descriptive_statistics", "l-Diversity Visualization"]:
            self.assertIn(key, result)

    def test_l_value_equals_distinct_sensitive_values(self):
        # Each age group has 3 distinct diseases → l=3
        result = compute_l_diversity(["age"], "disease", self._make_df())
        self.assertEqual(result["l-Value"], 3)

    def test_low_diversity(self):
        df = pd.DataFrame({
            "group":   ["A", "A", "A", "B", "B", "B"],
            "disease": ["flu", "flu", "flu", "cold", "cold", "cold"],
        })
        result = compute_l_diversity(["group"], "disease", df)
        self.assertEqual(result["l-Value"], 1)

    def test_empty_dataframe_returns_error(self):
        result = compute_l_diversity(["age"], "disease", pd.DataFrame({"age": [], "disease": []}))
        self.assertIn("Error", result)

    def test_missing_qi_returns_error(self):
        result = compute_l_diversity(["nonexistent"], "disease", self._make_df())
        self.assertIn("Error", result)

    def test_missing_sensitive_column_returns_error(self):
        result = compute_l_diversity(["age"], "nonexistent", self._make_df())
        self.assertIn("Error", result)

    def test_descriptive_stats_present(self):
        result = compute_l_diversity(["age"], "disease", self._make_df())
        for key in ["min", "max", "mean", "median"]:
            self.assertIn(key, result["descriptive_statistics"])


# ===========================================================================
# compute_t_closeness
# ===========================================================================


class TestTCloseness(unittest.TestCase):

    def _make_df(self):
        return pd.DataFrame({
            "age":     ["young"] * 6 + ["old"] * 6,
            "salary":  ["low", "low", "low", "high", "high", "high",
                        "low", "low", "high", "high", "high", "high"],
        })

    def test_returns_expected_keys(self):
        result = compute_t_closeness(["age"], "salary", self._make_df())
        self.assertNotIn("Error", result)
        for key in ["t-Value", "descriptive_statistics", "t-Closeness Visualization"]:
            self.assertIn(key, result)

    def test_t_value_in_range(self):
        result = compute_t_closeness(["age"], "salary", self._make_df())
        self.assertGreaterEqual(result["t-Value"], 0.0)
        self.assertLessEqual(result["t-Value"], 1.0)

    def test_perfectly_uniform_groups_have_zero_t(self):
        # Both groups mirror the global distribution exactly → t=0
        df = pd.DataFrame({
            "group":   ["A", "A", "B", "B"],
            "disease": ["flu", "cold", "flu", "cold"],
        })
        result = compute_t_closeness(["group"], "disease", df)
        self.assertAlmostEqual(result["t-Value"], 0.0, places=4)

    def test_empty_dataframe_returns_error(self):
        result = compute_t_closeness(["age"], "salary", pd.DataFrame({"age": [], "salary": []}))
        self.assertIn("Error", result)

    def test_missing_qi_returns_error(self):
        result = compute_t_closeness(["nonexistent"], "salary", self._make_df())
        self.assertIn("Error", result)

    def test_missing_sensitive_column_returns_error(self):
        result = compute_t_closeness(["age"], "nonexistent", self._make_df())
        self.assertIn("Error", result)

    def test_descriptive_stats_present(self):
        result = compute_t_closeness(["age"], "salary", self._make_df())
        for key in ["min", "max", "mean", "median"]:
            self.assertIn(key, result["descriptive_statistics"])


# ===========================================================================
# compute_entropy_risk
# ===========================================================================


class TestEntropyRisk(unittest.TestCase):

    def _make_df(self, n=20, n_groups=4):
        rng = np.random.default_rng(99)
        return pd.DataFrame({
            "group": rng.choice([f"g{i}" for i in range(n_groups)], size=n),
        })

    def test_returns_expected_keys(self):
        result = compute_entropy_risk(["group"], self._make_df())
        self.assertNotIn("Error", result)
        for key in ["Entropy-Value", "descriptive_statistics", "Entropy Risk Visualization"]:
            self.assertIn(key, result)

    def test_entropy_is_non_negative(self):
        result = compute_entropy_risk(["group"], self._make_df())
        self.assertGreaterEqual(result["Entropy-Value"], 0.0)

    def test_single_group_has_positive_entropy(self):
        # One group of size 10: entropy = log2(10)/10 ≈ 0.332 (not 0)
        df = pd.DataFrame({"group": ["A"] * 10})
        result = compute_entropy_risk(["group"], df)
        self.assertNotIn("Error", result)
        self.assertGreater(result["Entropy-Value"], 0.0)

    def test_empty_dataframe_returns_error(self):
        result = compute_entropy_risk(["group"], pd.DataFrame({"group": []}))
        self.assertIn("Error", result)

    def test_missing_qi_returns_error(self):
        result = compute_entropy_risk(["nonexistent"], self._make_df())
        self.assertIn("Error", result)

    def test_placeholder_missing_values_handled(self):
        df = pd.DataFrame({"group": ["A", "?", "A", "B", "B"]})
        result = compute_entropy_risk(["group"], df)
        self.assertNotIn("Error", result)

    def test_descriptive_stats_present(self):
        result = compute_entropy_risk(["group"], self._make_df())
        for key in ["min", "max", "mean", "median"]:
            self.assertIn(key, result["descriptive_statistics"])

    def test_visualization_is_base64(self):
        import base64
        result = compute_entropy_risk(["group"], self._make_df())
        vis = result.get("Entropy Risk Visualization", "")
        if vis:
            base64.b64decode(vis)


if __name__ == "__main__":
    unittest.main()
