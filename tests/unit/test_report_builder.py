"""Unit tests for aidrin.report.builder and headless run_readiness_report."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from aidrin.headless.runners import _build_file_info
from aidrin.report.builder import build_readiness_report, build_readiness_section
from aidrin.report.registry import SECTION_BUILDERS, SECTION_RESPONSE_KEYS

_REPO = Path(__file__).resolve().parents[2]
_FAIR_SAMPLE = _REPO / "examples" / "sample_data" / "dcat" / "BUTTER-E.json"


def _write_csv(df: pd.DataFrame) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return tmp.name


class TestBuildReadinessReport(unittest.TestCase):
    def setUp(self):
        self.csv = _write_csv(
            pd.DataFrame(
                {
                    "age": [21, 34, 45, 52, 29],
                    "income": [30_000, 55_000, 70_000, 40_000, 60_000],
                    "sex": ["M", "F", "F", "M", "F"],
                    "label": ["a", "b", "a", "b", "a"],
                }
            )
        )
        self.file_info = _build_file_info(self.csv, None, None)

    def tearDown(self):
        try:
            os.unlink(self.csv)
        except OSError:
            pass

    def test_section_response_keys_match_web_shape(self):
        report = build_readiness_report(self.file_info)
        self.assertTrue(report["success"])
        for slug, key in SECTION_RESPONSE_KEYS.items():
            self.assertIn(slug, SECTION_BUILDERS)
            self.assertIn(key, report)
            self.assertIsInstance(report[key], dict)
            self.assertIn("build_time_seconds", report[key])
        self.assertNotIn("fair_compliance", report)

    def test_fair_data_attached_when_provided(self):
        fair = {"FAIR Compliance Checks": {"Total Checks": "1/1"}}
        report = build_readiness_report(self.file_info, fair_data=fair)
        self.assertEqual(report["fair_compliance"], fair)

    def test_unknown_section_returns_none(self):
        self.assertIsNone(build_readiness_section("not-a-section", self.file_info))

    def test_builder_exception_uses_generic_error_message(self):
        def _boom(_file_info, include_visualizations=False):
            raise RuntimeError("secret-detail")

        result = build_readiness_section(
            "data-quality",
            self.file_info,
            builders={"data-quality": _boom},
            error_message="This section could not be computed.",
        )
        self.assertEqual(result, {"error": "This section could not be computed."})


class TestRunReadinessReport(unittest.TestCase):
    def setUp(self):
        self.csv = _write_csv(
            pd.DataFrame(
                {
                    "age": [1, 2, 3, 4],
                    "group": ["x", "y", "x", "y"],
                }
            )
        )

    def tearDown(self):
        try:
            os.unlink(self.csv)
        except OSError:
            pass

    def test_omits_fair_and_chart_payloads_by_default(self):
        from aidrin.headless import run_readiness_report

        report = run_readiness_report(self.csv)
        self.assertTrue(report["success"])
        self.assertNotIn("fair_compliance", report)
        # Builders leave chart fields empty; do not substring-strip the tree
        # (that would also drop column names containing "plot" / "visualization").
        dumped = json.dumps(report)
        self.assertNotIn("iVBORw", dumped)
        self.assertTrue(
            report["dataset_overview"].get("visualizations_deferred", False)
        )

    def test_preserves_columns_whose_names_look_like_chart_keys(self):
        from aidrin.headless import run_readiness_report

        csv = _write_csv(
            pd.DataFrame(
                {
                    "plot_id": [1, 2],
                    "plot_area": [10.5, 12.0],
                    "yield": [100, 110],
                    "region": ["A", "B"],
                }
            )
        )
        try:
            report = run_readiness_report(csv)
            scores = (
                report["data_quality"]["details"]["completeness"]["scores"]
            )
            self.assertEqual(
                set(scores),
                {"plot_id", "plot_area", "yield", "region"},
            )
            summary = report["dataset_overview"]["numerical_summary"]
            self.assertIn("plot_id", summary)
            self.assertIn("plot_area", summary)
            self.assertIn("yield", summary)
        finally:
            os.unlink(csv)

    def test_attaches_fair_compliance_without_pie_chart(self):
        from aidrin.headless import run_readiness_report

        report = run_readiness_report(
            self.csv,
            fair_metadata=str(_FAIR_SAMPLE),
            fair_standard="dcat-us-1.1",
        )
        self.assertIn("fair_compliance", report)
        self.assertEqual(
            report["fair_compliance"]["FAIR Compliance Checks"]["Total Checks"],
            "20/26",
        )
        self.assertNotIn("Pie chart", report["fair_compliance"])

    def test_missing_file_raises(self):
        from aidrin.headless import run_readiness_report

        with self.assertRaises(ValueError) as ctx:
            run_readiness_report("/no/such/dataset.csv")
        self.assertIn("File not found", str(ctx.exception))

    def test_selected_keys_does_not_break_overview(self):
        from aidrin.headless import run_readiness_report

        h5 = _REPO / "examples" / "sample_data" / "h5" / "unit_audit_demo.h5"
        report = run_readiness_report(
            str(h5),
            selected_keys=["environment/temperature", "environment/pressure"],
        )
        overview = report["dataset_overview"]
        self.assertNotIn("error", overview)
        self.assertEqual(overview["file_metadata"]["columns"], 2)

    def test_include_visualizations_embeds_overview_charts(self):
        from aidrin.headless import run_readiness_report

        report = run_readiness_report(self.csv, include_visualizations=True)
        overview = report["dataset_overview"]
        self.assertFalse(overview.get("visualizations_deferred", True))
        self.assertIn("histograms", overview)
        self.assertIn("histogram_bars", overview)
        self.assertIn("categorical_charts", overview)
        self.assertTrue(overview["histograms"] or overview["histogram_bars"])
        self.assertIn("iVBORw", json.dumps(overview))


class TestRunReadinessReportPdf(unittest.TestCase):
    def setUp(self):
        self.csv = _write_csv(pd.DataFrame({"a": [1, 2], "b": [3, 4]}))

    def tearDown(self):
        try:
            os.unlink(self.csv)
        except OSError:
            pass

    def test_invalid_mode_raises(self):
        from aidrin.headless import run_readiness_report_pdf

        with self.assertRaises(ValueError) as ctx:
            run_readiness_report_pdf(self.csv, mode="nope")
        self.assertIn("scorecard", str(ctx.exception))

    @patch(
        "aidrin.report.pdf.render_readiness_report_pdf",
        return_value=b"%PDF-1.4 mock",
    )
    @patch(
        "aidrin.report.pdf.build_pdf_context",
        return_value={"file_name": "x.csv"},
    )
    def test_scorecard_returns_pdf_bytes(self, mock_build_ctx, mock_render):
        from aidrin.headless import run_readiness_report_pdf

        sections = {
            slug: {"grade": 1.0, "grade_status": "good", "kpis": []}
            for slug in SECTION_BUILDERS
        }
        pdf = run_readiness_report_pdf(
            self.csv,
            mode="scorecard",
            sections=sections,
        )
        self.assertEqual(pdf, b"%PDF-1.4 mock")
        mock_build_ctx.assert_called_once()
        self.assertFalse(mock_build_ctx.call_args.kwargs["include_details"])
        mock_render.assert_called_once_with({"file_name": "x.csv"})

    @patch(
        "aidrin.report.pdf.render_readiness_report_pdf",
        return_value=b"%PDF-1.4 mock",
    )
    @patch(
        "aidrin.report.pdf.build_pdf_context",
        return_value={"file_name": "x.csv"},
    )
    def test_empty_section_errors_harvests_inline_errors(
        self, mock_build_ctx, _mock_render
    ):
        """Empty section_errors={} must still pick up inline section 'error' keys."""
        from aidrin.headless import run_readiness_report_pdf

        sections = {
            slug: {"grade": 1.0, "grade_status": "good", "kpis": []}
            for slug in SECTION_BUILDERS
        }
        sections["impact-on-ai"] = {
            "error": "Not enough usable columns for correlation analysis after pruning.",
            "columns_analyzed": [],
        }

        run_readiness_report_pdf(
            self.csv,
            sections=sections,
            section_errors={},
        )

        errors = mock_build_ctx.call_args.kwargs["section_errors"]
        self.assertEqual(
            errors["impact-on-ai"],
            "Not enough usable columns for correlation analysis after pruning.",
        )

    @patch(
        "aidrin.report.pdf.render_readiness_report_pdf",
        return_value=b"%PDF-1.4 mock",
    )
    @patch(
        "aidrin.report.pdf.build_pdf_context",
        return_value={"file_name": "x.csv"},
    )
    def test_response_keyed_sections_are_remapped_to_slugs(
        self, mock_build_ctx, _mock_render
    ):
        """run_readiness_report() underscore keys should remap to PDF slugs."""
        from aidrin.headless import run_readiness_report_pdf

        sections = {
            "dataset_overview": {
                "file_size_bytes": 100,
                "numerical_summary": {},
                "categorical_summary": {},
            },
            "data_quality": {"grade": 1.0, "grade_status": "good", "kpis": []},
            "impact_on_ai": {"error": "boom"},
            "fairness_bias": {"grade": 1.0, "grade_status": "good", "kpis": []},
            "data_governance": {"grade": 1.0, "grade_status": "good", "kpis": []},
        }

        run_readiness_report_pdf(self.csv, sections=sections)

        passed = mock_build_ctx.call_args.kwargs["sections"]
        self.assertIn("dataset-overview", passed)
        self.assertNotIn("dataset_overview", passed)
        self.assertEqual(
            mock_build_ctx.call_args.kwargs["section_errors"]["impact-on-ai"],
            "boom",
        )


if __name__ == "__main__":
    unittest.main()
