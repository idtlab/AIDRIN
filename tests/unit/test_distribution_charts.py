"""Tests for the Data Overview distribution charts (issues #253 and #212).

Issue #253: a column sampled on an even grid (``depth_m``, 0-28 000 m every
200 m) rendered as a sagging, near-flat KDE that implied the end depths were
rarer than the middle ones. Three things caused it, and each is pinned below:
the kernel losing mass past the data bounds, a density axis that did not start
at zero, and a histogram bin width that aliased against the sampling grid.

Issue #212: continuous columns get a bar twin so the reader can switch per
chart.
"""

import base64
import pathlib
import unittest

import numpy as np
import pandas as pd

from web.routes.utils import (
    _bin_count,
    _reflected_kde,
    continuous_bars,
    summary_histograms,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
INSPECTOR_JS = (
    pathlib.Path(__file__).resolve().parents[2] / "web" / "static" / "js" / "inspector.js"
)


def _grid_frame():
    """The shape of the reported column: an even grid, every value once."""
    return pd.DataFrame({"depth_m": np.arange(0, 28001, 200, dtype=float)})


class TestReflectedKde(unittest.TestCase):
    def test_density_keeps_all_its_mass(self):
        # The old cut=0 curve integrated to ~0.91: it clipped the kernel tails
        # off the ends instead of folding them back, so it was not a density.
        grid, density = _reflected_kde(_grid_frame()["depth_m"])
        self.assertAlmostEqual(float(np.trapezoid(density, grid)), 1.0, places=2)

    def test_even_grid_is_flat_to_both_edges(self):
        # The bug as a number: the reported curve read ~0.53 at the edges
        # relative to the centre, claiming 0 m and 28 000 m were half as common.
        _, density = _reflected_kde(_grid_frame()["depth_m"])
        centre = density[len(density) // 2]
        for edge in (density[0], density[-1]):
            self.assertAlmostEqual(edge / centre, 1.0, delta=0.1)

    def test_matches_the_analytic_uniform_density(self):
        values = _grid_frame()["depth_m"]
        _, density = _reflected_kde(values)
        truth = 1.0 / (values.max() - values.min())
        self.assertLess(float(np.abs(density - truth).max() / truth), 0.1)

    def test_degenerate_columns_have_no_estimate(self):
        for values in (
            pd.Series([], dtype=float),
            pd.Series([1.0]),
            pd.Series([7.0] * 20),  # no spread
            pd.Series([np.nan] * 5),
        ):
            self.assertIsNone(_reflected_kde(values))


class TestBinCount(unittest.TestCase):
    def test_even_grid_picks_a_count_it_divides(self):
        # 141 points on a 200 m lattice: of the 21 counts in 30-50, only 47
        # divides evenly. Any other turns a uniform column into a 4/5 comb.
        self.assertEqual(_bin_count(_grid_frame()["depth_m"]), 47)

    def test_even_grid_histogram_is_actually_flat(self):
        values = _grid_frame()["depth_m"]
        counts, _ = np.histogram(values, bins=_bin_count(values))
        self.assertEqual(set(counts.tolist()), {3})

    def test_low_cardinality_gets_one_bar_per_value(self):
        # A 1-5 rating is five bars, not fifty slivers (issue #212).
        ratings = pd.Series([1, 2, 3, 4, 5] * 80)
        self.assertEqual(_bin_count(ratings), 5)

    def test_irregular_data_stays_inside_the_band(self):
        rng = np.random.default_rng(0)
        for values in (
            pd.Series(rng.lognormal(3, 0.5, 50_000)),
            pd.Series(rng.normal(0, 1, 2_000)),
        ):
            self.assertGreaterEqual(_bin_count(values), 30)
            self.assertLessEqual(_bin_count(values), 50)

    def test_constant_column_is_a_single_bin(self):
        self.assertEqual(_bin_count(pd.Series([4.0] * 10)), 1)


class TestCurveAndBarsAgree(unittest.TestCase):
    """A per-chart toggle is only safe if both views support one conclusion."""

    def test_uniform_column_reads_flat_either_way(self):
        values = _grid_frame()["depth_m"]

        _, density = _reflected_kde(values)
        curve_spread = float(density.std() / density.mean())

        counts, _ = np.histogram(values, bins=_bin_count(values))
        bar_spread = float(counts.std() / counts.mean())

        # Neither rendering may imply structure the column does not have.
        self.assertLess(curve_spread, 0.05)
        self.assertLess(bar_spread, 0.05)


class TestChartPairing(unittest.TestCase):
    def _frame(self):
        rng = np.random.default_rng(3)
        return pd.DataFrame({
            "age": rng.normal(40, 9, 120),
            "rating": rng.integers(1, 6, 120),
            "label": ["a", "b"] * 60,          # categorical: not charted here
            "empty": [np.nan] * 120,
        })

    def test_every_curve_has_a_bar_twin(self):
        # Without a twin per column the toggle would dead-end on some cards.
        frame = self._frame()
        self.assertEqual(
            set(summary_histograms(frame)),
            set(continuous_bars(frame)),
        )

    def test_charts_are_keyed_for_the_existing_picker(self):
        self.assertEqual(list(continuous_bars(pd.DataFrame({"age": [1.0, 2.0, 3.0]}))), ["age_light"])

    def test_charts_are_real_pngs(self):
        frame = pd.DataFrame({"age": [1.0, 2.0, 3.0, 4.0]})
        for charts in (summary_histograms(frame), continuous_bars(frame)):
            self.assertTrue(base64.b64decode(charts["age_light"]).startswith(PNG_MAGIC))

    def test_degenerate_columns_still_produce_a_card(self):
        # They charted before this change; dropping them would silently shrink
        # the Data Overview grid.
        frame = pd.DataFrame({"empty": [np.nan] * 5, "const": [2.0] * 5})
        for charts in (summary_histograms(frame), continuous_bars(frame)):
            self.assertEqual(set(charts), {"empty_light", "const_light"})

    def test_renderer_is_wired_for_the_toggle(self):
        source = INSPECTOR_JS.read_text(encoding="utf-8")
        self.assertIn("function toggleDistributionChart", source)
        self.assertIn("data-chart-bars", source)
        self.assertIn("data.histogram_bars", source)


if __name__ == "__main__":
    unittest.main()
