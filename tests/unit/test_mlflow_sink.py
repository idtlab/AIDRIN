"""The MLflow assessment-tracking sink.

Three invariants carry most of the weight here:

* Disabled is the default, and a disabled sink costs nothing and does nothing.
* The sink can never raise into ``run_metric`` — every AIDRIN surface funnels
  through it, and an exception there would destroy a computed result.
* Logging goes through ``MlflowClient`` only.  ``mlflow._active_run_stack``
  became thread-local in 2.18, and the MCP server dispatches sync tool functions
  on worker threads, so a fluent-API call would silently create a stray run
  instead of writing to the intended one.
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

try:
    import mlflow  # noqa: F401

    HAS_MLFLOW = True
except ImportError:  # pragma: no cover
    HAS_MLFLOW = False

from aidrin.telemetry import mlflow_sink  # noqa: E402


class TestDisabledByDefault(unittest.TestCase):
    def setUp(self):
        mlflow_sink.reset()
        for var in ("AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI"):
            os.environ.pop(var, None)

    def tearDown(self):
        mlflow_sink.reset()

    def test_not_enabled_without_configuration(self):
        self.assertFalse(mlflow_sink.is_enabled())

    def test_enabled_flag_alone_is_not_enough(self):
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        self.assertFalse(mlflow_sink.is_enabled(), "needs a tracking URI too")

    def test_every_entry_point_is_a_noop_when_disabled(self):
        session = mlflow_sink.start_session(file_path="/tmp/x.csv")
        self.assertIsNone(session)
        mlflow_sink.log_metric_result(None, "completeness", {"x": 1}, 0.1, "/tmp/x.csv")
        mlflow_sink.end_session(None)


class TestNeverUsesTheFluentApi(unittest.TestCase):
    def test_sink_source_contains_no_fluent_calls(self):
        """Cheap structural guard against the thread-local run-stack hazard."""
        import pathlib

        source = pathlib.Path(mlflow_sink.__file__).read_text()
        for forbidden in ("mlflow.log_metric", "mlflow.log_param", "mlflow.start_run",
                          "mlflow.log_artifact", "mlflow.set_tag", "mlflow.active_run"):
            self.assertNotIn(forbidden, source, f"fluent API call {forbidden}")


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestTrackingContent(unittest.TestCase):
    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        # The filesystem backend is in maintenance mode and refuses to construct
        # a client without this opt-out.
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-test"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED",
            "MLFLOW_TRACKING_URI",
            "AIDRIN_MLFLOW_EXPERIMENT",
            "MLFLOW_ALLOW_FILE_STORE",
        ):
            os.environ.pop(var, None)

    def _runs(self):
        exp = self.client.get_experiment_by_name("aidrin-test")
        self.assertIsNotNone(exp, "experiment was never created")
        return self.client.search_runs([exp.experiment_id])

    def test_is_enabled(self):
        self.assertTrue(mlflow_sink.is_enabled())

    def test_a_metric_produces_one_run_with_its_headline_score(self):
        session = mlflow_sink.start_session(file_path="/tmp/data.csv")
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": 0.83}, 0.25, "/tmp/data.csv"
        )
        mlflow_sink.end_session(session)

        metric_runs = [r for r in self._runs() if r.data.tags.get("aidrin.metric")]
        self.assertEqual(len(metric_runs), 1)
        run = metric_runs[0]
        self.assertAlmostEqual(run.data.metrics["aidrin.quality.completeness"], 0.83)
        self.assertGreater(run.data.metrics["aidrin.quality.runtime_seconds"], 0)

    def test_batch_produces_one_run_per_metric_plus_a_parent(self):
        session = mlflow_sink.start_session(file_path="/tmp/data.csv")
        for i in range(10):
            mlflow_sink.log_metric_result(
                session, "completeness", {"Overall Completeness": i / 10}, 0.1, "/tmp/d.csv"
            )
        mlflow_sink.end_session(session)

        runs = self._runs()
        metric_runs = [r for r in runs if r.data.tags.get("aidrin.metric")]
        parents = [r for r in runs if not r.data.tags.get("aidrin.metric")]
        self.assertEqual(len(metric_runs), 10)
        self.assertEqual(len(parents), 1, "expected exactly one parent run")

    def test_metric_runs_are_nested_under_the_parent(self):
        session = mlflow_sink.start_session(file_path="/tmp/data.csv")
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": 0.5}, 0.1, "/tmp/d.csv"
        )
        mlflow_sink.end_session(session)

        runs = self._runs()
        parent = [r for r in runs if not r.data.tags.get("aidrin.metric")][0]
        child = [r for r in runs if r.data.tags.get("aidrin.metric")][0]
        self.assertEqual(child.data.tags["mlflow.parentRunId"], parent.info.run_id)
        self.assertEqual(child.data.tags["aidrin.session_id"], parent.data.tags["aidrin.session_id"])

    def test_no_run_is_left_running(self):
        session = mlflow_sink.start_session(file_path="/tmp/data.csv")
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": 0.5}, 0.1, "/tmp/d.csv"
        )
        mlflow_sink.end_session(session)

        for run in self._runs():
            self.assertEqual(run.info.status, "FINISHED", f"{run.info.run_id} left open")

    def test_file_path_can_be_hashed_by_opting_out(self):
        os.environ["AIDRIN_MLFLOW_LOG_DATA_DETAILS"] = "0"
        mlflow_sink.reset()
        session = mlflow_sink.start_session(file_path="/data/patients/MRN-4417723.csv")
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": 0.5}, 0.1,
            "/data/patients/MRN-4417723.csv",
        )
        mlflow_sink.end_session(session)

        rendered = repr([(r.data.params, r.data.tags) for r in self._runs()])
        self.assertNotIn("MRN-4417723", rendered)

    def test_undeclared_metric_logs_runtime_but_no_result_body(self):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.log_metric_result(
            session,
            "statistical_rates",
            {"Statistical Rates": {"female": 0.31, "male": 0.69}},
            0.1,
            "/tmp/d.csv",
        )
        mlflow_sink.end_session(session)

        run = [r for r in self._runs() if r.data.tags.get("aidrin.metric")][0]
        rendered = repr((run.data.params, run.data.tags, run.data.metrics))
        self.assertNotIn("female", rendered)
        self.assertIn("aidrin.fairness.runtime_seconds", run.data.metrics)

    def test_non_finite_score_is_skipped_and_recorded(self):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": float("nan")}, 0.1, "/tmp/d.csv"
        )
        mlflow_sink.end_session(session)

        run = [r for r in self._runs() if r.data.tags.get("aidrin.metric")][0]
        self.assertNotIn("aidrin.quality.completeness", run.data.metrics)
        self.assertIn("aidrin.quality.completeness", run.data.tags.get("aidrin.skipped_metrics", ""))


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestSinkFailuresAreContained(unittest.TestCase):
    def tearDown(self):
        mlflow_sink.reset()
        os.environ.pop("MLFLOW_TRACKING_URI", None)
        os.environ.pop("AIDRIN_MLFLOW_ENABLED", None)

    def test_unusable_tracking_uri_disables_rather_than_raises(self):
        os.environ["MLFLOW_TRACKING_URI"] = "file:///nonexistent-root/mlruns"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ.pop("MLFLOW_ALLOW_FILE_STORE", None)
        mlflow_sink.reset()

        # Must not raise, whatever the backend does.
        self.assertFalse(mlflow_sink.is_enabled())

    def test_logging_never_raises_when_the_client_explodes(self):
        os.environ["MLFLOW_TRACKING_URI"] = "http://127.0.0.1:1"  # nothing listening
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        mlflow_sink.reset()

        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": 0.5}, 0.1, "/tmp/d.csv"
        )
        mlflow_sink.end_session(session)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestDatasetIsRecorded(unittest.TestCase):
    """MLflow's Dataset column comes from log_inputs, not from a tag.

    Without it the column is blank and runs cannot be grouped by dataset in the
    UI, which is the whole point of tracking a dataset's readiness over time.
    """

    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-dataset"
        os.environ.pop("AIDRIN_MLFLOW_LOG_DATA_DETAILS", None)
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI", "AIDRIN_MLFLOW_EXPERIMENT",
            "MLFLOW_ALLOW_FILE_STORE", "AIDRIN_MLFLOW_LOG_DATA_DETAILS",
        ):
            os.environ.pop(var, None)

    def _run(self, file_path="/data/patients/MRN-4417723.csv"):
        session = mlflow_sink.start_session(file_path=file_path)
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": 0.9}, 0.1, file_path
        )
        mlflow_sink.end_session(session)
        exp = self.client.get_experiment_by_name("aidrin-dataset")
        runs = self.client.search_runs([exp.experiment_id])
        return [r for r in runs if not r.data.tags.get("aidrin.metric")][0]

    def test_metric_runs_record_the_dataset_too(self):
        """Otherwise the Dataset column is blank on every drill-down row."""
        self._run()
        exp = self.client.get_experiment_by_name("aidrin-dataset")
        children = [
            r for r in self.client.search_runs([exp.experiment_id])
            if r.data.tags.get("aidrin.run_type") == "metric"
        ]
        self.assertTrue(children)
        for child in children:
            full = self.client.get_run(child.info.run_id)
            with self.subTest(run=child.data.tags.get("aidrin.metric")):
                self.assertTrue(
                    full.inputs.dataset_inputs,
                    "metric run has no dataset; UI column is blank",
                )

    def test_parent_run_records_a_dataset_input(self):
        parent = self.client.get_run(self._run().info.run_id)
        self.assertTrue(
            parent.inputs.dataset_inputs, "no dataset recorded; UI column stays blank"
        )

    def test_dataset_is_named_by_its_file(self):
        """Dataset details are on by default so a run is identifiable."""
        parent = self.client.get_run(self._run().info.run_id)
        names = [d.dataset.name for d in parent.inputs.dataset_inputs]
        self.assertEqual(names, ["MRN-4417723.csv"])

    def test_dataset_name_can_be_hashed_by_opting_out(self):
        os.environ["AIDRIN_MLFLOW_LOG_DATA_DETAILS"] = "0"
        mlflow_sink.reset()
        parent = self.client.get_run(self._run().info.run_id)
        rendered = repr(parent.inputs.dataset_inputs)
        self.assertNotIn("MRN-4417723", rendered)

    def test_same_file_yields_the_same_dataset_identity(self):
        first = self.client.get_run(self._run("/tmp/stable.csv").info.run_id)
        mlflow_sink.reset()
        second_runs = []
        session = mlflow_sink.start_session(file_path="/tmp/stable.csv")
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": 0.8}, 0.1, "/tmp/stable.csv"
        )
        mlflow_sink.end_session(session)
        exp = self.client.get_experiment_by_name("aidrin-dataset")
        for r in self.client.search_runs([exp.experiment_id]):
            if not r.data.tags.get("aidrin.metric"):
                second_runs.append(self.client.get_run(r.info.run_id))
        names = {
            d.dataset.name for r in second_runs for d in r.inputs.dataset_inputs
        }
        self.assertIn(first.inputs.dataset_inputs[0].dataset.name, names)


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestRunTypeIsFilterable(unittest.TestCase):
    """Parent and child runs must both be selectable in the MLflow UI.

    MLflow cannot express "this tag is absent" in a search filter — a
    ``tags.x = ''`` query matches nothing — so distinguishing the two by the
    presence of ``aidrin.metric`` makes children selectable and parents not.
    Both carry an explicit ``aidrin.run_type`` instead.
    """

    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-runtype"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        for metric in ("completeness", "duplicity"):
            mlflow_sink.log_metric_result(
                session, metric, {"Overall Completeness": 0.9}, 0.1, "/tmp/d.csv"
            )
        mlflow_sink.end_session(session)
        self.eid = self.client.get_experiment_by_name("aidrin-runtype").experiment_id

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
            "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE",
        ):
            os.environ.pop(var, None)

    def test_assessments_are_selectable(self):
        runs = self.client.search_runs(
            [self.eid], filter_string="tags.`aidrin.run_type` = 'assessment'"
        )
        self.assertEqual(len(runs), 1)

    def test_metric_runs_are_selectable(self):
        runs = self.client.search_runs(
            [self.eid], filter_string="tags.`aidrin.run_type` = 'metric'"
        )
        self.assertEqual(len(runs), 2)

    def test_the_two_partition_the_experiment(self):
        total = len(self.client.search_runs([self.eid]))
        a = len(self.client.search_runs(
            [self.eid], filter_string="tags.`aidrin.run_type` = 'assessment'"))
        m = len(self.client.search_runs(
            [self.eid], filter_string="tags.`aidrin.run_type` = 'metric'"))
        self.assertEqual(a + m, total, "some run carries neither run_type")


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestDatasetLinksToTrainingRuns(unittest.TestCase):
    """An assessment and a training run over the same file must be one dataset.

    That link is the point of tracking readiness at all: "this data scored X,
    and then we trained on it".  MLflow identifies a dataset by name + digest,
    so AIDRIN has to produce the same digest a training run would.
    """

    def setUp(self):
        import tempfile

        import pandas as pd
        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-lineage"
        os.environ.pop("AIDRIN_MLFLOW_LOG_DATA_DETAILS", None)
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

        self.csv = os.path.join(self.tmp, "trainme.csv")
        pd.DataFrame({"a": [1, 2, 3], "b": [0.1, 0.2, 0.3]}).to_csv(self.csv, index=False)

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI", "AIDRIN_MLFLOW_EXPERIMENT",
            "MLFLOW_ALLOW_FILE_STORE", "AIDRIN_MLFLOW_LOG_DATA_DETAILS",
        ):
            os.environ.pop(var, None)

    def _aidrin_dataset(self):
        session = mlflow_sink.start_session(file_path=self.csv)
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": 1.0}, 0.1, self.csv
        )
        mlflow_sink.end_session(session)
        exp = self.client.get_experiment_by_name("aidrin-lineage")
        run = [
            r for r in self.client.search_runs([exp.experiment_id])
            if r.data.tags.get("aidrin.run_type") == "assessment"
        ][0]
        return self.client.get_run(run.info.run_id).inputs.dataset_inputs[0].dataset

    def _training_dataset(self):
        import mlflow
        import pandas as pd

        return mlflow.data.from_pandas(
            pd.read_csv(self.csv), source=self.csv, name=os.path.basename(self.csv)
        )

    def test_digest_matches_a_training_run(self):
        self.assertEqual(self._aidrin_dataset().digest, self._training_dataset().digest)

    def test_name_matches_a_training_run(self):
        self.assertEqual(self._aidrin_dataset().name, self._training_dataset().name)

    def test_falls_back_to_a_hashed_identity_when_details_are_off(self):
        """Opting out must not start writing real paths into the source."""
        os.environ["AIDRIN_MLFLOW_LOG_DATA_DETAILS"] = "0"
        mlflow_sink.reset()
        dataset = self._aidrin_dataset()
        self.assertNotIn("trainme", dataset.name)
        self.assertNotIn("trainme", dataset.source)

    def test_an_unreadable_file_does_not_break_the_run(self):
        session = mlflow_sink.start_session(file_path="/nonexistent/nope.csv")
        self.assertIsNotNone(session, "a bad path must not abort the assessment")
        mlflow_sink.end_session(session)


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestWritesAreBatched(unittest.TestCase):
    """One batched write per run, not one HTTP round trip per value.

    Measured against a local server: 400 metrics took 1.77s written one at a
    time and 0.07s batched.  The cost is per round trip, so it is worse against
    a remote tracking server than any local measurement suggests.
    """

    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-batched"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
            "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE",
        ):
            os.environ.pop(var, None)

    def _counted(self, fn):
        """Run *fn* counting log_batch vs single-value client calls."""
        calls = {"batch": 0, "single": 0}
        client = mlflow_sink._client
        real_batch, real_metric, real_param = (
            client.log_batch, client.log_metric, client.log_param
        )

        def batch(*a, **k):
            calls["batch"] += 1
            return real_batch(*a, **k)

        def metric(*a, **k):
            calls["single"] += 1
            return real_metric(*a, **k)

        def param(*a, **k):
            calls["single"] += 1
            return real_param(*a, **k)

        client.log_batch, client.log_metric, client.log_param = batch, metric, param
        try:
            fn()
        finally:
            client.log_batch, client.log_metric, client.log_param = (
                real_batch, real_metric, real_param
            )
        return calls

    def test_a_metric_run_writes_in_one_batch(self):
        mlflow_sink.is_enabled()  # build the client before wrapping it
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")

        calls = self._counted(lambda: mlflow_sink.log_metric_result(
            session, "constant_feature_count",
            {"Constant feature count": 2, "Total features": 11}, 0.1, "/tmp/d.csv",
            params={"threshold": 0.9, "distance_metric": "CH"},
        ))
        self.assertEqual(calls["single"], 0, "values were written one at a time")
        self.assertEqual(calls["batch"], 1, "expected a single batched write")

    def test_the_rollup_writes_in_one_batch(self):
        mlflow_sink.is_enabled()
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        for i in range(5):
            mlflow_sink.log_metric_result(
                session, "completeness", {"Overall Completeness": i / 5}, 0.1, "/tmp/d.csv"
            )
        calls = self._counted(lambda: mlflow_sink.end_session(session))
        self.assertEqual(calls["single"], 0)
        self.assertLessEqual(calls["batch"], 1)

    def test_batching_does_not_change_what_is_recorded(self):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.log_metric_result(
            session, "constant_feature_count",
            {"Constant feature count": 2, "Total features": 11}, 0.25, "/tmp/d.csv",
            params={"threshold": 0.9},
        )
        mlflow_sink.end_session(session)

        exp = self.client.get_experiment_by_name("aidrin-batched")
        runs = self.client.search_runs([exp.experiment_id])
        child = [r for r in runs if r.data.tags.get("aidrin.run_type") == "metric"][0]
        parent = [r for r in runs if r.data.tags.get("aidrin.run_type") == "assessment"][0]

        self.assertEqual(child.data.metrics["aidrin.structure.constant_feature_count"], 2.0)
        self.assertEqual(child.data.metrics["aidrin.structure.total_features"], 11.0)
        self.assertAlmostEqual(child.data.metrics["aidrin.structure.runtime_seconds"], 0.25)
        self.assertEqual(child.data.params["threshold"], "0.9")
        self.assertEqual(child.data.params["aidrin_version"], parent.data.params["aidrin_version"])
        self.assertEqual(parent.data.metrics["aidrin.structure.total_features"], 11.0)


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestSinkLeaksNothing(unittest.TestCase):
    """The sink runs inside long-lived processes: the MCP server and Celery.

    Anything it retains per assessment accumulates for the life of the process.
    """

    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-leaks"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
            "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE",
        ):
            os.environ.pop(var, None)

    def test_archiving_leaves_no_temporary_directories(self):
        import glob
        import tempfile

        pattern = os.path.join(tempfile.gettempdir(), "tmp*")
        before = set(glob.glob(pattern))

        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        for _ in range(3):
            mlflow_sink.log_metric_result(
                session, "completeness", {"Overall Completeness": 1.0}, 0.1, "/tmp/d.csv"
            )
        mlflow_sink.end_session(session)

        leaked = [
            d for d in set(glob.glob(pattern)) - before
            if os.path.isdir(d) and os.path.exists(os.path.join(d, "result.json"))
        ]
        self.assertEqual(leaked, [], f"archiving leaked temp dirs: {leaked}")

    def test_abandoned_sessions_do_not_accumulate_without_bound(self):
        """An agent that never calls end_assessment must not grow the process."""
        for _ in range(mlflow_sink.MAX_TRACKED_SESSIONS + 20):
            mlflow_sink.start_session(file_path="/tmp/d.csv")
        self.assertLessEqual(
            len(mlflow_sink._sessions), mlflow_sink.MAX_TRACKED_SESSIONS
        )

    def test_the_newest_sessions_are_the_ones_kept(self):
        first = mlflow_sink.start_session(file_path="/tmp/first.csv")
        for _ in range(mlflow_sink.MAX_TRACKED_SESSIONS + 5):
            mlflow_sink.start_session(file_path="/tmp/d.csv")
        newest = mlflow_sink.start_session(file_path="/tmp/newest.csv")

        self.assertIsNone(mlflow_sink.get_session(first.session_id), "oldest not evicted")
        self.assertIsNotNone(mlflow_sink.get_session(newest.session_id))

    def test_a_completed_session_is_released(self):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.end_session(session)
        self.assertIsNone(mlflow_sink.get_session(session.session_id))


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestAMetricRunIsAlwaysClosed(unittest.TestCase):
    """Nothing between create_run and set_terminated may orphan a run.

    A run left RUNNING shows as in-progress in the UI forever.  The trigger
    found in review was numpy values in params, but the guarantee has to be
    structural: any failure in the body must still close the run.
    """

    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-closed"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
            "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE",
        ):
            os.environ.pop(var, None)

    def _runs(self):
        exp = self.client.get_experiment_by_name("aidrin-closed")
        return self.client.search_runs([exp.experiment_id])

    def test_numpy_arguments_do_not_break_logging(self):
        import numpy as np

        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": 0.9}, 0.1, "/tmp/d.csv",
            params={"columns": np.array(["a", "b"]), "threshold": np.float64(0.9)},
        )
        mlflow_sink.end_session(session)

        child = [r for r in self._runs() if r.data.tags.get("aidrin.run_type") == "metric"][0]
        self.assertIn("aidrin.quality.completeness", child.data.metrics)
        self.assertEqual(child.data.params.get("columns_count"), "2")

    def test_a_failing_body_still_closes_the_run(self):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")

        original = mlflow_sink._build_params
        mlflow_sink._build_params = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            mlflow_sink.log_metric_result(
                session, "completeness", {"Overall Completeness": 0.9}, 0.1, "/tmp/d.csv"
            )
        finally:
            mlflow_sink._build_params = original
        mlflow_sink.end_session(session)

        for run in self._runs():
            self.assertEqual(
                run.info.status, "FINISHED",
                f"{run.data.tags.get('aidrin.run_type')} run left {run.info.status}",
            )


class TestNothingIsPrintedToStdout(unittest.TestCase):
    """The MCP server speaks JSON-RPC over stdout.

    MLflow prints "View run <name> at: <url>" to stdout when it creates a run
    against an HTTP tracking server, which corrupts the protocol stream and
    kills the MCP connection.  A file-store backend does not print, so unit
    tests alone never see this — it was found by driving the real server.
    """

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
            "MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT",
        ):
            os.environ.pop(var, None)

    @unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
    def test_enabling_the_sink_suppresses_mlflow_url_printing(self):
        import tempfile

        os.environ.pop("MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT", None)
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{tempfile.mkdtemp()}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        mlflow_sink.reset()

        self.assertTrue(mlflow_sink.is_enabled())
        self.assertEqual(
            os.environ.get("MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT"), "true",
            "MLflow would print run URLs to stdout and break the MCP protocol",
        )

    @unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
    def test_an_operator_setting_is_respected(self):
        import tempfile

        os.environ["MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT"] = "false"
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{tempfile.mkdtemp()}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        mlflow_sink.reset()
        mlflow_sink.is_enabled()
        self.assertEqual(os.environ["MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT"], "false")


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestFailedMetricsAreVisible(unittest.TestCase):
    """A metric that errored must be distinguishable from one with no score.

    Metrics fail to an ``{"Error": ...}`` dict rather than raising, so without a
    marker a failed run and a run for a metric that simply declares no headline
    projection look identical: runtime only.
    """

    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-failures"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
            "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE",
        ):
            os.environ.pop(var, None)

    def _run_for(self, metric, result):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.log_metric_result(session, metric, result, 0.1, "/tmp/d.csv")
        mlflow_sink.end_session(session)
        exp = self.client.get_experiment_by_name("aidrin-failures")
        return [
            r for r in self.client.search_runs([exp.experiment_id])
            if r.data.tags.get("aidrin.metric") == metric
        ][0]

    def test_a_failed_metric_is_marked(self):
        run = self._run_for(
            "single_attribute_risk",
            {"Error": "ID column 'sensor_id' must contain unique values for each row."},
        )
        self.assertEqual(run.data.tags.get("aidrin.status"), "error")

    def test_a_succeeding_metric_is_marked_ok(self):
        run = self._run_for("skewness", {"Skewness": {"age": 0.3}})
        self.assertEqual(run.data.tags.get("aidrin.status"), "ok")

    def test_the_error_message_is_not_recorded(self):
        """Metric errors quote column names and cell values."""
        run = self._run_for(
            "completeness", {"Error": "bad value 'SSN-123-45-6789' in column 'ssn'"}
        )
        rendered = repr((run.data.tags, run.data.params))
        self.assertNotIn("SSN-123-45-6789", rendered)
        self.assertNotIn("ssn", rendered)

    def test_failures_are_countable_from_the_assessment(self):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.log_metric_result(session, "a_ok", {"x": 1}, 0.1, "/tmp/d.csv")
        mlflow_sink.log_metric_result(session, "b_bad", {"Error": "no"}, 0.1, "/tmp/d.csv")
        mlflow_sink.log_metric_result(session, "c_bad", {"Error": "no"}, 0.1, "/tmp/d.csv")
        mlflow_sink.end_session(session)

        exp = self.client.get_experiment_by_name("aidrin-failures")
        parent = [
            r for r in self.client.search_runs([exp.experiment_id])
            if r.data.tags.get("aidrin.run_type") == "assessment"
        ][0]
        self.assertEqual(parent.data.metrics.get("aidrin.failed_metrics"), 2.0)


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestAssessmentStatus(unittest.TestCase):
    """An assessment says whether its metrics succeeded.

    Without it, ``tags.aidrin.status`` only ever matches metric runs, so an
    assessment that half failed looks identical to one that did not.
    """

    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-status"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        mlflow_sink.reset()
        for var in ("AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
                    "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE"):
            os.environ.pop(var, None)

    def _assess(self, results):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        for i, result in enumerate(results):
            mlflow_sink.log_metric_result(
                session, f"completeness_{i}", result, 0.1, "/tmp/d.csv"
            )
        mlflow_sink.end_session(session)
        exp = self.client.get_experiment_by_name("aidrin-status")
        return [
            r for r in self.client.search_runs([exp.experiment_id])
            if r.data.tags.get("aidrin.run_type") == "assessment"
        ][0]

    def test_all_succeeded_is_ok(self):
        run = self._assess([{"Overall Completeness": 1.0}, {"Overall Completeness": 0.9}])
        self.assertEqual(run.data.tags.get("aidrin.status"), "ok")
        self.assertEqual(run.data.metrics.get("aidrin.metrics_run"), 2.0)

    def test_some_failed_is_partial(self):
        run = self._assess([{"Overall Completeness": 1.0}, {"Error": "boom"}])
        self.assertEqual(run.data.tags.get("aidrin.status"), "partial")
        self.assertEqual(run.data.metrics.get("aidrin.failed_metrics"), 1.0)

    def test_all_failed_is_error(self):
        run = self._assess([{"Error": "boom"}, {"Error": "boom"}])
        self.assertEqual(run.data.tags.get("aidrin.status"), "error")

    def test_an_empty_assessment_is_ok(self):
        run = self._assess([])
        self.assertEqual(run.data.tags.get("aidrin.status"), "ok")
