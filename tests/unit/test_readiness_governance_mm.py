"""Readiness single-attribute MM risk must match the Privacy tab row set."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from aidrin.structured_data_metrics.privacy_measure import (
    generate_single_attribute_MM_risk_scores,
    generate_single_attribute_MM_risk_scores_groupby,
)
from web.routes.metrics import _build_data_governance_section


def _missingness_df():
    """Missingness concentrated on one QI so per-column dropna diverges from list-wise."""
    n = 400
    rng = np.random.default_rng(7)
    age = rng.choice(["20-29", "30-39", "40-49", "50-59"], size=n)
    sex = rng.choice(["M", "F"], size=n).astype(object)
    rare_idx = rng.choice(n, size=40, replace=False)
    age = age.astype(object)
    for i, idx in enumerate(rare_idx):
        age[idx] = f"rare-{i % 15}"
    sex[np.array([str(a).startswith("rare") for a in age])] = np.nan
    return pd.DataFrame({
        "id": np.arange(n),
        "age": age,
        "sex": sex,
        "income": rng.integers(1, 5, size=n),
    })


_GOV_SELECTION = {
    "quasi_identifiers": ["age", "sex"],
    "mm_quasi_identifiers": ["age", "sex"],
    "sensitive_attribute": "income",
    "id_column": "id",
    "id_synthetic": False,
    "hipaa_scan_columns": [],
    "dp_features": [],
}


def _ok_k(*_args, **_kwargs):
    return {"k-Value": 2, "descriptive_statistics": {}}


def _ok_l(*_args, **_kwargs):
    return {"l-Value": 2, "descriptive_statistics": {}}


def _ok_t(*_args, **_kwargs):
    return {"t-Value": 0.1, "descriptive_statistics": {}}


def _ok_e(*_args, **_kwargs):
    return {"Entropy-Value": 1.0, "descriptive_statistics": {}}


class TestReadinessSingleAttributeMmMatchesPrivacy(unittest.TestCase):
    def test_groupby_called_once_with_all_qis_and_no_viz(self):
        df = _missingness_df()
        with patch("web.routes.metrics.read_file", return_value=df), patch(
            "web.routes.metrics._auto_select_fairness_columns",
            return_value={"target_column": None},
        ), patch(
            "web.routes.metrics._auto_select_governance_columns",
            return_value=_GOV_SELECTION,
        ), patch(
            "web.routes.metrics.compute_k_anonymity", side_effect=_ok_k
        ), patch(
            "web.routes.metrics.compute_l_diversity", side_effect=_ok_l
        ), patch(
            "web.routes.metrics.compute_t_closeness", side_effect=_ok_t
        ), patch(
            "web.routes.metrics.compute_entropy_risk", side_effect=_ok_e
        ), patch(
            "web.routes.metrics.generate_single_attribute_MM_risk_scores_groupby",
            wraps=generate_single_attribute_MM_risk_scores_groupby,
        ) as spy:
            _build_data_governance_section(("unused", "data.csv", ".csv"), include_visualizations=True)

        spy.assert_called_once()
        args, kwargs = spy.call_args
        self.assertEqual(list(args[2]), ["age", "sex"])
        self.assertFalse(kwargs.get("include_visualization", True))

    def test_means_match_privacy_tab_listwise_scores(self):
        df = _missingness_df()
        privacy = generate_single_attribute_MM_risk_scores(
            df, "id", ["age", "sex"], include_visualization=False
        )
        privacy_stats = privacy["Descriptive statistics of the risk scores"]

        with patch("web.routes.metrics.read_file", return_value=df), patch(
            "web.routes.metrics._auto_select_fairness_columns",
            return_value={"target_column": None},
        ), patch(
            "web.routes.metrics._auto_select_governance_columns",
            return_value=_GOV_SELECTION,
        ), patch(
            "web.routes.metrics.compute_k_anonymity", side_effect=_ok_k
        ), patch(
            "web.routes.metrics.compute_l_diversity", side_effect=_ok_l
        ), patch(
            "web.routes.metrics.compute_t_closeness", side_effect=_ok_t
        ), patch(
            "web.routes.metrics.compute_entropy_risk", side_effect=_ok_e
        ):
            section = _build_data_governance_section(("unused", "data.csv", ".csv"))

        by_qi = section["details"]["single_attribute_risk"]["by_quasi_identifier"]
        for col in ("age", "sex"):
            self.assertAlmostEqual(
                by_qi[col]["mean_risk"],
                round(float(privacy_stats[col]["mean"]), 4),
            )

        per_col = generate_single_attribute_MM_risk_scores_groupby(
            df, "id", ["age"], include_visualization=False
        )
        per_col_mean = float(per_col["Descriptive statistics of the risk scores"]["age"]["mean"])
        listwise_mean = float(privacy_stats["age"]["mean"])
        self.assertNotAlmostEqual(per_col_mean, listwise_mean, places=4)
        self.assertAlmostEqual(by_qi["age"]["mean_risk"], round(listwise_mean, 4))
        self.assertNotAlmostEqual(by_qi["age"]["mean_risk"], round(per_col_mean, 4))
