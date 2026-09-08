"""Full metric output archived as a run artifact.

The headline scores are only a handful of numbers; metrics like skewness,
correlations and outlier proportions carry per-column detail worth keeping.  So
the full result is archived as JSON — but the full result is also where the PII
lives, so it is gated and redacted.

Two gates, deliberately separate:

* ``AIDRIN_MLFLOW_LOG_DATA_DETAILS`` — on by default; archives the result with raw
  cell values redacted.  Set it to ``0`` for a shared tracking server, which also
  hashes dataset paths and withholds column names.
* ``AIDRIN_MLFLOW_LOG_RAW_RESULTS=1`` — archive it verbatim, with no redaction.
  This ships whatever AIDRIN found, including matched SSNs.  Opt-in, always, and
  it never re-enables archiving that was turned off.
"""

import json
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

from aidrin.telemetry.redaction import redact_result  # noqa: E402

PHI_RESULT = {
    "zip_code": {
        "total_flags": 1000,
        "potential_types_detected": ["VALID_POSTAL_CODE"],
        "examples": ["10002", "60601", "10001"],
    }
}

FILEREF_RESULT = {
    "Summary": {"invalid_references": 1, "valid_references": 9},
    "Invalid references": [
        {
            "target": "scan_path",
            "location": "row 4",
            "value": "'/data/patients/MRN-4417723/scan.dcm'",
            "normalized_value": "/data/patients/MRN-4417723/scan.dcm",
            "resolved_path": "/data/patients/MRN-4417723/scan.dcm",
            "reason": "missing",
        }
    ],
}

SKEWNESS_RESULT = {
    "Skewness": {"age": 0.31, "income": 2.04, "credit_score": -0.12},
    "Description": "Skewness measures distribution asymmetry.",
}


class TestRedactionKeepsDetail(unittest.TestCase):
    """The point of the artifact is the per-column numbers; keep them."""

    def test_per_column_numbers_survive(self):
        out = redact_result("skewness", SKEWNESS_RESULT)
        self.assertEqual(out["Skewness"]["age"], 0.31)
        self.assertEqual(out["Skewness"]["income"], 2.04)

    def test_counts_survive_on_a_leaky_metric(self):
        out = redact_result("hipaa_compliance", PHI_RESULT)
        self.assertEqual(out["zip_code"]["total_flags"], 1000)
        self.assertEqual(out["zip_code"]["potential_types_detected"], ["VALID_POSTAL_CODE"])

    def test_summary_counts_survive(self):
        out = redact_result("file_reference_validation", FILEREF_RESULT)
        self.assertEqual(out["Summary"]["invalid_references"], 1)


class TestRedactionRemovesRawValues(unittest.TestCase):
    def test_hipaa_examples_are_removed(self):
        out = redact_result("hipaa_compliance", PHI_RESULT)
        self.assertNotIn("10002", json.dumps(out))
        self.assertNotIn("examples", json.dumps(out))

    def test_file_reference_paths_are_removed(self):
        out = redact_result("file_reference_validation", FILEREF_RESULT)
        self.assertNotIn("MRN-4417723", json.dumps(out))

    def test_duplicate_group_values_are_removed(self):
        result = {
            "Duplicate groups": [
                {"Feature values": {"name": "Jane Doe"}, "Row count": 3}
            ],
            "Overall duplicity of the dataset": 0.2,
        }
        out = redact_result("duplicity_by_features", result)
        self.assertNotIn("Jane Doe", json.dumps(out))
        self.assertEqual(out["Overall duplicity of the dataset"], 0.2)

    def test_sensitive_attribute_keys_are_removed_but_counted(self):
        result = {"Statistical Rates": {"female": 0.31, "non-binary": 0.02, "male": 0.67}}
        out = redact_result("statistical_rates", result)
        rendered = json.dumps(out)
        for value in ("female", "non-binary", "male"):
            self.assertNotIn(value, rendered)

    def test_error_messages_are_removed(self):
        result = {"Error": "cannot parse 'SSN-123-45-6789' in column 'patient_ssn'"}
        out = redact_result("completeness", result)
        rendered = json.dumps(out)
        self.assertNotIn("SSN-123-45-6789", rendered)
        self.assertNotIn("patient_ssn", rendered)

    def test_outlier_preview_rows_are_removed(self):
        result = {
            "preview": [{"value": "42.9", "location": "row 3", "rule_id": "r1"}],
            "summary": {"outlier": 1},
        }
        out = redact_result("outliers_custom", result)
        self.assertNotIn("preview", json.dumps(out))
        self.assertEqual(out["summary"]["outlier"], 1)

    def test_base64_visualizations_are_removed(self):
        result = {"Completeness Visualization": "iVBORw0KGgoAAAANS" * 500, "x": 1}
        out = redact_result("completeness", result)
        self.assertLess(len(json.dumps(out)), 200)

    def test_redaction_is_structural_not_metric_specific(self):
        """An unknown metric gets the same treatment — no allowlist to forget."""
        result = {"Error": "leaked 'value'", "examples": ["a"], "count": 5}
        out = redact_result("some_future_metric", result)
        self.assertNotIn("leaked", json.dumps(out))
        self.assertNotIn("examples", json.dumps(out))
        self.assertEqual(out["count"], 5)


@unittest.skipUnless(
    __import__("importlib").util.find_spec("mlflow"), "requires the [mlflow] extra"
)
class TestArtifactGating(unittest.TestCase):
    def setUp(self):
        import tempfile

        from mlflow.tracking import MlflowClient

        from aidrin.telemetry import mlflow_sink

        self.sink = mlflow_sink
        self.tmp = tempfile.mkdtemp()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        os.environ["MLFLOW_TRACKING_URI"] = f"file://{self.tmp}"
        os.environ["AIDRIN_MLFLOW_ENABLED"] = "1"
        os.environ["AIDRIN_MLFLOW_EXPERIMENT"] = "aidrin-artifacts"
        for var in ("AIDRIN_MLFLOW_LOG_DATA_DETAILS", "AIDRIN_MLFLOW_LOG_RAW_RESULTS"):
            os.environ.pop(var, None)
        mlflow_sink.reset()
        self.client = MlflowClient(tracking_uri=f"file://{self.tmp}")

    def tearDown(self):
        self.sink.reset()
        for var in (
            "AIDRIN_MLFLOW_ENABLED",
            "MLFLOW_TRACKING_URI",
            "AIDRIN_MLFLOW_EXPERIMENT",
            "MLFLOW_ALLOW_FILE_STORE",
            "AIDRIN_MLFLOW_LOG_DATA_DETAILS",
            "AIDRIN_MLFLOW_LOG_RAW_RESULTS",
        ):
            os.environ.pop(var, None)

    def _log_and_fetch_artifacts(self):
        session = self.sink.start_session(file_path="/tmp/d.csv")
        self.sink.log_metric_result(session, "hipaa_compliance", PHI_RESULT, 0.1, "/tmp/d.csv")
        self.sink.end_session(session)
        exp = self.client.get_experiment_by_name("aidrin-artifacts")
        runs = self.client.search_runs([exp.experiment_id])
        child = [r for r in runs if r.data.tags.get("aidrin.metric")][0]
        return child, [a.path for a in self.client.list_artifacts(child.info.run_id)]

    def test_result_is_archived_by_default(self):
        _, artifacts = self._log_and_fetch_artifacts()
        self.assertIn("result.json", artifacts)

    def test_archiving_can_be_turned_off(self):
        os.environ["AIDRIN_MLFLOW_LOG_DATA_DETAILS"] = "0"
        self.sink.reset()
        _, artifacts = self._log_and_fetch_artifacts()
        self.assertEqual(artifacts, [])

    def test_the_archived_result_is_redacted(self):
        child, artifacts = self._log_and_fetch_artifacts()
        self.assertIn("result.json", artifacts)

        local = self.client.download_artifacts(child.info.run_id, "result.json")
        body = open(local).read()
        self.assertNotIn("10002", body, "raw PHI reached the redacted artifact")
        self.assertIn("total_flags", body)

    def test_raw_flag_archives_verbatim(self):
        os.environ["AIDRIN_MLFLOW_LOG_RAW_RESULTS"] = "1"
        self.sink.reset()
        child, artifacts = self._log_and_fetch_artifacts()
        self.assertIn("result.json", artifacts)

        local = self.client.download_artifacts(child.info.run_id, "result.json")
        body = open(local).read()
        self.assertIn("10002", body, "raw mode should archive the result verbatim")

    def test_raw_flag_does_not_re_enable_disabled_archiving(self):
        """Raw modifies how an archive is written; it never switches it on."""
        os.environ["AIDRIN_MLFLOW_LOG_DATA_DETAILS"] = "0"
        os.environ["AIDRIN_MLFLOW_LOG_RAW_RESULTS"] = "1"
        self.sink.reset()
        _, artifacts = self._log_and_fetch_artifacts()
        self.assertEqual(artifacts, [])


if __name__ == "__main__":
    unittest.main()
