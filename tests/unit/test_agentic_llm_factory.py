"""Unit tests for aidrin.agentic.llm_factory.

This pipeline intentionally supports exactly one LLM provider per run —
OpenRouter or LBL CBORG — with no fallback to a third provider (including the
previously-shipped default of plain OpenAI). TestResolveProviderApiKey covers
the key resolution contract: which env var wins for which base_url, that an
explicit key always wins, and that an unrecognized base_url (e.g. an old
config still pointing at api.openai.com) fails immediately with a clear
message instead of silently resolving to no key or silently falling back to
OPENAI_API_KEY. TestCreateChatModelNoFallback covers create_chat_model
itself: a request failure against the configured base_url must propagate,
never silently retry against plain OpenAI with the wrong key.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

try:
    import langchain_openai  # noqa: F401
    HAS_LANGCHAIN_OPENAI = True
except ImportError:
    HAS_LANGCHAIN_OPENAI = False

from aidrin.agentic.llm_factory import create_chat_model, resolve_provider_api_key


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


@unittest.skipUnless(HAS_LANGCHAIN_OPENAI, "langchain-openai not installed")
class TestCreateChatModelNoFallback(unittest.TestCase):
    """
    Regression tests: create_chat_model used to wrap a base_url-configured
    client in _FallbackWrapper, which retried any failed request against
    plain ChatOpenAI with no base_url — silently resending the OpenRouter/
    CBORG key to api.openai.com, and then pinning every subsequent call on
    that same instance to the broken fallback. _FallbackWrapper has been
    removed entirely: a request failure must now propagate normally, and
    exactly one ChatOpenAI client (targeting the configured base_url) must
    ever be constructed.
    """

    def test_only_one_chat_openai_instance_is_constructed(self):
        with patch("langchain_openai.ChatOpenAI") as mock_chat_openai:
            create_chat_model(
                "some-model", api_key="or-key", base_url="https://openrouter.ai/api/v1", temperature=0
            )
        self.assertEqual(mock_chat_openai.call_count, 1)
        _, kwargs = mock_chat_openai.call_args
        self.assertEqual(kwargs.get("api_key"), "or-key")
        self.assertEqual(kwargs.get("base_url"), "https://openrouter.ai/api/v1")

    def test_invoke_failure_propagates_instead_of_retrying_against_plain_openai(self):
        with patch("langchain_openai.ChatOpenAI") as mock_chat_openai:
            mock_chat_openai.return_value.invoke.side_effect = RuntimeError("endpoint unreachable")
            llm = create_chat_model(
                "some-model", api_key="or-key", base_url="https://openrouter.ai/api/v1", temperature=0
            )
            with self.assertRaises(RuntimeError):
                llm.invoke([("human", "hi")])
            # A second call must still hit the same (still-failing) configured
            # endpoint, not transparently succeed via a different one.
            with self.assertRaises(RuntimeError):
                llm.invoke([("human", "hi again")])
        # Only the one client aimed at the configured base_url was ever built —
        # no second, fallback ChatOpenAI instance targeting plain OpenAI.
        self.assertEqual(mock_chat_openai.call_count, 1)


if __name__ == "__main__":
    unittest.main()
