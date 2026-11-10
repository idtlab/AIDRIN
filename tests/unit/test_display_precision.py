"""Metric tables and their charts must agree on decimal precision.

A metric's bar chart is rendered to PNG inside ``aidrin`` with its own format
string, while the table beside it goes through ``format_dict_values`` in the
web layer. Because the chart labels are baked in before the web layer ever
sees the numbers, the two drift apart silently: outlier scores rendered at
three decimals on the chart were served to the table rounded to two, so
``age`` read ``0.004`` on the chart and ``0.0`` in the table (issue #211).

These tests pin both ends to the same precision.
"""

import os
import re
import unittest

from web.routes.utils import format_dict_values

DISPLAY_DECIMALS = 3

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
METRICS_DIR = os.path.join(REPO_ROOT, "aidrin", "structured_data_metrics")
INSPECTOR_JS = os.path.join(REPO_ROOT, "web", "static", "js", "inspector.js")

# Metric modules whose chart labels annotate the same proportion values that
# format_dict_values rounds for the table. Percentage labels (``.1f%`` in
# representation_rate/class_imbalance) are a different unit and excluded.
MODULES_LABELLING_PROPORTIONS = ("outliers.py", "completeness.py", "feature_relevance.py")

# Matches the value labels drawn on bars, e.g. f'{val:.3f}'.
BAR_LABEL_FORMAT = re.compile(r"\{val:\.(\d+)f\}")


class TestTableRounding(unittest.TestCase):
    """format_dict_values feeds the table; it must not truncate below the chart."""

    def test_values_keep_three_decimals(self):
        self.assertEqual(
            format_dict_values({"age": 0.004391757009919842}),
            {"age": 0.004},
        )

    def test_rounding_recurses_into_nested_results(self):
        # Metric payloads nest, e.g. {"Outlier scores": {col: score, ...}}.
        formatted = format_dict_values(
            {"Outlier scores": {"education.num": 0.036792481803384416}}
        )
        self.assertEqual(formatted, {"Outlier scores": {"education.num": 0.037}})

    def test_small_but_nonzero_scores_survive(self):
        # The #211 symptom: at two decimals this collapsed to 0.0, contradicting
        # the 0.004 printed on the chart.
        self.assertNotEqual(format_dict_values({"age": 0.0044})["age"], 0.0)

    def test_non_numeric_values_pass_through(self):
        payload = {"Description": "text", "keys": ["a", "b"], "n": 3}
        self.assertEqual(format_dict_values(payload), payload)


class TestChartLabelsMatchTable(unittest.TestCase):
    """Bar labels are baked into the PNG, so they must be pinned to the same precision."""

    def test_bar_labels_use_the_table_precision(self):
        for module in MODULES_LABELLING_PROPORTIONS:
            path = os.path.join(METRICS_DIR, module)
            with open(path, encoding="utf-8") as handle:
                found = BAR_LABEL_FORMAT.findall(handle.read())
            with self.subTest(module=module):
                self.assertTrue(found, f"no bar value labels found in {module}")
                self.assertEqual(
                    sorted(set(found)),
                    [str(DISPLAY_DECIMALS)],
                    f"{module} labels bars at {sorted(set(found))} decimals; the table "
                    f"renders {DISPLAY_DECIMALS}. Keep both in step (issue #211).",
                )

    def test_the_table_renderer_pads_to_the_same_precision(self):
        # formatValue() decides the string shown in the scores table. Padding
        # past DISPLAY_DECIMALS appends zeros the value no longer carries and
        # makes the table read wider than the chart label beside it.
        with open(INSPECTOR_JS, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn(
            f"v.toFixed({DISPLAY_DECIMALS})",
            source,
            f"inspector.js formatValue() must render numbers at {DISPLAY_DECIMALS} "
            "decimals to match the chart labels (issue #211).",
        )


if __name__ == "__main__":
    unittest.main()
