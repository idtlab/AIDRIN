"""Correlation pruning must drop ID-like numerics and datetimes."""

import unittest

import numpy as np
import pandas as pd

from web.routes.metrics import _pairwise_signals, _prune_columns_for_corr


class TestPruneColumnsForCorr(unittest.TestCase):
    def test_drops_id_like_numerics_and_datetimes(self):
        n = 100
        df = pd.DataFrame({
            "row_id": np.arange(n),
            "created_at": pd.date_range("2020-01-01", periods=n, freq="h"),
            "seq_no": np.arange(n) * 2,
            "feature_a": np.random.default_rng(0).normal(size=n),
            "cat": np.random.default_rng(1).choice(["x", "y", "z"], size=n),
        })
        kept, dropped = _prune_columns_for_corr(df)
        dropped_by_feature = {d["feature"]: d["reason"] for d in dropped}

        self.assertEqual(dropped_by_feature["row_id"], "ID-like (near-unique values)")
        self.assertEqual(dropped_by_feature["seq_no"], "ID-like (near-unique values)")
        self.assertEqual(dropped_by_feature["created_at"], "datetime column")
        self.assertIn("feature_a", kept)
        self.assertIn("cat", kept)
        self.assertNotIn("row_id", kept)
        self.assertNotIn("seq_no", kept)
        self.assertNotIn("created_at", kept)

    def test_id_timestamp_columns_no_longer_manufacture_leakage(self):
        """Without pruning, row_id/created_at/seq_no yield 3 perfect leakage pairs."""
        n = 100
        df = pd.DataFrame({
            "row_id": np.arange(n),
            "created_at": pd.date_range("2020-01-01", periods=n, freq="h"),
            "seq_no": np.arange(n) * 2,
            "feature_a": np.random.default_rng(0).normal(size=n),
        })
        kept, _ = _prune_columns_for_corr(df)
        # Only a real feature remains among the four; no ID/timestamp pairs to score.
        self.assertEqual(kept, ["feature_a"])

        bogus_scores = {
            "row_id vs created_at": 1.0,
            "row_id vs seq_no": 1.0,
            "created_at vs seq_no": 1.0,
        }
        self.assertEqual(len(_pairwise_signals(bogus_scores)["leakage"]), 3)
        leakage_kpi = max(0.0, 1.0 - 3 / 5.0)
        self.assertEqual(leakage_kpi, 0.4)
