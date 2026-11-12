"""Overview distribution charts for the readiness report (web + headless).

Matplotlib helpers used by dataset-overview visualizations. Kept in ``aidrin``
so CLI PDF / ``--viz`` do not need the ``web`` package.
"""

from __future__ import annotations

import base64
import io
import threading

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

# Matplotlib's pyplot API is process-global and not thread-safe. Serialize chart
# builders that share this process so concurrent requests cannot cross-contaminate figures.
MATPLOTLIB_PLOT_LOCK = threading.Lock()

# Every distribution chart in the Data Overview uses this figure size, so the
# cards in the grid line up whatever kind of chart they hold.
_DISTRIBUTION_FIGSIZE = (4, 3)


def _finite_values(series):
    """Numeric values with NaN *and* infinities removed.

    ``dropna()`` keeps infinities and they reach matplotlib as an infinite axis
    range, so a single ``inf`` in a column raised ``ValueError`` out of
    ``ax.hist`` and took the whole Data Overview down with it. seaborn used to
    filter them before this module began drawing its own charts.
    """
    values = pd.to_numeric(pd.Series(series), errors="coerce").to_numpy(dtype=float)
    return values[np.isfinite(values)]


# Beyond this nothing is distinguishable on a chart, and the caller clamps far
# below it; the ceiling only stops a pathological rule result from overflowing.
_MAX_RULE_BINS = 10_000


def _auto_bin_count(values):
    """numpy's "auto" rule as a count, without materializing the bin edges.

    ``np.histogram_bin_edges(bins="auto")`` builds the complete edge array
    before any cap can be applied to it. One far outlier makes the rule ask for
    billions of edges: 1000 values in [0, 1] plus a single 1e9 wants about 1e10
    of them, roughly 80 GB, which the web process would try to allocate on
    every uncached overview request. The count is only arithmetic, so derive it
    and let the caller clamp before anything is allocated.
    """
    n = values.size
    sturges = int(np.ceil(np.log2(n))) + 1 if n > 1 else 1
    span = float(values.max() - values.min())
    if span <= 0:
        return sturges

    first, third = np.percentile(values, [25, 75])
    iqr = float(third - first)
    if iqr <= 0:
        return sturges

    # Freedman-Diaconis; numpy's "auto" takes whichever of the two is finer.
    fd_width = 2.0 * iqr / n ** (1.0 / 3.0)
    if fd_width <= 0:
        return sturges
    return max(sturges, int(min(span / fd_width, _MAX_RULE_BINS)))


def _reflected_kde(values, bw_adjust=0.5, grid_size=256):
    """Estimate a density that keeps all of its mass inside ``[min, max]``.

    A Gaussian kernel centred near an edge spills roughly half its weight past
    the end of the data. ``cut=0`` clips that weight away rather than putting it
    back, so the curve sags at both ends and claims the extreme values are
    rarer than they are: on a column sampled on an even grid the end density
    reads about half the middle, and the curve integrates to ~0.91 instead of 1
    (issue #253). Mirroring every point about both bounds folds the lost weight
    back inward, which restores both the shape and the total mass.

    Returns ``(grid, density)``, or ``None`` when the column cannot support an
    estimate (fewer than two values, or no spread).
    """
    x = _finite_values(values)
    if x.size < 2:
        return None
    low, high = x.min(), x.max()
    spread = x.std(ddof=1)
    if high <= low or not np.isfinite(spread) or spread <= 0:
        return None

    # Scott's rule, matching the bandwidth seaborn used, so smoothing is
    # unchanged and only the boundary behaviour differs.
    bandwidth = bw_adjust * x.size ** (-1.0 / 5.0) * spread
    if bandwidth <= 0:
        return None

    augmented = np.concatenate([x, 2 * low - x, 2 * high - x])
    kde = gaussian_kde(augmented, bw_method=bandwidth / augmented.std(ddof=1))
    grid = np.linspace(low, high, grid_size)
    # The sample was tripled; undo that so the result is a density again.
    return grid, kde(grid) * 3.0


def _bin_count(values, floor=30, cap=50):
    """Choose a histogram bin count that does not alias against the data.

    Values recorded on a regular grid (a depth profile sampled every 200 m, a
    daily counter) alias against an arbitrary bin width: unless the width is a
    whole multiple of the grid step, neighbouring bins take four points and then
    five, and a perfectly uniform column renders as a comb while its curve
    renders flat. Two views of one column must not support different
    conclusions, so a regular grid picks a count it divides evenly.
    """
    values = _finite_values(values)
    if values.size == 0:
        return 1

    unique = np.unique(values)  # np.unique returns them sorted
    nunique = unique.size
    if nunique <= 1:
        return 1
    if nunique <= cap:
        # Fewer distinct values than bins: one bar each, so a coded column
        # (a 1-5 rating) gets five bars rather than fifty slivers.
        return int(nunique)

    step = np.diff(unique)
    if step.size and np.allclose(step, step[0], rtol=1e-6):
        divisors = [b for b in range(floor, cap + 1) if nunique % b == 0]
        if divisors:
            return max(divisors)

    return int(min(max(_auto_bin_count(values), floor), cap, nunique))


def _style_distribution_axes(ax, ylabel, text_color="#6b7280"):
    """Apply the shared axis styling for both distribution renderings."""
    ax.set_xlabel("Values", fontsize=10, color=text_color)
    ax.set_ylabel(ylabel, fontsize=10, color=text_color)
    ax.tick_params(colors=text_color, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(text_color)


def _encode_figure(fig, dpi):
    """Render *fig* to a transparent base64 PNG and close it."""
    img_buffer = io.BytesIO()
    fig.savefig(img_buffer, format="png", dpi=dpi, transparent=True)
    img_buffer.seek(0)
    encoded_img = base64.b64encode(img_buffer.read()).decode("utf-8")
    plt.close(fig)
    img_buffer.close()
    return encoded_img


def summary_histograms(df, columns=None, figsize=_DISTRIBUTION_FIGSIZE, dpi=150):
    """Generate base64-encoded KDE distribution plots.

    ``columns`` restricts the plots to the given columns (used to plot only
    columns whose semantic role is *continuous*); when ``None`` it falls back
    to every numeric column for backward compatibility.

    :func:`continuous_bars` draws the same columns as a histogram so the Data
    Overview can offer a per-chart switch. It skips columns with nothing to
    bin, so a column with no finite values yields a KDE key here and no bar
    key; the switch is only offered where both exist.
    """
    curve_color = "#4485F4"

    if columns is None:
        columns = list(df.select_dtypes(include="number").columns)

    line_graphs = {}
    with MATPLOTLIB_PLOT_LOCK:
        for column in columns:
            fig, ax = plt.subplots(figsize=figsize)
            fig.patch.set_alpha(0)
            ax.set_facecolor("none")

            estimate = _reflected_kde(pd.to_numeric(df[column], errors="coerce"))
            if estimate is not None:
                grid, density = estimate
                ax.plot(grid, density, color=curve_color, linewidth=1.5)
                # A density axis that does not start at zero magnifies a flat
                # curve into a feature: on an evenly sampled column matplotlib
                # would scale a 5% ripple to fill the panel, so the curve
                # disagreed with its own histogram (issue #253).
                ax.set_ylim(bottom=0)

            _style_distribution_axes(ax, "Density")
            fig.tight_layout(pad=0.5)

            # Store as _light for backward compat with JS picker
            line_graphs[f"{column}_light"] = _encode_figure(fig, dpi)

    return line_graphs


def continuous_bars(df, columns=None, figsize=_DISTRIBUTION_FIGSIZE, dpi=150):
    """Generate base64-encoded binned-histogram bars for continuous columns.

    The twin of :func:`summary_histograms`: same columns, same keys, drawn as
    a binned histogram instead of a KDE curve. A KDE smooths the distribution,
    which hides the gaps in data that is continuous by dtype but effectively
    discrete (issue #212), so the Data Overview ships both and lets the reader
    switch per chart. Columns with no non-null values are skipped — there is
    nothing to bin, and a blank card is worse than no card.

    ``columns`` restricts the plots the same way :func:`summary_histograms`
    does. Categorical columns are not covered here; they get value-count bars
    from :func:`categorical_bars` instead.
    """
    bar_color = "#4485F4"

    if columns is None:
        columns = list(df.select_dtypes(include="number").columns)

    bar_graphs = {}
    with MATPLOTLIB_PLOT_LOCK:
        for column in columns:
            values = _finite_values(df[column])
            if values.size == 0:
                continue

            fig, ax = plt.subplots(figsize=figsize)
            fig.patch.set_alpha(0)
            ax.set_facecolor("none")

            ax.hist(
                values,
                bins=_bin_count(values),
                color=bar_color,
                edgecolor="white",
                linewidth=0.5,
            )

            _style_distribution_axes(ax, "Count")
            fig.tight_layout(pad=0.5)

            bar_graphs[f"{column}_light"] = _encode_figure(fig, dpi)

    return bar_graphs


# Individual categories shown before the tail is rolled up. Nine leaves room
# for the "Other" bar inside a fixed ten-slot axis.
_CATEGORICAL_MAX_BARS = 9
# Every categorical chart is laid out on this many slots whether or not it fills
# them, so bar thickness is identical across columns and the cards in the grid
# are all the same height. Fewer categories buy blank space, not fatter bars.
_CATEGORICAL_SLOTS = 10
# Muted fill for the rolled-up tail, so it reads as a summary, not a category.
_OTHER_BAR_COLOR = "#c7d6f5"
# A bar at least this fraction of the widest gets its label drawn inside, where
# it cannot run off the right edge.
_LABEL_INSIDE_FRACTION = 0.55


def categorical_bars(df, columns, max_categories=_CATEGORICAL_MAX_BARS):
    """Generate base64-encoded value-count bar charts for categorical columns.

    KDE curves are meaningless for discrete/coded columns, so categorical
    columns (including numeric codes like ``flavor``) get a value-count bar
    chart instead.

    Bars are horizontal, matching every other chart in the app and letting long
    category names ("Married-spouse-absent", "Dominican-Republic") read at full
    length instead of being rotated and clipped.

    Every chart is drawn on a fixed ``_CATEGORICAL_SLOTS``-slot axis at the same
    figure size as the continuous charts, and vertically centred, so a
    two-category column and a ten-category one produce bars of the same
    thickness and cards of the same height throughout the grid — the axis gains
    blank space rather than the bars stretching to fill it.

    Categories beyond ``max_categories`` are summed into a single ``Other`` bar
    rather than dropped, so the chart always accounts for every non-null row and
    the size of the tail stays visible. How many categories it stands for is
    carried in that bar's value label, keeping the axis tick to a plain
    ``Other``.

    Ordering: numeric and boolean categories read in value order, so a 1-5
    rating is a scale rather than a frequency ranking. Everything else has no
    natural order and reads largest-first.
    """
    text_color = "#6b7280"
    bar_color = "#4485F4"

    bars = {}
    with MATPLOTLIB_PLOT_LOCK:
        for column in columns:
            series = df[column]
            total = int(series.notna().sum())
            counts = series.value_counts(dropna=True)
            if counts.empty or total == 0:
                continue

            shown = counts.head(max_categories)
            hidden = counts.iloc[max_categories:]
            if pd.api.types.is_numeric_dtype(shown.index) or pd.api.types.is_bool_dtype(shown.index):
                shown = shown.sort_index()
            else:
                shown = shown.sort_values(ascending=False)

            labels = [str(i) for i in shown.index]
            values = [int(v) for v in shown.values]
            colors = [bar_color] * len(values)
            # Per-bar suffix; only the rollup carries one.
            notes = [""] * len(values)
            if len(hidden):
                labels.append("Other")
                values.append(int(hidden.sum()))
                colors.append(_OTHER_BAR_COLOR)
                notes.append(f" · {len(hidden)} categories")

            n = len(values)
            slots = max(n, _CATEGORICAL_SLOTS)
            # Centre the bars in the slots, so the slack sits above and below.
            offset = (slots - n) / 2
            positions = [offset + i for i in range(n)]

            # Same figure size as the continuous charts, so every card in the Data
            # Overview grid is the same height.
            fig, ax = plt.subplots(figsize=_DISTRIBUTION_FIGSIZE)
            fig.patch.set_alpha(0)
            ax.set_facecolor("none")

            ax.barh(positions, values, color=colors, height=0.7)
            ax.set_yticks(positions)
            ax.set_yticklabels(labels, fontsize=7, color=text_color)
            ax.set_xlabel("Count", fontsize=10, color=text_color)
            ax.tick_params(axis="x", colors=text_color, labelsize=8)
            ax.invert_yaxis()  # first category at the top
            ax.set_ylim(slots - 0.5, -0.5)

            widest = max(values)
            ax.set_xlim(0, widest * 1.3)
            for position, value, color, note in zip(positions, values, colors, notes):
                inside = value >= widest * _LABEL_INSIDE_FRACTION
                ax.text(
                    value - widest * 0.02 if inside else value + widest * 0.02,
                    position,
                    f"{value:,} ({value / total * 100:.1f}%){note}",
                    ha="right" if inside else "left",
                    va="center",
                    fontsize=6.5,
                    # White reads on the solid blue fill but not on the muted
                    # "Other" bar, which keeps the normal text colour.
                    color="white" if inside and color == bar_color else text_color,
                    fontweight="bold" if inside and color == bar_color else "normal",
                )

            for spine in ax.spines.values():
                spine.set_color(text_color)
            fig.tight_layout(pad=0.5)

            bars[f"{column}_light"] = _encode_figure(fig, 150)

    return bars


def categorical_distribution_charts(df, top_n=10):
    """Generate base64-encoded pie charts for categorical columns.

    Shows the top *top_n* values per column; remaining values are grouped
    into an "Other" slice when applicable.
    """
    text_color = "#6b7280"
    palette = [
        "#4485F4", "#34A853", "#FBBC05", "#EA4335", "#9C27B0",
        "#00ACC1", "#FF7043", "#8D6E63", "#78909C", "#AB47BC",
    ]
    charts = {}

    cat_cols = df.select_dtypes(include=["object", "string", "category"]).columns
    with MATPLOTLIB_PLOT_LOCK:
        for column in cat_cols:
            series = df[column].dropna()
            if len(series) == 0:
                continue

            vc = series.value_counts()
            if len(vc) > top_n:
                top = vc.head(top_n)
                other_count = int(vc.iloc[top_n:].sum())
                labels = [str(v) for v in top.index]
                sizes = [int(v) for v in top.values]
                if other_count > 0:
                    labels.append("Other")
                    sizes.append(other_count)
            else:
                labels = [str(v) for v in vc.index]
                sizes = [int(v) for v in vc.values]

            n_slices = len(labels)
            colors = [palette[i % len(palette)] for i in range(n_slices)]

            fig, ax = plt.subplots(figsize=(5, 5))
            fig.patch.set_alpha(0)

            wedges, _, autotexts = ax.pie(
                sizes,
                labels=None,
                autopct=lambda pct: f"{pct:.1f}%" if pct >= 4 else "",
                colors=colors,
                startangle=90,
                pctdistance=0.75,
                textprops={"color": text_color, "fontsize": 8},
            )
            for t in autotexts:
                t.set_fontsize(7)

            ax.legend(
                wedges,
                labels,
                loc="center left",
                bbox_to_anchor=(1, 0.5),
                fontsize=8,
                frameon=False,
                labelcolor=text_color,
            )
            ax.set_title(str(column), fontsize=10, color=text_color, pad=8)
            fig.tight_layout()

            img_buffer = io.BytesIO()
            fig.savefig(img_buffer, format="png", dpi=150, transparent=True, bbox_inches="tight")
            img_buffer.seek(0)
            charts[str(column)] = base64.b64encode(img_buffer.read()).decode("utf-8")
            plt.close(fig)
            img_buffer.close()

    return charts
