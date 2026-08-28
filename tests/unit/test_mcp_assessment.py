"""The MCP assessment-tracking surface.

Discovery rides on the preflight the skill already performs, so an assessment
costs no extra round trip: ``list_metrics`` reports whether tracking is on.
"""

import json
import os
import sys
import tempfile
import types
import unittest

import pandas as pd
import pytest

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

pytest.importorskip("mcp")

from aidrin.mcp.server import (  # noqa: E402
    end_assessment,
    list_metrics,
    run_aidrin_metric,
    start_assessment,
)
from aidrin.telemetry import mlflow_sink  # noqa: E402


def _write_csv() -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    path = tmp.name
    tmp.close()
    pd.DataFrame({"age": [18, 30, None], "score": [0.1, 0.5, 0.9]}).to_csv(path, index=False)
    return path


class TestCatalogueShape(unittest.TestCase):
    def setUp(self):
        mlflow_sink.reset()
        for var in ("AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI"):
            os.environ.pop(var, None)

    def tearDown(self):
        mlflow_sink.reset()

    def test_metrics_stay_in_their_own_key(self):
        """The skill iterates the category mapping; a stray sibling would read
        as a category."""
        payload = json.loads(list_metrics())
        self.assertIn("metrics", payload)
        self.assertIsInstance(payload["metrics"], dict)
        for category, entries in payload["metrics"].items():
            self.assertIsInstance(entries, list, f"{category} is not a list of metrics")

    def test_reports_tracking_disabled(self):
        self.assertFalse(json.loads(list_metrics())["mlflow_enabled"])

    def test_start_assessment_reports_disabled_rather_than_failing(self):
        payload = json.loads(start_assessment("/tmp/whatever.csv"))
        self.assertEqual(payload["tracking"], "disabled")
        self.assertIsNone(payload["session_id"])


@unittest.skipUnless(
    __import__("importlib").util.find_spec("mlflow"), "requires the [mlflow] extra"
)
class TestTrackedAssessment(unittest.TestCase):
    def setUp(self):
        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-mcp-test"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")
        self.csv = _write_csv()

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED",
            "MLFLOW_TRACKING_URI",
            "AIDRIN_MLFLOW_EXPERIMENT",
            "MLFLOW_ALLOW_FILE_STORE",
        ):
            os.environ.pop(var, None)
        try:
            os.unlink(self.csv)
        except OSError:
            pass

    def _runs(self):
        exp = self.client.get_experiment_by_name("aidrin-mcp-test")
        self.assertIsNotNone(exp)
        return self.client.search_runs([exp.experiment_id])

    def test_reports_tracking_enabled(self):
        self.assertTrue(json.loads(list_metrics())["mlflow_enabled"])

    def test_full_assessment_flow(self):
        session_id = json.loads(start_assessment(self.csv))["session_id"]
        self.assertIsNotNone(session_id)

        run_aidrin_metric(self.csv, "completeness", session_id=session_id)
        run_aidrin_metric(self.csv, "duplicity", session_id=session_id)
        end_assessment(session_id)

        runs = self._runs()
        children = [r for r in runs if r.data.tags.get("aidrin.metric")]
        parents = [r for r in runs if not r.data.tags.get("aidrin.metric")]
        self.assertEqual(len(children), 2)
        self.assertEqual(len(parents), 1)
        self.assertEqual(parents[0].data.tags["aidrin.interface"], "mcp")
        self.assertIn("aidrin.quality.completeness", parents[0].data.metrics)

    def test_metric_without_a_session_id_is_untracked(self):
        run_aidrin_metric(self.csv, "completeness")
        exp = self.client.get_experiment_by_name("aidrin-mcp-test")
        runs = self.client.search_runs([exp.experiment_id]) if exp else []
        self.assertEqual(len(runs), 0)

    def test_report_is_attached_to_the_parent_run(self):
        session_id = json.loads(start_assessment(self.csv))["session_id"]
        run_aidrin_metric(self.csv, "completeness", session_id=session_id)

        report = os.path.join(self.tmp, "report.md")
        with open(report, "w") as fh:
            fh.write("# Readiness report\n")
        end_assessment(session_id, report_path=report)

        parent = [r for r in self._runs() if not r.data.tags.get("aidrin.metric")][0]
        artifacts = [a.path for a in self.client.list_artifacts(parent.info.run_id)]
        self.assertIn("report.md", artifacts)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(
    __import__("importlib").util.find_spec("mlflow"), "requires the [mlflow] extra"
)
class TestSurfaceIsAttributedCorrectly(unittest.TestCase):
    """A tool called over MCP must not record itself as a CLI run.

    ``run_data_quality_check`` and ``run_batch`` go through
    ``run_batch_metrics``, which opens its own session.  Surface is a property
    of the process, not of the call.
    """

    def setUp(self):
        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-interface"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")
        self.csv = _write_csv()

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
            "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE",
        ):
            os.environ.pop(var, None)
        try:
            os.unlink(self.csv)
        except OSError:
            pass

    def _assessments(self):
        exp = self.client.get_experiment_by_name("aidrin-interface")
        return [
            r for r in self.client.search_runs([exp.experiment_id])
            if r.data.tags.get("aidrin.run_type") == "assessment"
        ]

    def test_implicit_sessions_from_mcp_are_tagged_mcp(self):
        from aidrin.mcp.server import run_data_quality_check

        run_data_quality_check(self.csv)
        surfaces = {r.data.tags.get("aidrin.interface") for r in self._assessments()}
        self.assertEqual(surfaces, {"mcp"})

    def test_explicit_assessments_are_tagged_mcp(self):
        session_id = json.loads(start_assessment(self.csv))["session_id"]
        run_aidrin_metric(self.csv, "completeness", session_id=session_id)
        end_assessment(session_id)
        surfaces = {r.data.tags.get("aidrin.interface") for r in self._assessments()}
        self.assertEqual(surfaces, {"mcp"})
