"""Unit tests for the differential privacy metric (add_noise.py).

These tests run without Flask, Celery, or Redis.  return_noisy_stats is a
plain Python function so it is called directly with DataFrames.
"""

import sys
import types
import unittest

import matplotlib
import pandas as pd

matplotlib.use("Agg")

# ---------------------------------------------------------------------------
# Stubs — must be installed before any aidrin import
# ---------------------------------------------------------------------------

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from aidrin.structured_data_metrics.add_noise import (  # noqa: E402
    return_noisy_stats,
)


class TestReturnNoisyStats(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame({
            "age": [25, 30, 35],
            "salary": [50000, 60000, 70000],
        })

    def test_no_columns_selected(self):
        with self.assertRaises(Exception) as ctx:
            return_noisy_stats([], 0.5, self.df)
        self.assertIn("No columns selected", str(ctx.exception))

    def test_single_column(self):
        result = return_noisy_stats(["age"], 0.5, self.df)
        self.assertIn("Mean of feature age(before noise)", result)
        self.assertIn("DP Statistics Visualization", result)

    def test_invalid_epsilon(self):
        with self.assertRaises(Exception) as ctx:
            return_noisy_stats(["age"], 0, self.df)
        self.assertIn("Epsilon must be greater than 0", str(ctx.exception))


class TestDpErrorPayload(unittest.TestCase):
    """The headless runner turns the raised message into a user-facing payload."""

    def test_no_columns_message_is_mapped(self):
        from aidrin.headless.runners import _dp_error_payload

        payload = _dp_error_payload("No columns selected for noise addition")
        self.assertEqual(
            payload["Error"],
            "No numerical features selected for differential privacy.",
        )
        self.assertEqual(payload["Noisy file saved"], "Failed - Invalid parameters")


if __name__ == "__main__":
    unittest.main()
