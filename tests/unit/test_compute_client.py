"""Unit tests for the headless Globus Compute client.

A stub client stands in for globus_compute_sdk.Client, so no SDK, no
credentials, and no endpoint are needed.
"""

import unittest
from unittest.mock import patch

from aidrin.compute import client as compute_client


class _StubTaskPending(Exception):
    """Mimics the SDK's pending-task exception (message-matched, as in web/globus.py)."""


class _StubClient:
    """Minimal stand-in for globus_compute_sdk.Client."""

    def __init__(self, results=None, run_error=None):
        # results: list of (kind, value); kind in {"pending", "result", "error"}
        self._results = list(results or [])
        self._run_error = run_error
        self.registered = []
        self.runs = []
        self.cancelled = []

    def register_function(self, fn):
        self.registered.append(fn)
        return f"func-{fn.__name__}"

    def run(self, *args, endpoint_id=None, function_id=None, **kwargs):
        if self._run_error:
            raise self._run_error
        self.runs.append({"args": args, "endpoint_id": endpoint_id, "function_id": function_id})
        return "task-abc"

    def get_result(self, task_id):
        kind, value = self._results.pop(0)
        if kind == "pending":
            raise _StubTaskPending("Task pending")
        if kind == "error":
            raise RuntimeError(value)
        return value

    def cancel_task(self, task_id):
        self.cancelled.append(task_id)


class TestAvailability(unittest.TestCase):

    def test_is_available_returns_bool(self):
        self.assertIsInstance(compute_client.is_available(), bool)

    def test_get_client_raises_when_sdk_missing(self):
        with patch.object(compute_client, "_sdk_available", False):
            with self.assertRaises(compute_client.GlobusUnavailable) as ctx:
                compute_client.get_client()
            self.assertIn("aidrin[globus]", str(ctx.exception))


class TestRegister(unittest.TestCase):

    def setUp(self):
        compute_client.clear_function_cache()

    def test_registers_headless_runner_once(self):
        stub = _StubClient()
        first = compute_client.register(stub)
        second = compute_client.register(stub)
        self.assertEqual(first, second)
        self.assertEqual(len(stub.registered), 1)
        self.assertEqual(stub.registered[0].__name__, "remote_headless_runner")

    def test_force_reregisters(self):
        stub = _StubClient()
        compute_client.register(stub)
        compute_client.register(stub, force=True)
        self.assertEqual(len(stub.registered), 2)


class TestSubmit(unittest.TestCase):

    def setUp(self):
        compute_client.clear_function_cache()

    def test_submit_passes_command_and_kwargs_positionally(self):
        stub = _StubClient()
        task_id = compute_client.submit(stub, "endpoint-1", "summarize", {"file_path": "/x.csv"})
        self.assertEqual(task_id, "task-abc")
        run = stub.runs[0]
        self.assertEqual(run["args"], ("summarize", {"file_path": "/x.csv"}))
        self.assertEqual(run["endpoint_id"], "endpoint-1")


class TestCheckAndPoll(unittest.TestCase):

    def setUp(self):
        compute_client.clear_function_cache()

    def test_check_completed(self):
        stub = _StubClient(results=[("result", {"ok": True})])
        status = compute_client.check(stub, "task-abc")
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["result"], {"ok": True})

    def test_check_pending(self):
        stub = _StubClient(results=[("pending", None)])
        status = compute_client.check(stub, "task-abc")
        self.assertEqual(status["status"], "processing")

    def test_check_failed(self):
        stub = _StubClient(results=[("error", "worker exploded")])
        status = compute_client.check(stub, "task-abc")
        self.assertEqual(status["status"], "failed")
        self.assertIn("worker exploded", status["error"])

    def test_poll_returns_result_after_pending_rounds(self):
        stub = _StubClient(results=[("pending", None), ("pending", None), ("result", {"ok": 1})])
        slept = []
        result = compute_client.poll(
            stub, "task-abc", timeout=100, interval=2, sleep=slept.append, now=lambda: 0.0
        )
        self.assertEqual(result, {"ok": 1})
        self.assertEqual(slept, [2, 2])

    def test_poll_raises_remote_error_on_failure(self):
        stub = _StubClient(results=[("error", "boom")])
        with self.assertRaises(compute_client.RemoteError):
            compute_client.poll(stub, "task-abc", sleep=lambda _s: None, now=lambda: 0.0)

    def test_poll_times_out_with_task_id(self):
        stub = _StubClient(results=[("pending", None)] * 10)
        clock = iter([0.0, 5.0, 999.0, 999.0])
        with self.assertRaises(compute_client.RemoteTimeout) as ctx:
            compute_client.poll(
                stub, "task-abc", timeout=10, interval=1,
                sleep=lambda _s: None, now=lambda: next(clock),
            )
        self.assertEqual(ctx.exception.task_id, "task-abc")

    def test_poll_reports_result_size_limit_clearly(self):
        stub = _StubClient(results=[("error", "Result size 12000000 exceeds the maximum")])
        with self.assertRaises(compute_client.RemoteError) as ctx:
            compute_client.poll(stub, "task-abc", sleep=lambda _s: None, now=lambda: 0.0)
        self.assertIn("--save-images", str(ctx.exception))

    def test_check_does_not_treat_running_as_pending(self):
        # A genuine failure whose message happens to contain "running" must not
        # be misclassified as still-processing (matches web.globus.check_task,
        # which only matches "pending"/"waiting").
        stub = _StubClient(results=[("error", "error while running the batch job")])
        status = compute_client.check(stub, "task-abc")
        self.assertEqual(status["status"], "failed")
        self.assertIn("error while running the batch job", status["error"])

    def test_check_still_treats_pending_as_processing(self):
        # Guard against over-correcting: "pending" must still map to processing.
        stub = _StubClient(results=[("error", "Task pending on remote endpoint")])
        status = compute_client.check(stub, "task-abc")
        self.assertEqual(status["status"], "processing")

    def test_poll_raises_remote_error_for_running_failure_not_timeout(self):
        stub = _StubClient(results=[("error", "error while running the batch job")])
        with self.assertRaises(compute_client.RemoteError) as ctx:
            compute_client.poll(stub, "task-abc", sleep=lambda _s: None, now=lambda: 0.0)
        self.assertNotIsInstance(ctx.exception, compute_client.RemoteTimeout)
        self.assertIn("error while running the batch job", str(ctx.exception))


class TestProbe(unittest.TestCase):

    def setUp(self):
        compute_client.clear_function_cache()

    def test_probe_returns_env_dict(self):
        payload = {"aidrin_version": "0.9.2", "python_version": "3.12.4", "headless_import": True}
        stub = _StubClient(results=[("result", payload)])
        self.assertEqual(compute_client.probe(stub, "endpoint-1"), payload)

    def test_probe_rejects_broken_headless_import(self):
        payload = {
            "aidrin_version": "0.9.2",
            "python_version": "3.12.4",
            "headless_import": "ImportError: no module named aidrin.headless",
        }
        stub = _StubClient(results=[("result", payload)])
        with self.assertRaises(compute_client.RemoteError) as ctx:
            compute_client.probe(stub, "endpoint-1")
        self.assertIn("aidrin.headless", str(ctx.exception))


class TestCancel(unittest.TestCase):

    def test_cancel_calls_through_and_returns_true(self):
        stub = _StubClient()
        result = compute_client.cancel(stub, "task-abc")
        self.assertEqual(stub.cancelled, ["task-abc"])
        self.assertTrue(result)

    def test_cancel_swallows_backend_errors_and_returns_false(self):
        class _Boom:
            def cancel_task(self, task_id):
                raise RuntimeError("no such task")

        result = compute_client.cancel(_Boom(), "task-abc")  # must not raise
        self.assertFalse(result)

    def test_cancel_returns_false_when_sdk_has_no_cancel_task(self):
        # This is the real globus-compute-sdk 4.x case: Client has no
        # cancel_task method at all, unlike the older SDK versions the rest
        # of this test module simulates.
        class _NoCancelSupport:
            pass

        result = compute_client.cancel(_NoCancelSupport(), "task-abc")
        self.assertFalse(result)
