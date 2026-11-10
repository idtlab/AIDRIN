"""Unit tests for readiness report server-side section cache."""

import time
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from web.routes.metrics import (
    _cache_readiness_fair_compliance,
    _cache_readiness_payload,
    _fair_metadata_fingerprint,
    _get_cached_readiness_fair_compliance,
    _get_cached_readiness_payload,
    _readiness_fair_cache_key,
    _readiness_section_cache_key,
    get_cached_readiness_fair_report,
    get_cached_readiness_report,
)


class TestReadinessSectionCacheKey(unittest.TestCase):
    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    def test_section_key_matches_cached_result_pattern(self, _mock_user):
        key = _readiness_section_cache_key("data.csv", "data-quality")
        self.assertEqual(key, "user:user-1:file:data.csv:readiness_report:data-quality")

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    def test_visualization_key_is_per_section(self, _mock_user):
        key = _readiness_section_cache_key("data.csv", "dataset-overview", viz=True)
        self.assertEqual(
            key,
            "user:user-1:file:data.csv:readiness_report:dataset-overview:visualizations",
        )


class TestReadinessSectionCacheStore(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.TEMP_RESULTS_CACHE = {}
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    @patch("web.routes.metrics.current_app")
    def test_store_and_retrieve_section_payload(self, mock_current_app, _mock_user):
        mock_current_app.TEMP_RESULTS_CACHE = self.app.TEMP_RESULTS_CACHE
        payload = {"grade": 0.9, "kpis": []}
        _cache_readiness_payload("data.csv", "data-quality", payload, 1.23)

        cached, build_time = _get_cached_readiness_payload("data.csv", "data-quality")
        self.assertEqual(cached, payload)
        self.assertEqual(build_time, 1.23)

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    @patch("web.routes.metrics.current_app")
    def test_error_sections_are_not_cached(self, mock_current_app, _mock_user):
        mock_current_app.TEMP_RESULTS_CACHE = self.app.TEMP_RESULTS_CACHE
        _cache_readiness_payload(
            "data.csv", "impact-on-ai", {"error": "failed"}, 0.5
        )
        cached, _ = _get_cached_readiness_payload("data.csv", "impact-on-ai")
        self.assertIsNone(cached)

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    @patch("web.routes.metrics.current_app")
    def test_expired_entries_are_evicted(self, mock_current_app, _mock_user):
        mock_current_app.TEMP_RESULTS_CACHE = self.app.TEMP_RESULTS_CACHE
        key = _readiness_section_cache_key("data.csv", "data-quality")
        self.app.TEMP_RESULTS_CACHE[key] = {
            "data": {"grade": 1.0},
            "timestamp": time.time() - 7200,
            "expires_at": time.time() - 1,
            "build_time_seconds": 2.0,
        }
        cached, _ = _get_cached_readiness_payload("data.csv", "data-quality")
        self.assertIsNone(cached)
        self.assertNotIn(key, self.app.TEMP_RESULTS_CACHE)

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    @patch("web.routes.metrics.current_app")
    def test_upload_style_clear_removes_user_keys(self, mock_current_app, _mock_user):
        mock_current_app.TEMP_RESULTS_CACHE = self.app.TEMP_RESULTS_CACHE
        _cache_readiness_payload("data.csv", "data-quality", {"grade": 0.8}, 1.0)
        _cache_readiness_payload(
            "data.csv", "dataset-overview", {"histograms": {}}, 2.0, viz=True
        )
        self.assertEqual(len(self.app.TEMP_RESULTS_CACHE), 2)

        keys_to_remove = [
            key
            for key in self.app.TEMP_RESULTS_CACHE
            if key.startswith("user:user-1")
        ]
        for key in keys_to_remove:
            self.app.TEMP_RESULTS_CACHE.pop(key, None)

        cached, _ = _get_cached_readiness_payload("data.csv", "data-quality")
        self.assertIsNone(cached)


class TestReadinessAggregatedCache(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.TEMP_RESULTS_CACHE = {}
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    @patch("web.routes.metrics.current_app")
    def test_get_cached_readiness_report_returns_all_sections(
        self, mock_current_app, _mock_user
    ):
        mock_current_app.TEMP_RESULTS_CACHE = self.app.TEMP_RESULTS_CACHE
        sections = {
            "dataset-overview": {"rows": 10},
            "data-quality": {"grade": 0.9},
            "impact-on-ai": {"grade": 0.8},
            "fairness-bias": {"grade": 0.7},
            "data-governance": {"grade": 0.6},
        }
        for slug, payload in sections.items():
            _cache_readiness_payload("data.csv", slug, payload, 1.0)

        result = get_cached_readiness_report("data.csv")
        self.assertIsNotNone(result)
        self.assertTrue(result["cached"])
        self.assertEqual(set(result["sections"].keys()), set(sections.keys()))
        self.assertEqual(result["sections"]["data-quality"]["grade"], 0.9)
        self.assertEqual(result["sections"]["data-quality"]["build_time_seconds"], 1.0)
        self.assertTrue(all(result["sections_cached"].values()))

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    @patch("web.routes.metrics.current_app")
    def test_get_cached_readiness_report_requires_every_section(
        self, mock_current_app, _mock_user
    ):
        mock_current_app.TEMP_RESULTS_CACHE = self.app.TEMP_RESULTS_CACHE
        _cache_readiness_payload("data.csv", "data-quality", {"grade": 0.9}, 1.0)

        self.assertIsNone(get_cached_readiness_report("data.csv"))


class TestReadinessFairCache(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.TEMP_RESULTS_CACHE = {}
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    def test_fair_cache_key_matches_pattern(self, _mock_user):
        key = _readiness_fair_cache_key("data.csv")
        self.assertEqual(key, "user:user-1:file:data.csv:readiness_report:fair")

    def test_metadata_fingerprint_changes_with_type(self):
        payload = b'{"title": "example"}'
        dcat = _fair_metadata_fingerprint(payload, "DCAT")
        datacite = _fair_metadata_fingerprint(payload, "Datacite")
        self.assertNotEqual(dcat, datacite)

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    @patch("web.routes.metrics.current_app")
    def test_store_and_retrieve_fair_compliance(self, mock_current_app, _mock_user):
        mock_current_app.TEMP_RESULTS_CACHE = self.app.TEMP_RESULTS_CACHE
        payload = {"FAIR Compliance Checks": {"Total Checks": "10/19"}}
        _cache_readiness_fair_compliance(
            "data.csv",
            payload,
            metadata_type="DCAT",
            metadata_filename="meta.json",
            metadata_fingerprint="abc123",
            build_time_seconds=0.75,
        )

        cached = _get_cached_readiness_fair_compliance("data.csv")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["data"], payload)
        self.assertEqual(cached["metadata_type"], "DCAT")
        self.assertEqual(cached["metadata_filename"], "meta.json")
        self.assertEqual(cached["metadata_fingerprint"], "abc123")
        self.assertEqual(cached["build_time_seconds"], 0.75)

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    @patch("web.routes.metrics.current_app")
    def test_get_cached_readiness_fair_report(self, mock_current_app, _mock_user):
        mock_current_app.TEMP_RESULTS_CACHE = self.app.TEMP_RESULTS_CACHE
        _cache_readiness_fair_compliance(
            "data.csv",
            {"Findable": {}},
            metadata_type="Datacite",
            metadata_filename="dc.json",
            metadata_fingerprint="fp1",
            build_time_seconds=1.0,
        )

        result = get_cached_readiness_fair_report("data.csv")
        self.assertIsNotNone(result)
        self.assertTrue(result["cached"])
        self.assertEqual(result["fair_compliance"]["metadata_filename"], "dc.json")

    @patch("web.routes.metrics.get_current_user_id", return_value="user-1")
    @patch("web.routes.metrics.current_app")
    def test_aggregated_report_includes_optional_fair_compliance(
        self, mock_current_app, _mock_user
    ):
        mock_current_app.TEMP_RESULTS_CACHE = self.app.TEMP_RESULTS_CACHE
        for slug in (
            "dataset-overview",
            "data-quality",
            "impact-on-ai",
            "fairness-bias",
            "data-governance",
        ):
            _cache_readiness_payload("data.csv", slug, {"grade": 0.5}, 1.0)
        _cache_readiness_fair_compliance(
            "data.csv",
            {"FAIR Compliance Checks": {"Total Checks": "5/19"}},
            metadata_type="DCAT",
            metadata_filename="meta.json",
            metadata_fingerprint="fp2",
            build_time_seconds=0.5,
        )

        result = get_cached_readiness_report("data.csv")
        self.assertIn("fair_compliance", result)
        self.assertEqual(
            result["fair_compliance"]["data"]["FAIR Compliance Checks"]["Total Checks"],
            "5/19",
        )


if __name__ == "__main__":
    unittest.main()
