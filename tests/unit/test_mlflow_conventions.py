"""MLflow conventions AIDRIN has to honour itself.

``MlflowClient.create_run`` sets none of the system tags the fluent API sets for
you, so a client-only integration silently produces runs with blank Source and
User columns.  And a readiness score without the arguments that produced it is
not comparable: k-anonymity over two quasi-identifiers and over five are
different measurements that both land in ``readiness.governance.k_anonymity``.
"""

import os
import sys
import tempfile
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


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestConventions(unittest.TestCase):
    def setUp(self):
        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-conventions"
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

    def _assess(self, params=None):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.log_metric_result(
            session, "k_anonymity", {"k-Value": 3}, 0.1, "/tmp/d.csv", params=params
        )
        mlflow_sink.end_session(session)
        exp = self.client.get_experiment_by_name("aidrin-conventions")
        runs = self.client.search_runs([exp.experiment_id])
        return (
            [r for r in runs if r.data.tags.get("aidrin.run_type") == "assessment"][0],
            [r for r in runs if r.data.tags.get("aidrin.run_type") == "metric"][0],
        )

    # -- system tags --------------------------------------------------------

    def test_runs_identify_their_source(self):
        """Otherwise the UI's Source column is blank on every AIDRIN run."""
        parent, child = self._assess()
        for run in (parent, child):
            with self.subTest(run=run.data.tags.get("aidrin.run_type")):
                self.assertIn("mlflow.source.name", run.data.tags)
                self.assertEqual(run.data.tags["mlflow.source.type"], "LOCAL")

    def test_runs_identify_their_user(self):
        parent, child = self._assess()
        for run in (parent, child):
            with self.subTest(run=run.data.tags.get("aidrin.run_type")):
                self.assertTrue(run.data.tags.get("mlflow.user"))

    # -- provenance ---------------------------------------------------------

    def test_aidrin_version_is_recorded(self):
        """A score is only reproducible if you know which AIDRIN produced it."""
        parent, child = self._assess()
        for run in (parent, child):
            with self.subTest(run=run.data.tags.get("aidrin.run_type")):
                self.assertTrue(run.data.params.get("aidrin_version"))

    # -- arguments ----------------------------------------------------------

    def test_metric_arguments_are_recorded(self):
        _, child = self._assess(
            params={"quasi_identifiers": ["age", "zip_code", "gender"]}
        )
        self.assertEqual(child.data.params.get("quasi_identifiers_count"), "3")

    def test_column_names_are_recorded_by_default(self):
        _, child = self._assess(params={"quasi_identifiers": ["age", "zip_code"]})
        self.assertIn("zip_code", child.data.params.get("quasi_identifiers", ""))

    def test_column_names_can_be_withheld_by_opting_out(self):
        os.environ["AIDRIN_MLFLOW_LOG_DATA_DETAILS"] = "0"
        mlflow_sink.reset()
        _, child = self._assess(params={"quasi_identifiers": ["age", "zip_code"]})
        self.assertNotIn("zip_code", repr(child.data.params))
        self.assertEqual(child.data.params.get("quasi_identifiers_count"), "2")

    def test_non_column_arguments_are_always_recorded(self):
        """A threshold is configuration, not data — it is safe and it matters."""
        _, child = self._assess(params={"threshold": 0.9, "distance_metric": "CH"})
        self.assertEqual(child.data.params.get("threshold"), "0.9")
        self.assertEqual(child.data.params.get("distance_metric"), "CH")

    def test_empty_arguments_are_not_logged(self):
        _, child = self._assess(params={"threshold": None, "columns": []})
        self.assertNotIn("threshold", child.data.params)

    def test_long_argument_values_cannot_exceed_the_param_limit(self):
        """MLflow raises above 6000 characters rather than truncating."""
        _, child = self._assess(params={"columns": [f"column_{i:04d}" for i in range(2000)]})
        for value in child.data.params.values():
            self.assertLessEqual(len(value), 6000)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestGitProvenance(unittest.TestCase):
    """MLflow records the commit a run came from; AIDRIN is installed from a repo.

    Without it, two assessments that disagree cannot be traced to the versions
    that produced them beyond the release number.
    """

    def setUp(self):
        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-git"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        mlflow_sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
            "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE",
        ):
            os.environ.pop(var, None)

    def test_runs_record_the_git_commit(self):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.log_metric_result(
            session, "completeness", {"Overall Completeness": 1.0}, 0.1, "/tmp/d.csv"
        )
        mlflow_sink.end_session(session)

        exp = self.client.get_experiment_by_name("aidrin-git")
        for run in self.client.search_runs([exp.experiment_id]):
            with self.subTest(run=run.data.tags.get("aidrin.run_type")):
                commit = run.data.tags.get("mlflow.source.git.commit")
                self.assertTrue(commit, "no git commit recorded")
                self.assertEqual(len(commit), 40, f"not a full sha: {commit}")

    def test_a_non_repo_install_is_not_an_error(self):
        """pip-installed AIDRIN has no repo; the tag is simply absent."""
        from aidrin.telemetry import mlflow_sink as sink

        original = sink._git_commit
        sink._git_commit = lambda: None
        try:
            session = sink.start_session(file_path="/tmp/d.csv")
            self.assertIsNotNone(session)
            sink.end_session(session)
        finally:
            sink._git_commit = original


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestExperimentDescription(unittest.TestCase):
    """An experiment AIDRIN creates should say what it is.

    On a shared deployment these runs sit beside other teams' work, so a bare
    name leaves people guessing what produced them.
    """

    def setUp(self):
        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-described"
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        mlflow_sink.reset()
        for var in ("AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
                    "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE",
                    "MLFLOW_TRACKING_USERNAME"):
            os.environ.pop(var, None)

    def test_a_created_experiment_carries_a_description(self):
        self.assertTrue(mlflow_sink.is_enabled())
        exp = self.client.get_experiment_by_name("aidrin-described")
        note = exp.tags.get("mlflow.note.content", "")
        self.assertIn("AIDRIN", note)
        self.assertIn("AI Data Readiness Infrastructure", note)

    def test_an_existing_experiment_description_is_not_overwritten(self):
        """Someone else's experiment must not be relabelled by us."""
        exp_id = self.client.create_experiment(
            "aidrin-described", tags={"mlflow.note.content": "hands off"}
        )
        mlflow_sink.reset()
        self.assertTrue(mlflow_sink.is_enabled())
        self.assertEqual(
            self.client.get_experiment(exp_id).tags["mlflow.note.content"], "hands off"
        )


@unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
class TestRunAttribution(unittest.TestCase):
    """On a shared tracking server the local OS account is the wrong identity.

    getpass.getuser() reports "jlbez" while the account on the server is
    jean-luca.bez@example.org — misleading attribution beside other teams' runs.
    """

    def setUp(self):
        from mlflow.tracking import MlflowClient

        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-attribution"
        os.environ.pop("MLFLOW_TRACKING_USERNAME", None)
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        mlflow_sink.reset()
        for var in ("AIDRIN_MLFLOW_ENABLED", "MLFLOW_TRACKING_URI",
                    "AIDRIN_MLFLOW_EXPERIMENT", "MLFLOW_ALLOW_FILE_STORE",
                    "MLFLOW_TRACKING_USERNAME"):
            os.environ.pop(var, None)

    def _user(self):
        session = mlflow_sink.start_session(file_path="/tmp/d.csv")
        mlflow_sink.end_session(session)
        exp = self.client.get_experiment_by_name("aidrin-attribution")
        run = self.client.search_runs([exp.experiment_id])[0]
        return run.data.tags.get("mlflow.user")

    def test_the_tracking_username_is_used_when_set(self):
        os.environ["MLFLOW_TRACKING_USERNAME"] = "google:someone@example.org"
        mlflow_sink.reset()
        self.assertEqual(self._user(), "google:someone@example.org")

    def test_it_falls_back_to_the_local_account(self):
        import getpass

        self.assertEqual(self._user(), getpass.getuser())


class TestGatewayAuthHeader(unittest.TestCase):
    """MLflow behind an API gateway that wants a custom header.

    MLflow's own MLFLOW_TRACKING_TOKEN only ever sends
    ``Authorization: Bearer``. Gateways such as Kong commonly want the key in a
    header of their own (``x-api-key``), which that cannot express.
    """

    def tearDown(self):
        for var in ("AIDRIN_MLFLOW_AUTH_HEADER", "AIDRIN_MLFLOW_AUTH_KEY"):
            os.environ.pop(var, None)

    def test_no_headers_when_unconfigured(self):
        from aidrin.telemetry.auth import ApiKeyHeaderProvider

        provider = ApiKeyHeaderProvider()
        self.assertFalse(provider.in_context())

    def test_header_and_key_are_sent_together(self):
        from aidrin.telemetry.auth import ApiKeyHeaderProvider

        os.environ["AIDRIN_MLFLOW_AUTH_HEADER"] = "x-api-key"
        os.environ["AIDRIN_MLFLOW_AUTH_KEY"] = "secret-value"
        provider = ApiKeyHeaderProvider()
        self.assertTrue(provider.in_context())
        self.assertEqual(provider.request_headers(), {"x-api-key": "secret-value"})

    def test_a_key_without_a_header_name_is_inert(self):
        from aidrin.telemetry.auth import ApiKeyHeaderProvider

        os.environ["AIDRIN_MLFLOW_AUTH_KEY"] = "secret-value"
        self.assertFalse(ApiKeyHeaderProvider().in_context())

    @unittest.skipUnless(HAS_MLFLOW, "requires the [mlflow] extra")
    def test_enabling_the_sink_registers_the_provider(self):
        import tempfile

        from aidrin.telemetry import mlflow_sink

        os.environ["AIDRIN_MLFLOW_AUTH_HEADER"] = "x-api-key"
        os.environ["AIDRIN_MLFLOW_AUTH_KEY"] = "secret-value"
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{tempfile.mkdtemp()}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        mlflow_sink.reset()
        try:
            self.assertTrue(mlflow_sink.is_enabled())
            from mlflow.tracking.request_header.registry import (
                _request_header_provider_registry,
            )

            headers = {}
            for p in _request_header_provider_registry._registry:
                if p.in_context():
                    headers.update(p.request_headers())
            self.assertEqual(headers.get("x-api-key"), "secret-value")
        finally:
            mlflow_sink.reset()
            for var in ("MLFLOW_ALLOW_FILE_STORE", "MLFLOW_TRACKING_URI",
                        "AIDRIN_MLFLOW_ENABLED"):
                os.environ.pop(var, None)
