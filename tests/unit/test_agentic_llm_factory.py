"""Unit tests for aidrin.agentic.llm_factory.resolve_provider_api_key.

This pipeline intentionally supports exactly one LLM provider per run —
OpenRouter or LBL CBORG — with no fallback to a third provider (including the
previously-shipped default of plain OpenAI). These tests cover the key
resolution contract: which env var wins for which base_url, that an explicit
key always wins, and that an unrecognized base_url (e.g. an old config still
pointing at api.openai.com) fails immediately with a clear message instead of
silently resolving to no key or silently falling back to OPENAI_API_KEY.
"""

from __future__ import annotations

import os
import unittest

from aidrin.agentic.llm_factory import resolve_provider_api_key


class TestResolveProviderApiKey(unittest.TestCase):
    def setUp(self):
        self._saved_env = {
            k: os.environ.pop(k, None)
            for k in ("OPENROUTER_API_KEY", "CBORG_API_KEY", "OPENAI_API_KEY")
        }

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_no_base_url_returns_none(self):
        self.assertIsNone(resolve_provider_api_key(None))

    def test_explicit_key_wins_regardless_of_base_url(self):
        os.environ["OPENROUTER_API_KEY"] = "or-key"
        self.assertEqual(
            resolve_provider_api_key("https://openrouter.ai/api/v1", explicit="explicit-key"),
            "explicit-key",
        )

    def test_openrouter_base_url_resolves_openrouter_key(self):
        os.environ["OPENROUTER_API_KEY"] = "or-key"
        os.environ["CBORG_API_KEY"] = "cborg-key"
        self.assertEqual(resolve_provider_api_key("https://openrouter.ai/api/v1"), "or-key")

    def test_cborg_base_url_resolves_cborg_key(self):
        os.environ["OPENROUTER_API_KEY"] = "or-key"
        os.environ["CBORG_API_KEY"] = "cborg-key"
        self.assertEqual(resolve_provider_api_key("https://api.cborg.lbl.gov"), "cborg-key")

    def test_unrecognized_base_url_raises_immediately(self):
        """
        Regression test: an old config pointing at the previously-shipped
        default (api.openai.com) must fail fast and clearly, not silently
        resolve to None (which either surfaces as a misleading "no API key"
        error several frames away, or — worse — silently works anyway
        because the underlying provider SDK falls back to OPENAI_API_KEY on
        its own, reintroducing exactly the cross-provider key mixing this
        single-provider design exists to prevent).
        """
        os.environ["OPENAI_API_KEY"] = "sk-real-openai-key"
        with self.assertRaises(ValueError) as ctx:
            resolve_provider_api_key("https://api.openai.com/v1")
        message = str(ctx.exception)
        self.assertIn("api.openai.com", message)
        self.assertIn("OpenRouter", message)
        self.assertIn("CBORG", message)

    def test_unrecognized_base_url_raises_even_with_openai_key_set(self):
        """An OPENAI_API_KEY in the environment must not mask the error."""
        os.environ["OPENAI_API_KEY"] = "sk-real-openai-key"
        with self.assertRaises(ValueError):
            resolve_provider_api_key("https://api.openai.com/v1")


if __name__ == "__main__":
    unittest.main()
