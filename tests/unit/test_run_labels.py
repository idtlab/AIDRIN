"""Metric runs identify themselves in the runs table.

Two gaps this covers: the interface column was blank on metric runs because only
the assessment run carried the tag, and a metric run's name alone does not say
which readiness dimension it belongs to.
"""

import os
import sys
import types
import unittest

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

from aidrin.telemetry.redaction import label_for  # noqa: E402


class TestLabels(unittest.TestCase):
    def test_label_is_pillar_then_metric_name(self):
        self.assertEqual(label_for("completeness"), "Data Quality: Completeness")
        self.assertEqual(
            label_for("constant_feature_count"), "Data Structure: Constant Feature Count"
        )
        self.assertEqual(
            label_for("class_imbalance"), "Fairness and Bias: Class Imbalance"
        )
        self.assertEqual(
            label_for("correlations"), "Impact of Data on AI: Correlations"
        )

    def test_established_spellings_are_preserved(self):
        """Title-casing would give "K Anonymity" and "Hipaa Compliance"."""
        self.assertEqual(label_for("k_anonymity"), "Data Governance: k-Anonymity")
        self.assertEqual(label_for("l_diversity"), "Data Governance: l-Diversity")
        self.assertEqual(label_for("t_closeness"), "Data Governance: t-Closeness")
        self.assertEqual(
            label_for("hipaa_compliance"), "Data Governance: HIPAA Compliance"
        )

    def test_an_unknown_metric_falls_back_to_its_name(self):
        self.assertEqual(label_for("someones_custom_metric"), "Someones Custom Metric")

    def test_every_registry_metric_has_a_pillar(self):
        from aidrin.headless.api import METRIC_REGISTRY

        for metric_key in METRIC_REGISTRY:
            with self.subTest(metric=metric_key):
                self.assertIn(": ", label_for(metric_key), "no pillar in the label")


@unittest.skipUnless(
    __import__("importlib").util.find_spec("mlflow"), "requires the [mlflow] extra"
)
class TestRunsAreLabelled(unittest.TestCase):
    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        from aidrin.telemetry import mlflow_sink

        self.sink = mlflow_sink
        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-labels"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        self.sink.reset()
        for var in ("AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
                    "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE"):
            os.environ.pop(var, None)

    def _runs(self):
        session = self.sink.start_session(file_path="/tmp/d.csv", interface="mcp")
        self.sink.log_metric_result(
            session, "k_anonymity", {"k-Value": 4}, 0.1, "/tmp/d.csv"
        )
        self.sink.end_session(session)
        exp = self.client.get_experiment_by_name("aidrin-labels")
        runs = self.client.search_runs([exp.experiment_id])
        return (
            [r for r in runs if r.data.tags.get("aidrin.run_type") == "assessment"][0],
            [r for r in runs if r.data.tags.get("aidrin.run_type") == "metric"][0],
        )

    def test_the_interface_column_is_filled_on_both_run_types(self):
        parent, child = self._runs()
        self.assertEqual(parent.data.tags.get("aidrin.interface"), "mcp")
        self.assertEqual(child.data.tags.get("aidrin.interface"), "mcp")

    def test_a_metric_run_is_described_by_pillar_and_name(self):
        _, child = self._runs()
        self.assertEqual(
            child.data.tags.get("mlflow.note.content"), "Data Governance: k-Anonymity"
        )

    def test_the_assessment_run_is_described(self):
        parent, _ = self._runs()
        self.assertEqual(parent.data.tags.get("mlflow.note.content"), "AIDRIN Assessment")
