"""Unit tests for the headless remote entry point (aidrin.compute.remote).

These call remote_headless_runner directly. No Globus SDK and no endpoint are
involved: the point is to prove the remote path dispatches into the same
aidrin.headless.api functions the local CLI uses.
"""

import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from aidrin.compute.remote import remote_env_probe, remote_headless_runner


def _sample_csv() -> str:
    rng = np.random.default_rng(7)
    df = pd.DataFrame(
        {
            "age": rng.integers(20, 70, size=40),
            "income": rng.integers(20_000, 90_000, size=40),
            "sex": rng.choice(["M", "F"], size=40),
        }
    )
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return tmp.name


class TestRemoteHeadlessRunner(unittest.TestCase):

    def setUp(self):
        self.path = _sample_csv()

    def tearDown(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def test_summarize_dispatches_to_api(self):
        result = remote_headless_runner("summarize", {"file_path": self.path})
        self.assertEqual(result["columns"], ["age", "income", "sex"])
        self.assertEqual(result["shape"]["rows"], 40)

    def test_run_metric_dispatches_to_api(self):
        result = remote_headless_runner(
            "run_metric",
            {"metric_name": "completeness", "file_path": self.path, "save_images": False},
        )
        self.assertIn("Completeness scores", result)

    def test_data_quality_dispatches_to_api(self):
        result = remote_headless_runner("data_quality", {"file_path": self.path})
        self.assertIn("completeness", result)

    def test_batch_dispatches_to_api(self):
        result = remote_headless_runner(
            "batch",
            {"config": {"file_path": self.path, "metrics": ["completeness"], "save_images": False}},
        )
        self.assertIn("completeness", result)

    def test_unknown_command_returns_error_dict(self):
        result = remote_headless_runner("nope", {})
        self.assertEqual(result["ErrorType"], "UnknownCommand")
        self.assertIn("nope", result["Error"])

    def test_exception_is_returned_not_raised(self):
        result = remote_headless_runner(
            "summarize", {"file_path": "/definitely/missing/file.csv"}
        )
        self.assertIn("Error", result)
        self.assertIn("ErrorType", result)


class TestRemoteHeadlessRunnerCacheCleanup(unittest.TestCase):
    """The endpoint has no upload-folder reaper for its `.aidrin.feather`
    cache sidecar (unlike the web app) and the local CLI's own cleanup is
    deliberately skipped for remote runs (it would delete a sidecar next to
    a same-named *local* path it never read). Nothing else sweeps the
    sidecar `read_file()` leaves next to the dataset it parses on the
    endpoint's filesystem, so `remote_headless_runner` must do it itself.
    """

    def setUp(self):
        # An isolated directory, not the shared system tmp dir that
        # `_sample_csv()` uses: other tests' own cache sidecars (or leftovers
        # from a previous run) would otherwise pollute the directory listing
        # this test class asserts on.
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "data.csv")
        rng = np.random.default_rng(7)
        pd.DataFrame(
            {
                "age": rng.integers(20, 70, size=40),
                "income": rng.integers(20_000, 90_000, size=40),
                "sex": rng.choice(["M", "F"], size=40),
            }
        ).to_csv(self.path, index=False)

    def _cache_sidecars(self):
        return [name for name in os.listdir(self.tmpdir) if name.endswith(".aidrin.feather")]

    def test_summarize_leaves_no_cache_sidecar(self):
        remote_headless_runner("summarize", {"file_path": self.path})
        self.assertEqual(self._cache_sidecars(), [])

    def test_run_metric_leaves_no_cache_sidecar(self):
        remote_headless_runner(
            "run_metric",
            {"metric_name": "completeness", "file_path": self.path, "save_images": False},
        )
        self.assertEqual(self._cache_sidecars(), [])

    def test_batch_leaves_no_cache_sidecar(self):
        remote_headless_runner(
            "batch",
            {"config": {"file_path": self.path, "metrics": ["completeness"], "save_images": False}},
        )
        self.assertEqual(self._cache_sidecars(), [])

    def test_cleanup_runs_on_the_error_path_too(self):
        missing = os.path.join(self.tmpdir, "definitely-missing.csv")
        result = remote_headless_runner("summarize", {"file_path": missing})
        self.assertIn("Error", result)
        self.assertEqual(self._cache_sidecars(), [])


class TestRemoteEnvProbe(unittest.TestCase):

    def test_probe_reports_headless_import(self):
        result = remote_env_probe()
        self.assertIn("aidrin_version", result)
        self.assertIn("python_version", result)
        self.assertIs(result["headless_import"], True)
