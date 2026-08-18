"""Unit tests for full readiness report PDF details."""

import unittest

from web.readiness.pdf_details import (
    build_pdf_section_details,
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
