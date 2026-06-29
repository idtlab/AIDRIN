"""Unit tests for readiness report dataset-overview helpers."""

import unittest

from web.routes.metrics import _prepare_feature_profiles_for_display


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
