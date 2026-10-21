"""Regression: categorical correlations with pandas StringDtype + nulls.

dython.associations() defaults to fillna(0.0). Pandas 3 strict ``string``
columns reject that assignment. Impact on AI and the Correlation Analysis
metric both call calc_correlations().
"""

import unittest
from unittest.mock import patch

import pandas as pd

from aidrin.structured_data_metrics.correlation_score import calc_correlations


def _string_dtype_frame():
    return pd.DataFrame(
        {
            "a": pd.array(["x", "y", None, "x"], dtype=pd.StringDtype()),
            "b": pd.array(["p", "q", "r", "p"], dtype=pd.StringDtype()),
            "n": [1.0, 2.0, 3.0, 4.0],
        }
    )


class TestCorrelationStringDtype(unittest.TestCase):
    def test_string_dtype_with_nulls_returns_scores_not_error(self):
        file_info = ("/tmp/data.csv", "data.csv", ".csv")
        with patch(
            "aidrin.structured_data_metrics.correlation_score.read_file",
            return_value=_string_dtype_frame(),
        ):
            result = calc_correlations(
                ["a", "b", "n"],
                file_info,
                include_visualization=False,
            )

        self.assertNotIn("Message", result, result.get("Message"))
        scores = result.get("Correlation Scores")
        self.assertIsInstance(scores, dict)
        self.assertTrue(scores)
        self.assertIn("a vs b", scores)
