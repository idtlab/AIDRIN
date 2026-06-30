"""Unit tests for HIPAA identifier detection (hipaa_compliance.py).

detect_hipaa_identifiers is a plain Python function — no Celery, Flask, or
Redis required.  Tests confirm detection accuracy for each PHI pattern.

Note: postal-code detection uses the pgeocode database (network-free local
lookup after first download).  Tests that rely on it are skipped when pgeocode
cannot access its data directory.
"""

import sys
import types
import unittest

import pandas as pd

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from aidrin.structured_data_metrics.hipaa_compliance import detect_hipaa_identifiers  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(data: dict, columns=None) -> dict:
    df = pd.DataFrame(data)
    cols = columns or list(df.columns)
    return detect_hipaa_identifiers(df, cols)


# ===========================================================================
# Pattern detection tests
# ===========================================================================


class TestSSNDetection(unittest.TestCase):

    def test_detects_ssn(self):
        result = _run({"info": ["Patient SSN: 123-45-6789"]})
        self.assertIn("info", result)
        self.assertIn("US_SSN", result["info"]["potential_types_detected"])

    def test_no_false_positive_on_plain_numbers(self):
        result = _run({"score": ["score is 987"]})
        # Should not flag a plain integer as SSN
        if "score" in result:
            self.assertNotIn("US_SSN", result["score"]["potential_types_detected"])


class TestEmailDetection(unittest.TestCase):

    def test_detects_email(self):
        result = _run({"contact": ["reach me at john.doe@example.com"]})
        self.assertIn("contact", result)
        self.assertIn("EMAIL_ADDRESS", result["contact"]["potential_types_detected"])

    def test_no_email_in_clean_data(self):
        result = _run({"contact": ["no email here, just text"]})
        if "contact" in result:
            self.assertNotIn("EMAIL_ADDRESS", result["contact"]["potential_types_detected"])


class TestPhoneDetection(unittest.TestCase):

    def test_detects_us_phone(self):
        result = _run({"phone": ["Call: 555-867-5309"]})
        self.assertIn("phone", result)
        self.assertIn("PHONE_OR_FAX", result["phone"]["potential_types_detected"])

    def test_detects_phone_with_country_code(self):
        result = _run({"phone": ["+1-800-123-4567"]})
        self.assertIn("phone", result)
        self.assertIn("PHONE_OR_FAX", result["phone"]["potential_types_detected"])


class TestIPAddressDetection(unittest.TestCase):

    def test_detects_ip_address(self):
        result = _run({"log": ["connected from 192.168.1.1"]})
        self.assertIn("log", result)
        self.assertIn("IP_ADDRESS", result["log"]["potential_types_detected"])


class TestURLDetection(unittest.TestCase):

    def test_detects_http_url(self):
        result = _run({"ref": ["see http://example.com for details"]})
        self.assertIn("ref", result)
        self.assertIn("URL", result["ref"]["potential_types_detected"])

    def test_detects_https_url(self):
        result = _run({"ref": ["https://hospital.org/patient/42"]})
        self.assertIn("ref", result)
        self.assertIn("URL", result["ref"]["potential_types_detected"])


class TestMedicalIDDetection(unittest.TestCase):

    def test_detects_mrn(self):
        # Pattern: MRN[:\s]?[A-Z0-9\-]+ — no space between colon and digits
        result = _run({"notes": ["MRN:00123456"]})
        self.assertIn("notes", result)
        self.assertIn("MEDICAL_IDS", result["notes"]["potential_types_detected"])


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases(unittest.TestCase):

    def test_empty_dataframe(self):
        df = pd.DataFrame({"info": []})
        result = detect_hipaa_identifiers(df, ["info"])
        # No findings in empty data
        self.assertNotIn("info", result)

    def test_none_values_skipped(self):
        result = _run({"info": [None, None, None]})
        # No PHI in None values
        self.assertNotIn("info", result)

    def test_column_not_in_df_skipped(self):
        df = pd.DataFrame({"a": ["text"]})
        result = detect_hipaa_identifiers(df, ["a", "nonexistent"])
        # Should not raise; nonexistent column is silently skipped
        self.assertNotIn("nonexistent", result)

    def test_multiple_phi_types_in_one_column(self):
        result = _run({
            "mixed": ["Contact: john@example.com, phone: 555-123-4567, SSN: 123-45-6789"]
        })
        self.assertIn("mixed", result)
        types_detected = result["mixed"]["potential_types_detected"]
        self.assertIn("EMAIL_ADDRESS", types_detected)
        self.assertIn("PHONE_OR_FAX", types_detected)
        self.assertIn("US_SSN", types_detected)

    def test_total_flags_counts_all_matches(self):
        # Three separate phone numbers in the same cell
        result = _run({
            "phones": ["555-111-2222 and 555-333-4444 and 555-555-6666"]
        })
        self.assertIn("phones", result)
        self.assertGreaterEqual(result["phones"]["total_flags"], 3)

    def test_examples_capped_at_five(self):
        # Many distinct emails — examples should not exceed 5
        emails = [f"user{i}@example.com" for i in range(20)]
        df = pd.DataFrame({"col": emails})
        result = detect_hipaa_identifiers(df, ["col"])
        if "col" in result:
            self.assertLessEqual(len(result["col"]["examples"]), 5)

    def test_clean_data_returns_empty_dict(self):
        result = _run({
            "name": ["Alice", "Bob", "Carol"],
            "score": ["95", "87", "91"],
        })
        self.assertEqual(result, {})

    def test_scans_only_requested_columns(self):
        df = pd.DataFrame({
            "phi_col": ["email: test@example.com"],
            "clean_col": ["no phi here"],
        })
        # Only scan clean_col — should find nothing
        result = detect_hipaa_identifiers(df, ["clean_col"])
        self.assertNotIn("phi_col", result)
        self.assertNotIn("clean_col", result)


if __name__ == "__main__":
    unittest.main()
