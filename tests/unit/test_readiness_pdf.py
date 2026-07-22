"""Unit tests for readiness report PDF context and rendering."""

import unittest
from unittest.mock import MagicMock, patch

from web.readiness.pdf import (
    FootnoteRegistry,
    _cap_na_rows,
    _fair_value_rows,
    _na_row,
    _prepare_fair_compliance,
    _prepare_governance,
    _prepare_overview,
    build_pdf_context,
    fmt_pct,
    pdf_filename,
    render_readiness_report_pdf,
)


class TestReadinessPdfFormatters(unittest.TestCase):
    def test_fmt_pct(self):
        self.assertEqual(fmt_pct(0.912), "91.20%")
        self.assertEqual(fmt_pct(None), "N/A")


class TestReadinessPdfContext(unittest.TestCase):
    def test_prepare_overview_enriches_profiles(self):
        overview = _prepare_overview(
            {
                "file_metadata": {"datetime_count": 1, "boolean_count": 2},
                "feature_profiles": [
                    {
                        "feature": "age",
                        "type": "numerical",
                        "dtype": "int64",
                        "status": "good",
                    }
                ],
            }
        )
        self.assertEqual(overview["other_count"], 3)
        self.assertEqual(overview["profiles"][0]["type_abbr"], "N")
        self.assertEqual(overview["profiles"][0]["status_label"], "Good")

    def test_build_pdf_context_includes_overview(self):
        sections = {
            "dataset-overview": {
                "file_metadata": {"file_name": "data.csv", "rows": 10, "columns": 2},
                "feature_profiles": [
                    {
                        "feature": "age",
                        "type": "numerical",
                        "dtype": "int64",
                        "pct_missing": 0.0,
                        "n_unique": 10,
                        "pct_dominant": 0.1,
                        "status": "good",
                        "summary": "ok",
                    }
                ],
                "feature_profiles_meta": {"total": 1, "shown": 1, "truncated": False},
            },
            "data-quality": {
                "grade": 0.95,
                "grade_status": "good",
                "kpis": [
                    {
                        "id": "completeness",
                        "label": "Completeness",
                        "value": 0.95,
                        "status": "good",
                        "hint": "hint",
                    }
                ],
                "auto_selection": {
                    "selection_criteria": {
                        "analysis_scope": {
                            "selected": "all columns",
                            "rule": "rule",
                        }
                    }
                },
                "needs_attention": {},
            },
            "impact-on-ai": {
                "grade": 0.8,
                "grade_status": "warning",
                "kpis": [],
                "auto_selection": {"selection_criteria": {"columns_analyzed": {}}},
                "needs_attention": {},
            },
            "fairness-bias": {
                "grade": 0.8,
                "grade_status": "warning",
                "kpis": [],
                "auto_selection": {"selection_criteria": {}},
                "needs_attention": {},
            },
            "data-governance": {
                "grade": 0.8,
                "grade_status": "warning",
                "kpis": [],
                "auto_selection": {"selection_criteria": {}},
                "needs_attention": {},
            },
        }
        context = build_pdf_context(file_name="data.csv", sections=sections)
        self.assertEqual(context["file_name"], "data.csv")
        self.assertIn("overview", context)
        self.assertEqual(context["overview"]["profiles"][0]["type_abbr"], "N")
        self.assertTrue(context["glossary"])

    def test_footnote_registry_scopes_per_section(self):
        registry = FootnoteRegistry()
        dq = registry.section("data_quality")
        impact = registry.section("impact")
        self.assertIn("1", str(dq.ref("pct_missing")))
        self.assertIn("1", str(impact.ref("leakage_safety")))
        self.assertEqual(len(dq.entries()), 1)
        self.assertEqual(len(impact.entries()), 1)
        dq.ref("n_unique")
        self.assertEqual(len(dq.entries()), 2)
        self.assertEqual(dq.entries()[1]["term"], "# unique")

    def test_cap_na_rows_limits_tall_blocks(self):
        rows = [
            _na_row("a", secondary="detail"),
            _na_row("b", secondary="detail"),
            _na_row("c", secondary="detail"),
            _na_row("d", secondary="detail"),
            _na_row("e", secondary="detail"),
            _na_row("f", secondary="detail"),
        ]
        kept, more = _cap_na_rows(rows, line_budget=8.0, max_rows=6, min_rows=2)
        self.assertLessEqual(len(kept), 4)
        self.assertGreater(more, 0)

    def test_cap_na_rows_keeps_simple_rows_up_to_max(self):
        rows = [_na_row(f"feature-{i}", value="1.00%") for i in range(6)]
        kept, more = _cap_na_rows(rows, line_budget=10.0, max_rows=6, min_rows=2)
        self.assertEqual(len(kept), 6)
        self.assertEqual(more, 0)

    def test_governance_high_linkage_risk_single_block(self):
        gov = {
            "kpis": [],
            "auto_selection": {"selection_criteria": {}},
            "needs_attention": {
                "high_linkage_risk": [
                    {"metric": "MM Prosecutor", "feature": "zip", "mean_risk": 0.42},
                    {"metric": "MM Marketer", "feature": "dob", "mean_risk": 0.31},
                ]
            },
        }
        prepared = _prepare_governance(gov)
        linkage_blocks = [
            b for b in prepared["needs_attention"] if b.get("glossary_key") == "high_linkage_risk"
        ]
        self.assertEqual(len(linkage_blocks), 1)
        self.assertEqual(len(linkage_blocks[0]["rows"]), 2)
        self.assertIn("(2)", linkage_blocks[0]["title"])

    def test_fair_value_rows_marks_failed_checks(self):
        rows = _fair_value_rows(
            {
                "identifier": "doi:10.1234/example",
                "title": "CHECK FAILED ❌",
            }
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["found"])
        self.assertFalse(rows[1]["found"])
        self.assertEqual(rows[1]["status_label"], "Missing")

    def test_prepare_fair_compliance_includes_principle_rows(self):
        fair = {
            "FAIR Compliance Checks": {
                "Total Checks": "2/4",
                "Findable Checks": "1/2",
                "Accessible Checks": "1/2",
                "Interoperable Checks": "0/0",
                "Reusable Checks": "0/0",
            },
            "Findable": {"identifier": "x", "title": "CHECK FAILED ❌"},
        }
        prepared = _prepare_fair_compliance(fair)
        self.assertIsNotNone(prepared)
        findable = prepared["principles"][0]
        self.assertEqual(findable["name"], "Findable")
        self.assertEqual(len(findable["rows"]), 2)

    def test_pdf_filename_sanitizes_name(self):
        name = pdf_filename("my data (1).csv")
        self.assertTrue(name.startswith("readiness-report-my_data__1_"))
        self.assertTrue(name.endswith(".pdf"))


class TestReadinessPdfRender(unittest.TestCase):
    @patch("weasyprint.HTML")
    @patch("weasyprint.CSS")
    @patch("web.readiness.pdf.render_template", return_value="<html></html>")
    def test_render_readiness_report_pdf(self, _mock_template, _mock_css, mock_html):
        mock_instance = MagicMock()
        mock_instance.write_pdf.return_value = b"%PDF-1.4"
        mock_html.return_value = mock_instance
        app = MagicMock()
        app.root_path = "/tmp/web"
        result = render_readiness_report_pdf(app, {"file_name": "data.csv"})
        self.assertEqual(result, b"%PDF-1.4")
        mock_instance.write_pdf.assert_called_once()


if __name__ == "__main__":
    unittest.main()
