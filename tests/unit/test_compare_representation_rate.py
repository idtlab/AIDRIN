"""Unit tests for compare_rep_rates (compare_representation_rate.py).

These tests run without Flask, Celery, or Redis.  The Celery task is invoked
via .apply() after configuring a minimal always-eager Celery app so the task
decorator is satisfied without a running broker.
"""

import sys
import types
import unittest

import matplotlib

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
# Minimal always-eager Celery app so shared_task decorators resolve cleanly
# ---------------------------------------------------------------------------

from celery import Celery  # noqa: E402

_celery_app = Celery("tests")
_celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
_celery_app.set_default()

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from aidrin.structured_data_metrics.compare_representation_rate import (  # noqa: E402
    compare_rep_rates,
)


def _key(column, value_from, value_to):
    """Build a key in the format calculate_representation_rate emits."""
    return (
        f"Column: '{column}', Probability ratio for "
        f"'{value_from}' to '{value_to}'"
    )


class TestCompareRepRates(unittest.TestCase):

    def test_both_rates_zero(self):
        """Both rates zero makes the total zero; must not raise ZeroDivisionError."""
        key = _key("race", "A", "B")
        result = compare_rep_rates.apply(args=({key: 0.0}, {key: 0.0})).get()

        comparisons = result["Comparisons"]
        self.assertAlmostEqual(
            comparisons["Real vs Dataset Representation rate difference in 'A' to 'B'"],
            0.0,
        )
        self.assertIn("Comparison Visualization", comparisons)

    def test_mixed_zero_and_nonzero_totals(self):
        """A zero-total pair must not stop other pairs from being compared."""
        zero_key = _key("race", "A", "B")
        other_key = _key("sex", "M", "F")
        rep = {zero_key: 0.0, other_key: 1.0}
        rrr = {zero_key: 0.0, other_key: 2.0}

        comparisons = compare_rep_rates.apply(args=(rep, rrr)).get()["Comparisons"]
        self.assertAlmostEqual(
            comparisons["Real vs Dataset Representation rate difference in 'M' to 'F'"],
            1.0,
        )

    def test_nonzero_rates(self):
        """The ordinary path still reports the absolute difference."""
        key = _key("race", "A", "B")
        comparisons = compare_rep_rates.apply(
            args=({key: 0.5}, {key: 2.0})
        ).get()["Comparisons"]

        self.assertAlmostEqual(
            comparisons["Real vs Dataset Representation rate difference in 'A' to 'B'"],
            1.5,
        )
        self.assertIn("Comparison Visualization", comparisons)


if __name__ == "__main__":
    unittest.main()
