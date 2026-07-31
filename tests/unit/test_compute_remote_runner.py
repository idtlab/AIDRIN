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


class TestRemoteEnvProbe(unittest.TestCase):

    def test_probe_reports_headless_import(self):
        result = remote_env_probe()
        self.assertIn("aidrin_version", result)
        self.assertIn("python_version", result)
        self.assertIs(result["headless_import"], True)
