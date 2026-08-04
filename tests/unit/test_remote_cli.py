"""Unit tests for the `aidrin remote` CLI surface."""

import argparse
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _run_cli(*argv: str) -> tuple[str, str, int]:
    """Invoke main() with the given argv, returning (stdout, stderr, exit_code)."""
    from aidrin.headless.cli import main

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    exit_code = 0
    with patch("sys.argv", ["aidrin", *argv]), \
         patch("sys.stdout", out_buf), \
         patch("sys.stderr", err_buf):
        try:
            main()
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
    return out_buf.getvalue(), err_buf.getvalue(), exit_code


class _RemoteCliTestCase(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.project = tempfile.mkdtemp()
        self._env = patch.dict(os.environ, {"AIDRIN_CONFIG_DIR": self.home}, clear=False)
        self._env.start()
        os.environ.pop("AIDRIN_GLOBUS_ENDPOINT", None)
        self._cwd = patch.object(Path, "cwd", staticmethod(lambda: Path(self.project)))
        self._cwd.start()
        # globus-compute-sdk is not a test dependency, and the CLI now refuses a
        # remote run without it. Every test here is about what happens once the
        # SDK is present; TestGuards covers the absent case explicitly.
        self._sdk = patch("aidrin.compute.client.is_available", return_value=True)
        self._sdk.start()

    def tearDown(self):
        self._sdk.stop()
        self._cwd.stop()
        self._env.stop()


class TestManagementCommands(_RemoteCliTestCase):

    def test_configure_probes_before_saving(self):
        probe_result = {"aidrin_version": "0.9.2", "python_version": "3.12.4", "headless_import": True}
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.probe", return_value=probe_result) as probe:
            out, err, code = _run_cli("remote", "configure", "--name", "nersc", "--endpoint", "uuid-1")
        self.assertEqual(code, 0)
        probe.assert_called_once()
        from aidrin.compute import profiles
        self.assertEqual(profiles.list_profiles()["profiles"]["nersc"]["endpoint"], "uuid-1")
        self.assertEqual(profiles.list_profiles()["profiles"]["nersc"]["aidrin_version"], "0.9.2")

    def test_configure_does_not_save_when_probe_fails(self):
        from aidrin.compute.client import RemoteError

        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.probe", side_effect=RemoteError("endpoint offline")):
            _out, err, code = _run_cli("remote", "configure", "--name", "nersc", "--endpoint", "uuid-1")
        self.assertEqual(code, 1)
        self.assertIn("endpoint offline", err)
        from aidrin.compute import profiles
        self.assertEqual(profiles.list_profiles()["profiles"], {})

    def test_list_prints_profiles_as_json(self):
        from aidrin.compute import profiles

        profiles.save_profile("nersc", "uuid-1", default=True)
        out, _err, code = _run_cli("remote", "list")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["default"], "nersc")

    def test_help_lists_the_management_surface(self):
        out, _err, code = _run_cli("remote", "--help")
        self.assertEqual(code, 0)
        for expected in ("configure", "list", "remove", "check", "login", "logout",
                         "status", "task", "--profile", "--endpoint", "--async", "--timeout"):
            self.assertIn(expected, out)

    def test_remove_reports_unknown_profile(self):
        _out, err, code = _run_cli("remote", "remove", "ghost")
        self.assertEqual(code, 1)
        self.assertIn("ghost", err)

    def test_check_honours_timeout_and_defaults_to_the_probe_timeout(self):
        from aidrin.compute import client as compute_client
        from aidrin.compute import profiles

        profiles.save_profile("nersc", "uuid-1", default=True)
        probe_result = {"aidrin_version": "0.9.2", "python_version": "3.12.4"}
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.probe", return_value=probe_result) as probe:
            _run_cli("remote", "check")
            self.assertEqual(probe.call_args.kwargs["timeout"], compute_client.PROBE_TIMEOUT)
            _run_cli("remote", "--timeout", "30", "check")
            self.assertEqual(probe.call_args.kwargs["timeout"], 30.0)

    def test_task_wait_fails_when_the_recovered_result_is_a_worker_error(self):
        error = {"Error": "File not found: /nope.csv", "ErrorType": "ValueError"}
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.poll", return_value=error):
            out, err, code = _run_cli("remote", "task", "task-5", "--wait")
        self.assertEqual(code, 1)
        self.assertIn("File not found: /nope.csv", err)
        self.assertEqual(out, "")

    def test_task_wait_prints_a_metric_error_result_and_exits_0(self):
        result = {"Error": "No numerical features found in the dataset."}
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.poll", return_value=result):
            out, _err, code = _run_cli("remote", "task", "task-5", "--wait")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), result)

    def test_task_cancel_reports_success_when_the_sdk_supports_it(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.cancel", return_value=True):
            _out, err, code = _run_cli("remote", "task", "task-5", "--cancel")
        self.assertEqual(code, 0)
        self.assertIn("Cancelled task-5", err)

    def test_task_cancel_does_not_claim_success_when_unsupported(self):
        # This is the real globus-compute-sdk 4.x case: cancel() cannot
        # actually cancel anything (see aidrin.compute.client.cancel).
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.cancel", return_value=False):
            _out, err, code = _run_cli("remote", "task", "task-5", "--cancel")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Cancelled task-5", err)
        self.assertIn("not supported", err.lower())
        self.assertIn("task-5", err)
        self.assertIn("running", err.lower())
        self.assertIn("--wait", err)

    def test_logout_without_sdk_support_explains_the_alternative(self):
        class _NoLogout:
            pass

        with patch("aidrin.compute.client.get_client", return_value=_NoLogout()):
            _out, err, code = _run_cli("remote", "logout")
        self.assertEqual(code, 1)
        self.assertIn("globus-compute-endpoint", err)
        self.assertIn("~/.globus_compute/", err)


class TestExecution(_RemoteCliTestCase):

    def setUp(self):
        super().setUp()
        from aidrin.compute import profiles

        profiles.save_profile("nersc", "uuid-1", default=True)

    def test_summarize_routes_to_remote_executor(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={"shape": {"rows": 10, "columns": 2}}):
            out, _err, code = _run_cli("remote", "summarize", "/scratch/data.csv")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["shape"]["rows"], 10)
        _conn, endpoint, command, _kwargs = submit.call_args[0]
        self.assertEqual(endpoint, "uuid-1")
        self.assertEqual(command, "summarize")

    def test_run_metric_routes_to_remote_executor(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={"Completeness scores": {}}):
            _out, _err, code = _run_cli("remote", "run", "completeness", "/scratch/data.csv")
        self.assertEqual(code, 0)
        self.assertEqual(submit.call_args[0][2], "run_metric")

    def test_endpoint_flag_overrides_profile(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={}):
            _run_cli("remote", "--endpoint", "uuid-override", "summarize", "/x.csv")
        self.assertEqual(submit.call_args[0][1], "uuid-override")

    def test_async_prints_task_id_only(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-77"), \
             patch("aidrin.compute.client.poll") as poll:
            out, _err, code = _run_cli("remote", "--async", "summarize", "/x.csv")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["task_id"], "task-77")
        poll.assert_not_called()

    def test_progress_goes_to_stderr_not_stdout(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1"), \
             patch("aidrin.compute.client.poll", return_value={"shape": {"rows": 3, "columns": 1}}):
            out, err, _code = _run_cli("remote", "summarize", "/x.csv")
        self.assertIn("task-1", err)
        self.assertEqual(json.loads(out), {"shape": {"rows": 3, "columns": 1}})

    def test_interrupt_cancels_the_remote_task_and_exits_130(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-9"), \
             patch("aidrin.compute.client.poll", side_effect=KeyboardInterrupt), \
             patch("aidrin.compute.client.cancel", return_value=True) as cancel:
            _out, err, code = _run_cli("remote", "summarize", "/x.csv")
        self.assertEqual(code, 130)
        self.assertEqual(cancel.call_args[0][1], "task-9")
        self.assertIn("task-9", err)
        self.assertIn("cancelled remote task task-9", err)

    def test_interrupt_reports_still_running_when_cancel_is_not_supported(self):
        # This is the real globus-compute-sdk 4.x case: cancel() cannot
        # actually cancel anything, so the interrupt message must not claim
        # it did.
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-9"), \
             patch("aidrin.compute.client.poll", side_effect=KeyboardInterrupt), \
             patch("aidrin.compute.client.cancel", return_value=False):
            _out, err, code = _run_cli("remote", "summarize", "/x.csv")
        self.assertEqual(code, 130)
        self.assertNotIn("cancelled remote task", err)
        self.assertIn("task-9", err)
        self.assertIn("running", err.lower())
        self.assertIn("--wait", err)

    def test_interrupt_before_submission_claims_no_cancellation(self):
        with patch("aidrin.compute.client.get_client", side_effect=KeyboardInterrupt), \
             patch("aidrin.compute.client.cancel") as cancel:
            _out, err, code = _run_cli("remote", "summarize", "/x.csv")
        self.assertEqual(code, 130)
        cancel.assert_not_called()
        self.assertNotIn("cancelled", err.lower())

    def test_version_skew_warns_on_stderr(self):
        from aidrin.compute import profiles

        profiles.save_profile("old", "uuid-old", default=True, aidrin_version="0.1.0")
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1"), \
             patch("aidrin.compute.client.poll", return_value={}):
            _out, err, _code = _run_cli("remote", "summarize", "/x.csv")
        self.assertIn("version", err.lower())


class TestGuards(_RemoteCliTestCase):

    def setUp(self):
        super().setUp()
        from aidrin.compute import profiles

        profiles.save_profile("nersc", "uuid-1", default=True)

    def test_no_endpoint_configured_exits_2(self):
        from aidrin.compute import profiles

        profiles.remove_profile("nersc")
        _out, err, code = _run_cli("remote", "summarize", "/x.csv")
        self.assertEqual(code, 2)
        self.assertIn("aidrin remote configure", err)

    def test_custom_metric_is_rejected(self):
        _out, err, code = _run_cli("remote", "run", "custom", "/my_audit.py", "/x.csv")
        self.assertEqual(code, 2)
        self.assertIn("local", err.lower())

    def test_agentic_is_rejected(self):
        _out, err, code = _run_cli("remote", "agentic", "run", "-c", "cfg.yaml")
        self.assertEqual(code, 2)
        self.assertIn("local", err.lower())

    def test_bare_remote_exits_2(self):
        _out, err, code = _run_cli("remote")
        self.assertEqual(code, 2)
        self.assertIn("subcommand", err)

    def test_missing_sdk_exits_2_before_announcing_the_run(self):
        with patch("aidrin.compute.client.is_available", return_value=False):
            _out, err, code = _run_cli("remote", "summarize", "/x.csv")
        self.assertEqual(code, 2)
        self.assertIn("pip install 'aidrin[globus]'", err)
        self.assertNotIn("Running on Globus Compute endpoint", err)


class TestRemoteFailuresExitNonZero(_RemoteCliTestCase):
    """A worker exception comes back as data, so the CLI must fail on it itself.

    ``ErrorType`` is the marker: the runner's ``except`` wrapper is the only
    thing that sets it. A metric that returns a plain ``{"Error": ...}`` for
    input it cannot score is an ordinary result, not a failure.
    """

    ERROR_RESULT = {"Error": "File not found: /nope.csv", "ErrorType": "ValueError"}
    # What a metric returns for a file it cannot score; no exception was raised.
    METRIC_ERROR_RESULT = {"Error": "No numerical features found in the dataset."}

    def setUp(self):
        super().setUp()
        from aidrin.compute import profiles

        profiles.save_profile("nersc", "uuid-1", default=True)

    def _run_with_result(self, result, *argv):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1"), \
             patch("aidrin.compute.client.poll", return_value=result):
            return _run_cli(*argv)

    def test_metric_error_result_exits_1_with_stderr_message(self):
        out, err, code = self._run_with_result(
            self.ERROR_RESULT, "remote", "run", "completeness", "/nope.csv"
        )
        self.assertEqual(code, 1)
        self.assertIn("File not found: /nope.csv", err)
        self.assertNotIn("File not found", out)

    def test_data_quality_error_result_exits_1_instead_of_summarizing(self):
        out, err, code = self._run_with_result(
            self.ERROR_RESULT, "remote", "data-quality", "/nope.csv"
        )
        self.assertEqual(code, 1)
        self.assertIn("File not found: /nope.csv", err)
        self.assertNotIn("Data Quality Summary", out)

    def test_summarize_error_result_exits_1(self):
        _out, err, code = self._run_with_result(
            self.ERROR_RESULT, "remote", "summarize", "/nope.csv"
        )
        self.assertEqual(code, 1)
        self.assertIn("File not found: /nope.csv", err)

    def test_batch_error_result_exits_1(self):
        config = Path(self.project) / "batch.json"
        config.write_text('{"file-path": "/nope.csv", "metrics": ["completeness"]}')
        _out, err, code = self._run_with_result(
            self.ERROR_RESULT, "remote", "batch", str(config)
        )
        self.assertEqual(code, 1)
        self.assertIn("File not found: /nope.csv", err)

    def test_batch_per_metric_error_still_exits_0(self):
        """An error under one metric is that metric failing, as it is locally."""
        config = Path(self.project) / "batch.json"
        config.write_text('{"file-path": "/data.csv", "metrics": ["completeness"]}')
        result = {
            "completeness": {"Error": "boom", "ErrorType": "ValueError"},
            "duplicity": {"Duplicity scores": {"Overall duplicity of the dataset": 0.0}},
        }
        out, _err, code = self._run_with_result(result, "remote", "batch", str(config))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["completeness"]["Error"], "boom")

    def test_metric_error_result_without_error_type_matches_the_local_run(self):
        """`{"Error": ...}` with no ErrorType is a result, and prints like one."""
        out, _err, code = self._run_with_result(
            self.METRIC_ERROR_RESULT, "remote", "run", "outliers", "/x.csv"
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), self.METRIC_ERROR_RESULT)

        with patch("aidrin.headless.api.run_metric", return_value=self.METRIC_ERROR_RESULT):
            local_out, _local_err, local_code = _run_cli("run", "outliers", "/x.csv")
        self.assertEqual((out, code), (local_out, local_code))

    def test_data_quality_error_result_without_error_type_matches_the_local_run(self):
        out, _err, code = self._run_with_result(
            self.METRIC_ERROR_RESULT, "remote", "data-quality", "/x.csv"
        )
        self.assertEqual(code, 0)

        with patch("aidrin.headless.api.run_data_quality", return_value=self.METRIC_ERROR_RESULT):
            local_out, _local_err, local_code = _run_cli("data-quality", "/x.csv")
        self.assertEqual((out, code), (local_out, local_code))

    def test_successful_remote_run_still_exits_0(self):
        out, _err, code = self._run_with_result(
            {"Overall Completeness": 1.0, "Completeness scores": {"a": 1.0}},
            "remote", "run", "completeness", "/data.csv",
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["Overall Completeness"], 1.0)


class TestPreParserFlagCollisions(unittest.TestCase):
    """`_split_remote_argv` eats these four flags before the local parser runs.

    A subcommand that declared one of them would never see it under `remote`,
    with no error at all -- the bug `remote configure --endpoint` already hit.
    `remote configure` is the one deliberate case; it reads the value back from
    the pre-parser and its parser lives outside this tree.
    """

    RESERVED = {"--profile", "--endpoint", "--timeout", "--async"}

    @staticmethod
    def _build_parser():
        """Grab the parser main() builds, without main() having to expose it."""
        from aidrin.headless.cli import main

        captured = {}

        def _spy(self, args=None, namespace=None):
            captured["parser"] = self
            raise SystemExit(0)

        with patch.object(argparse.ArgumentParser, "parse_args", _spy), \
             patch("sys.argv", ["aidrin", "list"]):
            try:
                main()
            except SystemExit:
                pass
        return captured["parser"]

    def _walk(self, parser, prefix="aidrin"):
        yield prefix, parser
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    yield from self._walk(sub, f"{prefix} {name}")

    def test_no_subcommand_declares_a_remote_only_flag(self):
        commands = dict(self._walk(self._build_parser()))
        # Guard against a vacuous pass if the capture ever stops working.
        self.assertIn("aidrin summarize", commands)
        self.assertIn("aidrin run completeness", commands)

        offenders = [
            f"{name} {option}"
            for name, sub in commands.items()
            for action in sub._actions
            for option in action.option_strings
            if option in self.RESERVED
        ]
        self.assertEqual(offenders, [], f"remote-only flags shadowed: {offenders}")


class TestLocalCliUnaffected(unittest.TestCase):

    def test_local_interrupt_claims_no_remote_cancellation(self):
        with patch("aidrin.headless.api.summarize_dataset", side_effect=KeyboardInterrupt):
            _out, err, code = _run_cli("summarize", "/x.csv")
        self.assertEqual(code, 130)
        self.assertNotIn("remote", err.lower())

    def test_local_summarize_still_works(self):
        import numpy as np
        import pandas as pd

        df = pd.DataFrame({"a": np.arange(10), "b": list("abcdefghij")})
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
        df.to_csv(tmp.name, index=False)
        tmp.close()
        try:
            out, _err, code = _run_cli("summarize", tmp.name)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["shape"]["rows"], 10)
        finally:
            os.unlink(tmp.name)
