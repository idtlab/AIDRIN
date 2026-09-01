"""Unit tests for RemoteExecutor.

A fake client module records what would have been submitted, so these tests
cover argument shaping and local post-processing without any Globus SDK.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from aidrin.compute.executor import AsyncSubmitted, RemoteExecutor
from aidrin.compute.profiles import RemoteTarget


class _Recorder:
    """Stands in for aidrin.compute.client."""

    def __init__(self, result=None, poll_error=None, cancel_result=False):
        self.result = result if result is not None else {"ok": True}
        self.poll_error = poll_error
        self.cancel_result = cancel_result
        self.submitted = []
        self.polled = []
        self.cancelled = []

    def get_client(self):
        return "stub-client"

    def submit(self, client, endpoint_id, command, kwargs):
        self.submitted.append((endpoint_id, command, kwargs))
        return "task-xyz"

    def poll(self, client, task_id, timeout=600.0, interval=2.0):
        self.polled.append((task_id, timeout))
        if self.poll_error is not None:
            raise self.poll_error
        return self.result

    def cancel(self, client, task_id):
        self.cancelled.append(task_id)
        return self.cancel_result


def _executor(recorder, **kwargs):
    target = RemoteTarget(endpoint="endpoint-1", profile="nersc", source="profile")
    with patch("aidrin.compute.executor.client", recorder):
        return RemoteExecutor(target, **kwargs)


class TestCommandShaping(unittest.TestCase):

    def test_summarize_sends_summarize_command(self):
        rec = _Recorder(result={"columns": ["a"]})
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            result = ex.summarize_dataset("/scratch/data.csv", max_features=5)
        endpoint, command, kwargs = rec.submitted[0]
        self.assertEqual(endpoint, "endpoint-1")
        self.assertEqual(command, "summarize")
        self.assertEqual(kwargs["file_path"], "/scratch/data.csv")
        self.assertEqual(kwargs["max_features"], 5)
        self.assertEqual(result, {"columns": ["a"]})

    def test_run_metric_sends_metric_name(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            ex.run_metric("completeness", "/scratch/data.csv", columns=["a", "b"])
        _endpoint, command, kwargs = rec.submitted[0]
        self.assertEqual(command, "run_metric")
        self.assertEqual(kwargs["metric_name"], "completeness")
        self.assertEqual(kwargs["columns"], ["a", "b"])

    def test_run_metric_preserves_execution_host_units_file(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            ex.run_metric(
                "variable-unit-validation",
                "/scratch/data.csv",
                units_file="/scratch/units.json",
            )
        _endpoint, command, kwargs = rec.submitted[0]
        self.assertEqual(command, "run_metric")
        self.assertEqual(kwargs["units_file"], "/scratch/units.json")

    def test_data_quality_command(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_data_quality("/scratch/data.csv")
        self.assertEqual(rec.submitted[0][1], "data_quality")

    def test_batch_sends_config_as_dict(self):
        from aidrin.headless.config import HeadlessConfig

        rec = _Recorder()
        config = HeadlessConfig.from_dict(
            {"file_path": "/scratch/data.csv", "metrics": ["completeness"]}
        )
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_batch_metrics(config)
        _endpoint, command, kwargs = rec.submitted[0]
        self.assertEqual(command, "batch")
        self.assertIsInstance(kwargs["config"], dict)
        self.assertEqual(kwargs["config"]["file_path"], "/scratch/data.csv")


class TestImagePolicy(unittest.TestCase):

    def test_endpoint_never_writes_images(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_metric("completeness", "/x.csv", save_images=True)
        _endpoint, _command, kwargs = rec.submitted[0]
        self.assertFalse(kwargs["save_images"])

    def test_requesting_images_keeps_viz_payload(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_metric("completeness", "/x.csv", save_images=True)
        _endpoint, _command, kwargs = rec.submitted[0]
        self.assertFalse(kwargs["strip_visualizations"])

    def test_default_strips_viz_payload(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_metric("completeness", "/x.csv")
        _endpoint, _command, kwargs = rec.submitted[0]
        self.assertTrue(kwargs["strip_visualizations"])
        self.assertFalse(kwargs["save_images"])

    def test_images_are_written_locally(self):
        import base64

        png = base64.b64encode(b"not-a-real-png").decode()
        rec = _Recorder(result={"Visualization": png})
        target_dir = tempfile.mkdtemp()
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            result = ex.run_metric(
                "completeness", "/x.csv", save_images=True, image_dir=target_dir
            )
        self.assertTrue(result["Visualization"].startswith(target_dir))
        self.assertTrue(os.path.exists(result["Visualization"]))

    def test_run_metric_accepts_api_params_positionally(self):
        """A positional call through strip_visualizations must not raise.

        ``api.run_metric``'s signature is (metric_name, file_path, file_type,
        file_name, save_images, image_dir, verbose, strip_visualizations,
        **kwargs). If the executor's parameter order drifts, a caller that
        works against the local module breaks against the remote one.
        """
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_metric(
                "completeness", "/x.csv", None, None, True, None, False, False
            )
        _endpoint, command, kwargs = rec.submitted[0]
        self.assertEqual(command, "run_metric")
        self.assertEqual(kwargs["metric_name"], "completeness")


class TestBatchImagePolicy(unittest.TestCase):

    def test_batch_default_never_writes_images_and_strips_viz(self):
        from aidrin.headless.config import HeadlessConfig

        rec = _Recorder()
        config = HeadlessConfig.from_dict(
            {"file_path": "/scratch/data.csv", "metrics": ["completeness"]}
        )
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_batch_metrics(config)
        _endpoint, _command, kwargs = rec.submitted[0]
        self.assertFalse(kwargs["config"]["save_images"])
        self.assertTrue(kwargs["strip_visualizations"])

    def test_batch_with_images_requested_keeps_viz_payload_and_writes_locally(self):
        from aidrin.headless.config import HeadlessConfig
        import base64

        png = base64.b64encode(b"not-a-real-png").decode()
        rec = _Recorder(result={"completeness": {"Visualization": png}})
        target_dir = tempfile.mkdtemp()
        config = HeadlessConfig.from_dict(
            {
                "file_path": "/scratch/data.csv",
                "metrics": ["completeness"],
                "save_images": True,
                "image_dir": target_dir,
            }
        )
        with patch("aidrin.compute.executor.client", rec):
            result = _executor(rec).run_batch_metrics(config)
        _endpoint, _command, kwargs = rec.submitted[0]
        self.assertFalse(kwargs["config"]["save_images"])
        self.assertFalse(kwargs["strip_visualizations"])
        # image_dir is a directory on this machine; the endpoint never sees it.
        self.assertNotIn("image_dir", kwargs["config"])
        self.assertTrue(
            result["completeness"]["Visualization"].startswith(target_dir)
        )
        self.assertTrue(os.path.exists(result["completeness"]["Visualization"]))


class TestDetach(unittest.TestCase):

    def test_async_raises_with_task_id(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec, detach=True)
            with self.assertRaises(AsyncSubmitted) as ctx:
                ex.summarize_dataset("/x.csv")
        self.assertEqual(ctx.exception.task_id, "task-xyz")
        self.assertEqual(rec.polled, [])

    def test_blocking_passes_timeout_through(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec, timeout=42).summarize_dataset("/x.csv")
        self.assertEqual(rec.polled[0][1], 42)


class TestInterrupt(unittest.TestCase):

    def test_ctrl_c_cancels_the_task_before_re_raising(self):
        rec = _Recorder(poll_error=KeyboardInterrupt())
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            with self.assertRaises(KeyboardInterrupt):
                ex.summarize_dataset("/x.csv")
        self.assertEqual(rec.cancelled, ["task-xyz"])

    def test_ctrl_c_records_true_when_cancel_succeeds(self):
        rec = _Recorder(poll_error=KeyboardInterrupt(), cancel_result=True)
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            with self.assertRaises(KeyboardInterrupt):
                ex.summarize_dataset("/x.csv")
        self.assertTrue(ex.last_cancel_succeeded)

    def test_ctrl_c_records_false_when_cancel_is_not_supported(self):
        # Mirrors the real globus-compute-sdk 4.x case: cancel() cannot
        # actually cancel anything, and _call must not paper over that.
        rec = _Recorder(poll_error=KeyboardInterrupt(), cancel_result=False)
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            with self.assertRaises(KeyboardInterrupt):
                ex.summarize_dataset("/x.csv")
        self.assertFalse(ex.last_cancel_succeeded)

    def test_last_cancel_succeeded_is_none_before_any_interrupt(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            ex.summarize_dataset("/x.csv")
        self.assertIsNone(ex.last_cancel_succeeded)


class TestSubmitCallback(unittest.TestCase):

    def test_on_submit_receives_the_task_id(self):
        rec = _Recorder()
        seen = []
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec, on_submit=seen.append).summarize_dataset("/x.csv")
        self.assertEqual(seen, ["task-xyz"])

    def test_detached_submission_does_not_fire_on_submit(self):
        """Detached mode reports the id through AsyncSubmitted, not the hook."""
        rec = _Recorder()
        seen = []
        with patch("aidrin.compute.executor.client", rec):
            with self.assertRaises(AsyncSubmitted):
                _executor(rec, detach=True, on_submit=seen.append).summarize_dataset("/x.csv")
        self.assertEqual(seen, [])


class TestDuckTyping(unittest.TestCase):

    def test_executor_covers_every_api_function_the_cli_calls(self):
        """If this fails, the CLI's executor swap will break at runtime."""
        for name in ("run_metric", "summarize_dataset", "run_data_quality", "run_batch_metrics"):
            self.assertTrue(hasattr(RemoteExecutor, name), name)
