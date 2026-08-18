"""Tests for the line/bar toggle on continuous distribution charts (issue #212).

Continuous columns render as a KDE curve, which smooths over data that may be
effectively discrete. ``continuous_bars`` supplies a binned-histogram twin for
every column ``summary_histograms`` draws, so the UI can swap between the two
without another round trip. Categorical columns are excluded on purpose: they
already render as value-count bars, and a KDE over a discrete code is the
thing column roles exist to avoid.
"""

import base64
import os

import numpy as np
import pandas as pd

from web.routes.utils import continuous_bars, summary_histograms

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INSPECTOR_JS = os.path.join(REPO_ROOT, "web", "static", "js", "inspector.js")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _df(n=500):
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "age": rng.normal(42, 12, n),
            "income": rng.lognormal(10.6, 0.45, n),
            "star_rating": rng.choice([1, 2, 3, 4, 5], n),
        }
    )


def test_every_line_chart_has_a_bar_counterpart():
    # Without a twin for each column the toggle would dead-end on some cards.
    df = _df()
    cols = ["age", "income"]
    assert set(summary_histograms(df, columns=cols)) == set(continuous_bars(df, columns=cols))


def test_bars_are_keyed_for_the_existing_picker():
    # The JS picker strips a "_light" suffix; a different key renders nothing.
    bars = continuous_bars(_df(), columns=["age"])
    assert list(bars) == ["age_light"]


def test_bars_are_real_pngs():
    bars = continuous_bars(_df(), columns=["age"])
    assert base64.b64decode(bars["age_light"]).startswith(PNG_MAGIC)


def test_all_nan_column_is_skipped_not_fatal():
    # A column that is entirely missing has nothing to bin; it must not take
    # the whole Data Overview down with it.
    df = pd.DataFrame({"empty": [np.nan] * 20, "age": np.arange(20.0)})
    bars = continuous_bars(df, columns=["empty", "age"])
    assert "empty_light" not in bars
    assert "age_light" in bars


def test_no_columns_gives_no_charts():
    assert continuous_bars(_df(), columns=[]) == {}


def test_toggle_is_wired_in_the_renderer():
    # The charts are server-rendered PNGs, so the swap happens in the DOM.
    with open(INSPECTOR_JS, encoding="utf-8") as handle:
        source = handle.read()
    assert "function toggleDistributionChart" in source
    assert "data-chart-card" in source
    assert "data-chart-bar" in source


def test_the_line_png_is_not_mirrored_into_an_attribute():
    # Each PNG is ~15-30 KB of base64. Copying the line rendering into a
    # data-attribute as well as the <img> doubled the section's DOM for no
    # gain, on every card — including the categorical ones with no toggle.
    with open(INSPECTOR_JS, encoding="utf-8") as handle:
        source = handle.read()
    assert "data-chart-line" not in source
