"""Tests for the categorical value-count charts in the Data Overview.

These charts have to work across a wide cardinality range — a boolean flag and
a 42-value country column land in the same grid. The rules under test: bars are
horizontal so long labels stay readable, every chart is drawn on a fixed slot
count so bar thickness and card height never vary, the tail beyond the cap is
rolled up instead of silently dropped, and numeric categories read as a scale
rather than a frequency ranking.
"""

import base64
from unittest import mock

import numpy as np
import pandas as pd

from web.routes import utils as web_utils
from web.routes.utils import categorical_bars

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _drawn(df, column, **kwargs):
    """Return (labels top-to-bottom, values, figure height) for one chart."""
    captured = {}
    real_labels = web_utils.plt.Axes.set_yticklabels
    real_barh = web_utils.plt.Axes.barh
    real_subplots = web_utils.plt.subplots

    def labels_spy(self, labels, *a, **kw):
        captured["labels"] = [str(x) for x in labels]
        return real_labels(self, labels, *a, **kw)

    def barh_spy(self, y, width, *a, **kw):
        captured["positions"] = list(y)
        captured["values"] = list(width)
        captured["height"] = kw.get("height")
        return real_barh(self, y, width, *a, **kw)

    def subplots_spy(*a, **kw):
        captured["figsize"] = kw.get("figsize")
        return real_subplots(*a, **kw)

    real_text = web_utils.plt.Axes.text

    def text_spy(self, x, y, s, *a, **kw):
        captured.setdefault("value_labels", []).append(s)
        return real_text(self, x, y, s, *a, **kw)

    with mock.patch.object(web_utils.plt.Axes, "set_yticklabels", labels_spy), \
         mock.patch.object(web_utils.plt.Axes, "barh", barh_spy), \
         mock.patch.object(web_utils.plt.Axes, "text", text_spy), \
         mock.patch.object(web_utils.plt, "subplots", subplots_spy):
        categorical_bars(df, [column], **kwargs)
    return captured


# ---------------------------------------------------------------------------
# Orientation and sizing
# ---------------------------------------------------------------------------

def test_bars_are_horizontal():
    # Vertical bars force 45-degree labels; "Married-spouse-absent" does not fit.
    drawn = _drawn(pd.DataFrame({"c": ["a", "b", "b"]}), "c")
    assert drawn["values"] == [2, 1]


def test_every_chart_is_the_same_size_whatever_the_cardinality():
    # A fixed slot count is what keeps bar thickness constant and stops the
    # cards in the grid from having ragged heights.
    two = _drawn(pd.DataFrame({"c": ["a"] * 5 + ["b"] * 3}), "c")
    nine = _drawn(pd.DataFrame({"c": [f"c{i}" for i in range(9)] * 3}), "c")
    assert two["figsize"] == nine["figsize"]
    assert two["height"] == nine["height"]


def test_sparse_bars_are_centred_in_the_spare_slots():
    # Two bars on a ten-slot axis sit in the middle, with the slack above and
    # below rather than two slabs filling the box.
    two = _drawn(pd.DataFrame({"c": ["a"] * 5 + ["b"] * 3}), "c")
    positions = two["positions"]
    assert len(positions) == 2
    midpoint = sum(positions) / len(positions)
    assert midpoint == (web_utils._CATEGORICAL_SLOTS - 1) / 2


def test_a_full_chart_uses_every_slot():
    # Nine categories plus the rollup exactly fills the ten slots.
    df = pd.DataFrame({"c": sum(([f"c{i}"] * (20 - i) for i in range(15)), [])})
    drawn = _drawn(df, "c")
    assert len(drawn["values"]) == web_utils._CATEGORICAL_SLOTS
    assert drawn["positions"][0] == 0


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

def test_numeric_categories_read_as_a_scale():
    df = pd.DataFrame({"rating": [1] * 2 + [2] * 9 + [3] * 4 + [4] * 20 + [5] * 15})
    assert _drawn(df, "rating")["labels"] == ["1", "2", "3", "4", "5"]


def test_boolean_categories_are_ordered_too():
    df = pd.DataFrame({"flag": [True] * 30 + [False] * 5})
    assert _drawn(df, "flag")["labels"] == ["False", "True"]


def test_string_categories_read_largest_first():
    df = pd.DataFrame({"country": ["UK"] * 3 + ["USA"] * 10 + ["Peru"] * 6})
    assert _drawn(df, "country")["labels"] == ["USA", "Peru", "UK"]


# ---------------------------------------------------------------------------
# The "Other" rollup
# ---------------------------------------------------------------------------

def test_tail_is_rolled_up_not_dropped():
    # 15 categories, cap of 9 -> 9 bars plus a single rollup bar.
    df = pd.DataFrame({"c": sum(([f"c{i}"] * (20 - i) for i in range(15)), [])})
    drawn = _drawn(df, "c")
    assert drawn["labels"][-1] == "Other"
    assert len(drawn["labels"]) == 10


def test_the_axis_tick_stays_a_plain_other():
    # The tick column is narrow; the category count belongs in the value label.
    df = pd.DataFrame({"c": sum(([f"c{i}"] * (20 - i) for i in range(15)), [])})
    assert _drawn(df, "c")["labels"][-1] == "Other"


def test_the_rollup_preserves_every_non_null_row():
    # Whatever is charted must still add up to the column's non-null total,
    # otherwise the reader is quietly shown a subset.
    df = pd.DataFrame({"c": sum(([f"c{i}"] * (20 - i) for i in range(15)), [])})
    drawn = _drawn(df, "c")
    assert sum(drawn["values"]) == int(df["c"].notna().sum())


def test_no_rollup_when_everything_fits():
    df = pd.DataFrame({"c": ["a"] * 5 + ["b"] * 3})
    assert not any(label.startswith("Other") for label in _drawn(df, "c")["labels"])


def test_rollup_reports_how_many_categories_it_stands_for():
    df = pd.DataFrame({"c": sum(([f"c{i}"] * (20 - i) for i in range(15)), [])})
    drawn = _drawn(df, "c")
    hidden = df["c"].value_counts().iloc[web_utils._CATEGORICAL_MAX_BARS:]
    assert drawn["values"][-1] == int(hidden.sum())
    # Carried in the bar's own value label, next to its count and percentage.
    assert "6 categories" in drawn["value_labels"][-1]


def test_ordinary_bars_carry_no_category_note():
    df = pd.DataFrame({"c": sum(([f"c{i}"] * (20 - i) for i in range(15)), [])})
    drawn = _drawn(df, "c")
    assert not any("categories" in label for label in drawn["value_labels"][:-1])


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

def test_all_null_column_is_skipped():
    df = pd.DataFrame({"empty": [None] * 10, "ok": ["a", "b"] * 5})
    charts = categorical_bars(df, ["empty", "ok"])
    assert "empty_light" not in charts
    assert "ok_light" in charts


def test_charts_are_real_pngs():
    charts = categorical_bars(pd.DataFrame({"c": ["a", "b", "b"]}), ["c"])
    assert base64.b64decode(charts["c_light"]).startswith(PNG_MAGIC)


def test_percentages_are_based_on_non_null_rows():
    # Half the column is missing; the charted half must read as 100%, not 50%,
    # since value_counts drops nulls.
    df = pd.DataFrame({"c": ["a"] * 5 + [np.nan] * 5})
    drawn = _drawn(df, "c")
    assert sum(drawn["values"]) == 5
