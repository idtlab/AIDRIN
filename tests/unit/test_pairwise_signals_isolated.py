"""Unpaired kept columns must count as isolated for informativeness."""

import unittest

from web.routes.metrics import _pairwise_signals


class TestPairwiseSignalsIsolatedSeeding(unittest.TestCase):
    def test_lone_numeric_counts_as_isolated(self):
        # Same shape as calc_correlations: cat-cat pairs only, no cross-type.
        scores = {
            "c1 vs c2": 0.02,
            "c2 vs c1": 0.02,
            "c1 vs c3": 0.01,
            "c3 vs c1": 0.01,
            "c2 vs c3": 0.03,
            "c3 vs c2": 0.03,
        }
        kept = ["c1", "c2", "c3", "n1"]
        signals = _pairwise_signals(scores, columns=kept)
        self.assertEqual(signals["isolated"], ["c1", "c2", "c3", "n1"])
        n_kept = len(kept)
        informativeness = max(0.0, 1.0 - len(signals["isolated"]) / n_kept)
        self.assertEqual(informativeness, 0.0)

    def test_without_column_seed_lone_numeric_is_missed(self):
        """Documents the pre-fix failure mode when columns are not seeded."""
        scores = {
            "c1 vs c2": 0.02,
            "c2 vs c1": 0.02,
            "c1 vs c3": 0.01,
            "c3 vs c1": 0.01,
            "c2 vs c3": 0.03,
            "c3 vs c2": 0.03,
        }
        signals = _pairwise_signals(scores)
        self.assertEqual(signals["isolated"], ["c1", "c2", "c3"])
        informativeness = max(0.0, 1.0 - len(signals["isolated"]) / 4)
        self.assertEqual(informativeness, 0.25)
