"""Regression test: KDE distribution plots must not extend past the data's
actual min/max (e.g. showing values < 0 for a strictly-positive feature).

sns.kdeplot's default cut=3 pads the curve 3 bandwidths past the extreme
datapoints; summary_histograms must override this with cut=0.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import seaborn as sns

import web.routes.utils as utils


def test_summary_histograms_kde_stays_within_data_range():
    rng = np.random.default_rng(0)
    values = np.concatenate([[0.03, 0.82], rng.uniform(0.03, 0.82, 200)])
    df = pd.DataFrame({"RotD50_PGA": values})

    captured_axes = []
    original_kdeplot = sns.kdeplot

    def spy_kdeplot(*args, **kwargs):
        ax = original_kdeplot(*args, **kwargs)
        captured_axes.append(ax)
        return ax

    with patch("web.routes.utils.sns.kdeplot", side_effect=spy_kdeplot):
        utils.summary_histograms(df)

    assert captured_axes, "sns.kdeplot was not called"
    xdata = captured_axes[0].lines[0].get_xdata()
    assert xdata.min() >= values.min()
    assert xdata.max() <= values.max()
