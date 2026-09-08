"""Unit tests for full readiness report PDF details."""

import unittest

from web.readiness.pdf_details import (
    _fmt_compact_num,
    build_pdf_section_details,
    prepare_fairness_details,
    prepare_fair_compliance_details,
    prepare_governance_details,
    prepare_overview_details,
)


class TestReadinessPdfDetails(unittest.TestCase):
    def test_prepare_overview_details_includes_table_and_charts(self):
        section = {
            "numerical_summary": {"age": {"count": 10, "mean": 35.5}},
            "numerical_summary_meta": {"total": 1, "shown": 1},
            "feature_profiles_meta": {"truncated": False},
        }
        viz = {
            "categorical_charts": {"city": "abc123"},
            "histograms": {"age_light": "def456"},
        }
        details = prepare_overview_details(section, viz)
        self.assertIsNotNone(details)
        types = [b["type"] for b in details["blocks"]]
        self.assertIn("table", types)
        self.assertIn("chart_group", types)

    def test_overview_numerical_summary_fits_compact_pdf_columns(self):
        section = {
            "numerical_summary": {
                "age": {
                    "count": 100.0,
                    "min": 1.0,
                    "25th percentile": 10.0,
                    "50th percentile": 20.0,
                    "mean": 21.5,
                    "75th percentile": 30.0,
                    "max": 1.2e8,
                    "std": 3.4e7,
                }
            },
            "numerical_summary_meta": {"total": 1, "shown": 1},
        }
        details = prepare_overview_details(section, {})
        table = details["blocks"][0]
        self.assertEqual(
            table["headers"],
            ["Feature", "count", "min", "25%", "50%", "mean", "75%", "max", "std"],
        )
        row = table["rows"][0]
        self.assertEqual(row[0], "age")
        self.assertEqual(row[-2], "1.200e+08")
        self.assertEqual(row[-1], "3.400e+07")
        self.assertTrue(all(len(cell) <= 12 for cell in row[1:]))

    def test_fmt_compact_num_keeps_ordinary_values_short(self):
        self.assertEqual(_fmt_compact_num(100.0), "100")
        self.assertEqual(_fmt_compact_num(21.5), "21.50")
        self.assertEqual(_fmt_compact_num(0.00012), "1.200e-04")

    def test_governance_high_linkage_single_block_in_pdf_context(self):
        section = {
            "details": {
                "single_attribute_risk": {
                    "by_quasi_identifier": {"zip": {"mean_risk": 0.42}},
                }
            },
            "auto_selection": {"selection_criteria": {"quasi_identifiers": {}}},
        }
        details = prepare_governance_details(section, {})
        self.assertIsNotNone(details)
        self.assertTrue(any(b["type"] == "table" for b in details["blocks"]))

    def test_prepare_governance_details_privacy_charts_and_excluded_qi(self):
        section = {
            "details": {
                "k_anonymity": {"visualization": "k123"},
                "l_diversity": {"visualization": "l123"},
                "t_closeness": {"visualization": "t123"},
            },
            "auto_selection": {
                "selection_criteria": {
                    "quasi_identifiers": {
                        "excluded": [
                            {"feature": "ssn", "reason": "high cardinality"},
                            {"feature": "email", "reason": "direct identifier"},
                        ],
                        "excluded_meta": {"total": 2},
                    }
                }
            },
        }
        viz = {
            "k_anonymity": "k123",
            "l_diversity": "l123",
            "t_closeness": "t123",
        }
        details = prepare_governance_details(section, viz)
        self.assertIsNotNone(details)
        privacy = details["blocks"][0]
        self.assertEqual(privacy["type"], "chart_group")
        self.assertEqual(privacy["layout"], "two_per_row")
        self.assertEqual(len(privacy["charts"]), 3)
        excluded = details["blocks"][-1]
        self.assertEqual(excluded["type"], "table")
        self.assertEqual(excluded["layout"], "paired_exclusions")
        self.assertEqual(excluded["title"], "Excluded quasi-identifier candidates (2)")
        self.assertEqual(
            excluded["rows"][0],
            ["ssn", "high cardinality", "email", "direct identifier"],
        )

    def test_prepare_fairness_details_includes_excluded_sensitive_candidates(self):
        section = {
            "details": {
                "representation_rate": {
                    "visualizations": {"gender": "rep123"},
                },
                "class_imbalance": {"visualization": "ci123"},
                "statistical_rate": {
                    "visualization": "sr123",
                    "sensitive": "gender",
                    "target": "outcome",
                },
            },
            "auto_selection": {
                "selection_criteria": {
                    "target_column": {"selected": "outcome"},
                    "sensitive_attributes": {
                        "excluded": [
                            {"feature": "id", "reason": "identifier-like"},
                            {"feature": "notes", "reason": "free text"},
                        ],
                        "excluded_meta": {"total": 2},
                    },
                }
            },
        }
        details = prepare_fairness_details(section, {})
        self.assertIsNotNone(details)
        rep_group = details["blocks"][0]
        self.assertEqual(rep_group["type"], "chart_group")
        self.assertEqual(rep_group["layout"], "single_per_row")
        self.assertEqual(rep_group["charts"][0]["label"], "gender")
        self.assertEqual(details["blocks"][1]["size"], "class_imbalance")
        self.assertEqual(details["blocks"][2]["size"], "statistical_rate")
        excluded = details["blocks"][-1]
        self.assertEqual(excluded["type"], "table")
        self.assertEqual(excluded["layout"], "paired_exclusions")
        self.assertEqual(excluded["title"], "Excluded sensitive candidates (2)")
        self.assertEqual(excluded["headers"], [
            "Feature",
            "Reason for exclusion",
            "Feature",
            "Reason for exclusion",
        ])
        self.assertEqual(excluded["rows"][0], ["id", "identifier-like", "notes", "free text"])

    def test_build_pdf_section_details_keys(self):
        sections = {
            "dataset-overview": {},
            "data-quality": {},
            "impact-on-ai": {},
            "fairness-bias": {},
            "data-governance": {},
        }
        result = build_pdf_section_details(sections, {})
        self.assertEqual(
            set(result.keys()),
            {"overview", "data_quality", "impact", "fairness", "governance"},
        )

    def test_prepare_fair_compliance_details_skips_principles_and_chart(self):
        details = prepare_fair_compliance_details(
            {
                "FAIR Compliance Checks": {"Total Checks": "2/4", "Findable Checks": "1/1"},
                "Findable": {"identifier": "x"},
                "Accessible": {"accessURL": "https://example.org"},
                "Other": {"extra_field": "value"},
                "Original Metadata": {"nested": {"title": "Dataset"}},
                "Pie chart": "abc",
            }
        )
        self.assertIsNotNone(details)
        titles = [b["title"] for b in details["blocks"]]
        self.assertEqual(details["heading"], "Detailed results")
        self.assertIn("FAIR Compliance Checks", titles)
        self.assertIn("Other", titles)
        self.assertIn("Original Metadata", titles)
        self.assertNotIn("Findable", titles)
        self.assertNotIn("Accessible", titles)
        self.assertNotIn("Pie chart", titles)


if __name__ == "__main__":
    unittest.main()
