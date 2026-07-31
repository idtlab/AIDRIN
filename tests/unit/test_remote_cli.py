"""Unit tests for the `aidrin remote` CLI surface."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aidrin.compute.executor import AsyncSubmitted


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

    def tearDown(self):
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

    def test_remove_reports_unknown_profile(self):
        _out, err, code = _run_cli("remote", "remove", "ghost")
        self.assertEqual(code, 1)
        self.assertIn("ghost", err)


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


class TestLocalCliUnaffected(unittest.TestCase):

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
