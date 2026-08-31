"""Per-column values are logged on the metric run, and never roll up.

A metric run belongs to one dataset and one metric, so per-column keys there are
pure detail: nothing compares one dataset's ``completeness`` run against
another's. The assessment run is where cross-dataset comparison happens, so it
keeps only the aggregates; per-column keys would turn its Compare view into a
sparse grid the moment two datasets have different schemas.
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

from aidrin.telemetry.redaction import per_column  # noqa: E402


class TestExtraction(unittest.TestCase):
    def test_completeness_columns_are_extracted(self):
        result = {"Completeness scores": {"age": 1.0, "income": 0.82},
                  "Overall Completeness": 0.91}
        out = per_column("completeness", result)
        self.assertEqual(out["aidrin.column.completeness.age"], 1.0)
        self.assertEqual(out["aidrin.column.completeness.income"], 0.82)

    def test_nested_per_column_results_are_found(self):
        result = {"Outlier scores": {"age": 0.02, "Overall outlier score": 0.01}}
        out = per_column("outliers", result)
        self.assertIn("aidrin.column.outliers.age", out)

    def test_an_undeclared_metric_yields_nothing(self):
        self.assertEqual(per_column("hipaa_compliance", {"ssn": {"total_flags": 3}}), {})

    def test_non_finite_values_are_skipped(self):
        result = {"Skewness": {"constant_col": float("nan"), "age": 0.3}}
        out = per_column("skewness", result)
        self.assertNotIn("aidrin.column.skewness.constant_col", out)
        self.assertIn("aidrin.column.skewness.age", out)


class TestKeysAreSafe(unittest.TestCase):
    """MLflow allows alphanumerics, underscore, dash, dot, slash and space."""

    LEGAL = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./ ")

    def test_illegal_characters_are_replaced(self):
        result = {"Completeness scores": {"Income (USD)": 0.9, "pct%": 0.5}}
        for key in per_column("completeness", result):
            self.assertTrue(set(key) <= self.LEGAL, f"illegal characters in {key!r}")

    def test_colliding_column_names_stay_distinct(self):
        """`Income (USD)` and `Income [USD]` sanitise identically.

        MLflow does not reject a repeated key; it appends another step to the
        same series, so two columns would silently merge into one chart.
        """
        result = {"Completeness scores": {"Income (USD)": 0.9, "Income [USD]": 0.4}}
        out = per_column("completeness", result)
        self.assertEqual(len(out), 2, f"columns merged into one key: {out}")
        self.assertEqual(sorted(out.values()), [0.4, 0.9])

    def test_long_column_names_stay_within_the_limit(self):
        result = {"Completeness scores": {"c" * 400: 0.5}}
        for key in per_column("completeness", result):
            self.assertLessEqual(len(key), 250)


@unittest.skipUnless(
    __import__("importlib").util.find_spec("mlflow"), "requires the [mlflow] extra"
)
class TestRollupStaysClean(unittest.TestCase):
    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        from aidrin.telemetry import mlflow_sink

        self.sink = mlflow_sink
        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-percolumn"
        os.environ.pop("AIDRIN_MLFLOW_LOG_DATA_DETAILS", None)
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        self.sink.reset()
        for var in ("AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
                    "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE",
                    "AIDRIN_MLFLOW_LOG_DATA_DETAILS"):
            os.environ.pop(var, None)

    def _run(self):
        session = self.sink.start_session(file_path="/tmp/d.csv")
        self.sink.log_metric_result(
            session, "completeness",
            {"Completeness scores": {"age": 1.0, "income": 0.8},
             "Overall Completeness": 0.9},
            0.1, "/tmp/d.csv",
        )
        self.sink.end_session(session)
        exp = self.client.get_experiment_by_name("aidrin-percolumn")
        runs = self.client.search_runs([exp.experiment_id])
        return (
            [r for r in runs if r.data.tags.get("aidrin.run_type") == "assessment"][0],
            [r for r in runs if r.data.tags.get("aidrin.run_type") == "metric"][0],
        )

    def test_the_metric_run_carries_per_column_values(self):
        _, child = self._run()
        self.assertEqual(child.data.metrics["aidrin.column.completeness.age"], 1.0)
        self.assertEqual(child.data.metrics["aidrin.column.completeness.income"], 0.8)
        self.assertEqual(child.data.metrics["aidrin.quality.completeness"], 0.9)

    def test_the_assessment_run_keeps_only_aggregates(self):
        parent, _ = self._run()
        leaked = [k for k in parent.data.metrics if k.startswith("aidrin.column.")]
        self.assertEqual(leaked, [], f"per-column keys rolled up: {leaked}")
        self.assertIn("aidrin.quality.completeness", parent.data.metrics)

    def test_opting_out_of_data_details_withholds_column_names(self):
        os.environ["AIDRIN_MLFLOW_LOG_DATA_DETAILS"] = "0"
        self.sink.reset()
        _, child = self._run()
        leaked = [k for k in child.data.metrics if k.startswith("aidrin.column.")]
        self.assertEqual(leaked, [], "column names published despite the opt-out")


if __name__ == "__main__":
    unittest.main()
