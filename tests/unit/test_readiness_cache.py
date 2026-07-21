"""Unit tests for readiness report server-side section cache."""

import time
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from web.routes.metrics import (
    _cache_readiness_payload,
    _get_cached_readiness_payload,
    _readiness_section_cache_key,
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


if __name__ == "__main__":
    unittest.main()
