"""``run_metric`` and ``run_batch_metrics`` record to MLflow when it is enabled.

The session is threaded through as an id string rather than kept as hidden
process state: the MCP server is one process serving many tool calls, and a
single "current session" would be wrong the moment two assessments overlap.
"""

import os
import sys
import tempfile
import types
import unittest

import pandas as pd

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

try:
    import mlflow  # noqa: F401

    HAS_MLFLOW = True
except ImportError:  # pragma: no cover
    HAS_MLFLOW = False

from aidrin.headless.api import run_batch_metrics, run_metric  # noqa: E402
from aidrin.telemetry import mlflow_sink  # noqa: E402


def _write_csv() -> str:
    df = pd.DataFrame({"age": [31, 42, None, 25], "score": [0.5, 0.7, 0.2, 0.9]})
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return tmp.name


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestRunMetricTracking(unittest.TestCase):
    def setUp(self):
        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-test"
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
        exp = self.client.get_experiment_by_name("aidrin-test")
        self.assertIsNotNone(exp)
        return self.client.search_runs([exp.experiment_id])

    def test_metric_run_records_the_headline_score(self):
        session = mlflow_sink.start_session(file_path=self.csv, interface="mcp")
        run_metric(
            "completeness", self.csv, save_images=False, session_id=session.session_id
        )
        mlflow_sink.end_session(session)

        child = [r for r in self._runs() if r.data.tags.get("aidrin.metric")][0]
        self.assertIn("aidrin.quality.completeness", child.data.metrics)
        self.assertEqual(child.data.tags["aidrin.metric"], "completeness")

    def test_result_is_identical_whether_or_not_tracking_is_on(self):
        session = mlflow_sink.start_session(file_path=self.csv)
        tracked = run_metric(
            "completeness", self.csv, save_images=False, session_id=session.session_id
        )
        mlflow_sink.end_session(session)
        untracked = run_metric("completeness", self.csv, save_images=False)
        self.assertEqual(tracked, untracked)

    def test_no_session_id_means_no_run(self):
        run_metric("completeness", self.csv, save_images=False)
        exp = self.client.get_experiment_by_name("aidrin-test")
        runs = self.client.search_runs([exp.experiment_id]) if exp else []
        self.assertEqual(len(runs), 0)

    def test_batch_rolls_up_onto_one_parent(self):
        results = run_batch_metrics(
            {
                "file_path": self.csv,
                "metrics": ["completeness", "duplicity", "outliers"],
                "save_images": False,
            }
        )
        self.assertEqual(len(results), 3)

        runs = self._runs()
        parents = [r for r in runs if not r.data.tags.get("aidrin.metric")]
        children = [r for r in runs if r.data.tags.get("aidrin.metric")]
        self.assertEqual(len(children), 3)
        self.assertEqual(len(parents), 1, "batch must produce exactly one parent run")
        self.assertIn("aidrin.quality.completeness", parents[0].data.metrics)


class TestTrackingFailureCannotBreakMetrics(unittest.TestCase):
    def setUp(self):
        self.csv = _write_csv()

    def tearDown(self):
        mlflow_sink.reset()
        try:
            os.unlink(self.csv)
        except OSError:
            pass

    def test_result_unchanged_when_the_sink_raises(self):
        baseline = run_metric("completeness", self.csv, save_images=False)

        def _explode(*args, **kwargs):
            raise RuntimeError("tracking server is on fire")

        original = mlflow_sink.log_metric_result
        mlflow_sink.log_metric_result = _explode
        try:
            result = run_metric(
                "completeness", self.csv, save_images=False, session_id="whatever"
            )
        finally:
            mlflow_sink.log_metric_result = original

        self.assertEqual(result, baseline)


if __name__ == "__main__":
    unittest.main()
