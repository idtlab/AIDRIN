"""Unit tests for readiness report dataset-overview helpers."""

import unittest

import pandas as pd

from web.routes.metrics import (
    _build_categorical_distributions,
    _build_numerical_summary_for_overview,
    _cap_detail_list,
    _dataframe_for_overview_detail_charts,
    _prepare_feature_profiles_for_display,
)


class TestCapDetailList(unittest.TestCase):
    def test_no_truncation_when_under_cap(self):
        items = [{"feature": f"c{i}"} for i in range(10)]
        capped, meta = _cap_detail_list(items, max_items=50)
        self.assertEqual(len(capped), 10)
        self.assertFalse(meta["truncated"])

    def test_truncation_when_over_cap(self):
        items = [{"feature": f"c{i}"} for i in range(100)]
        capped, meta = _cap_detail_list(items, max_items=50)
        self.assertEqual(len(capped), 50)
        self.assertTrue(meta["truncated"])
        self.assertEqual(meta["total"], 100)


class TestBuildNumericalSummaryForOverview(unittest.TestCase):
    def test_caps_wide_numerical_summary(self):
        df = pd.DataFrame({f"n{i}": range(5) for i in range(600)})
        summary, meta = _build_numerical_summary_for_overview(df)
        self.assertEqual(len(summary), 500)
        self.assertTrue(meta["truncated"])
        self.assertEqual(meta["total"], 600)


class TestBuildCategoricalDistributions(unittest.TestCase):
    def test_caps_wide_categorical_distributions(self):
        df = pd.DataFrame({f"c{i}": ["a", "b", "a"] for i in range(80)})
        dists, meta = _build_categorical_distributions(df, max_columns=50)
        self.assertEqual(len(dists), 50)
        self.assertTrue(meta["truncated"])
        self.assertEqual(meta["total"], 80)


class TestDataframeForOverviewDetailCharts(unittest.TestCase):
    def test_uses_capped_profile_features_only(self):
        profiles = (
            [{"feature": f"p{i}", "status": "poor", "type": "numerical"} for i in range(3)]
            + [{"feature": f"g{i}", "status": "good", "type": "numerical"} for i in range(10)]
        )
        df = pd.DataFrame({p["feature"]: range(5) for p in profiles})
        display, meta = _prepare_feature_profiles_for_display(profiles, max_profiles=5)
        self.assertTrue(meta["truncated"])
        chart_df = _dataframe_for_overview_detail_charts(df, display)
        self.assertEqual(list(chart_df.columns), [p["feature"] for p in display])


class TestPrepareFeatureProfilesForDisplay(unittest.TestCase):
    def test_no_truncation_when_under_cap(self):
        profiles = [
            {"feature": "a", "status": "good"},
            {"feature": "b", "status": "poor"},
        ]
        shown, meta = _prepare_feature_profiles_for_display(profiles, max_profiles=500)
        self.assertEqual(len(shown), 2)
        self.assertFalse(meta["truncated"])
        self.assertEqual(meta["status_counts"], {"poor": 1, "warning": 0, "good": 1})

    def test_truncation_prioritizes_poor_then_warning_then_good(self):
        profiles = (
            [{"feature": f"g{i}", "status": "good"} for i in range(10)]
            + [{"feature": f"w{i}", "status": "warning"} for i in range(5)]
            + [{"feature": f"p{i}", "status": "poor"} for i in range(3)]
        )
        shown, meta = _prepare_feature_profiles_for_display(profiles, max_profiles=8)
        self.assertTrue(meta["truncated"])
        self.assertEqual(meta["total"], 18)
        self.assertEqual(meta["shown"], 8)
        statuses = [p["status"] for p in shown]
        self.assertEqual(statuses[:3], ["poor", "poor", "poor"])
        self.assertEqual(statuses[3:8], ["warning"] * 5)


if __name__ == "__main__":
    unittest.main()
