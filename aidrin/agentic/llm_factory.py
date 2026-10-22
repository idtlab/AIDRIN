"""
Lightweight chat LLM factory with optional provider flexibility.

The agentic pipeline is designed around a single OpenAI-compatible provider per
run — OpenRouter or LBL CBORG, configured once via ``llm.base_url`` — rather than
mixing providers across pipeline stages. ``create_chat_model`` just builds a
client for whatever ``base_url``/``api_key``/``model`` it's given; the single-
provider-per-run resolution of which API key belongs to which base_url lives in
``resolve_provider_api_key`` below.

Usage:
    llm = create_chat_model(model_name="openai/gpt-oss-120b", api_key=key, base_url=base_url, temperature=0)
"""

from __future__ import annotations

import os
from typing import Any


def resolve_provider_api_key(base_url: str | None, explicit: str | None = None) -> str | None:
    """
    Resolve the API key for a single-provider setup where every pipeline stage
    shares one ``llm.base_url`` (either OpenRouter or LBL CBORG — no mixing).

    An explicit key (e.g. ``llm.api_key`` from config) always wins. Otherwise the
    right environment variable is inferred from which provider ``base_url``
    points at — ``OPENROUTER_API_KEY`` for OpenRouter, ``CBORG_API_KEY`` for
    CBORG — so a stray key for the *other* provider sitting in the environment
    never gets used by mistake.

    Returns None (not an error) when base_url itself is unset — some callers
    legitimately construct without one. But a base_url that *is* set to
    anything other than OpenRouter/CBORG (e.g. an old config still pointing at
    api.openai.com — this pipeline dropped built-in OpenAI support) raises
    immediately with a clear, actionable message, rather than silently
    returning None here and surfacing as either a confusing "no API key"
    error several frames away, or — worse — silently working anyway because
    the underlying provider SDK falls back to OPENAI_API_KEY on its own when
    no key is passed, which is exactly the cross-provider mixing this
    single-provider design exists to prevent.
    """
    if explicit:
        return explicit
    if not base_url:
        return None
    lowered = base_url.lower()
    if "openrouter" in lowered:
        return os.environ.get("OPENROUTER_API_KEY")
    if "cborg" in lowered:
        return os.environ.get("CBORG_API_KEY")
    raise ValueError(
        f"llm.base_url {base_url!r} is not a supported provider. This pipeline only "
        "supports OpenRouter (https://openrouter.ai/api/v1) or LBL CBORG "
        "(https://api.cborg.lbl.gov) — point llm.base_url at one of those. "
        "Direct OpenAI/Google endpoints are no longer supported."
    )


class _ResponsesWrapper:
    """
    Minimal wrapper to expose an .invoke([...]) API for models that require
    the OpenAI `responses` endpoint (e.g., gpt-5.2, gpt-5-codex).
    """

    def __init__(
        self,
        model: str,
        api_key: str | None,
        temperature: float,
        base_url: str | None = None,
        component: str = "unknown",
    ) -> None:
        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:
            raise ImportError("openai>=1.6.0 is required for responses models (gpt-5.x/codex).") from exc
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model
        self.temperature = temperature
        self.component = component

    def invoke(self, messages: list[tuple[str, str]]) -> Any:
        prompt = "\n".join(f"{role}: {content}" for role, content in messages)
        resp = self.client.responses.create(
            model=self.model,
            input=prompt,
            temperature=self.temperature,
        )

        try:
            from aidrin.agentic.token_tracker import get_tracker
            usage = getattr(resp, "usage", None)
            if usage is not None:
                get_tracker().record_chat(
                    self.model,
                    int(getattr(usage, "input_tokens", 0)),
                    int(getattr(usage, "output_tokens", 0)),
                    component=self.component,
                )
        except Exception:
            pass

        class _Resp:
            def __init__(self, text: str) -> None:
                self.content = text

        try:
            text = resp.output[0].content[0].text
        except Exception:
            try:
                text = resp.output_text
            except Exception:
                text = str(resp)
        return _Resp(text)


class _TrackingWrapper:
    """Wraps a LangChain chat model to record token usage after each invoke."""

    def __init__(self, llm: Any, model_name: str, component: str = "unknown") -> None:
        self._llm = llm
        self._model_name = model_name
        self._component = component

    def invoke(self, messages: Any) -> Any:
        resp = self._llm.invoke(messages)
        try:
            from aidrin.agentic.token_tracker import get_tracker
            tracker = get_tracker()
            usage = getattr(resp, "usage_metadata", None)
            if usage:
                tracker.record_chat(
                    self._model_name,
                    int(usage.get("input_tokens", 0)),
                    int(usage.get("output_tokens", 0)),
                    component=self._component,
                )
            else:
                token_usage = getattr(resp, "response_metadata", {}).get("token_usage", {})
                if token_usage:
                    tracker.record_chat(
                        self._model_name,
                        int(token_usage.get("prompt_tokens", 0)),
                        int(token_usage.get("completion_tokens", 0)),
                        component=self._component,
                    )
        except Exception:
            pass
        return resp

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)


def create_chat_model(
    model_name: str,
    *,
    api_key: str | None = None,
    temperature: float = 0.0,
    base_url: str | None = None,
    component: str = "unknown",
) -> Any:
    """
    Create a chat model client that works across providers when possible.

    component: which pipeline stage this model instance belongs to (e.g.
    "generation", "context_compression", "execution", "remediation",
    "complexity_scorer"), tagged onto every token_tracker record_chat() call
    made through it — see aidrin/agentic/token_tracker.py's per-component breakdown.

    When ``base_url`` is provided the client targets that OpenAI-compatible endpoint
    (OpenRouter or LBL CBORG — see resolve_provider_api_key) using ChatOpenAI directly,
    with no fallback to any other endpoint: falling back to plain OpenAI on a request
    failure would silently resend the OpenRouter/CBORG key to api.openai.com, exactly
    the cross-provider key mixing this single-provider design exists to prevent. A
    request failure propagates normally instead, for the caller's own retry logic
    (e.g. CodeExecutor's self-healing loop) to handle.

    Otherwise tries, in order:
    1) ChatLiteLLM (langchain_community) for broad provider support.
    2) ChatOpenAI for OpenAI models.
    Raises ImportError if neither path is available.
    """
    if any(x in model_name.lower() for x in ["gpt-5", "codex"]):
        return _ResponsesWrapper(
            model=model_name, api_key=api_key, temperature=temperature, base_url=base_url, component=component
        )

    if base_url:
        try:
            from langchain_openai import ChatOpenAI
            return _TrackingWrapper(
                ChatOpenAI(model=model_name, temperature=temperature, api_key=api_key, base_url=base_url),
                model_name,
                component,
            )
        except ImportError as exc:
            raise ImportError("langchain-openai is required for custom base_url endpoints.") from exc

    try:
        import litellm  # type: ignore
        litellm.drop_params = True
    except Exception:
        pass
    is_claude = model_name.lower().startswith("claude")
    # Claude 4.6+ models reject an explicit temperature/top_p/top_k — steering is
    # done via prompting instead, so only pass it through for providers that
    # still accept it.
    try:
        from langchain_litellm import ChatLiteLLM  # type: ignore
        llm_model = f"anthropic/{model_name}" if is_claude else model_name
        kwargs: dict[str, Any] = {"model": llm_model, "api_key": api_key}
        if not is_claude:
            kwargs["temperature"] = temperature
        return _TrackingWrapper(ChatLiteLLM(**kwargs), llm_model, component)
    except ImportError:
        pass
    try:
        from langchain_community.chat_models import ChatLiteLLM  # type: ignore
        llm_model = f"anthropic/{model_name}" if is_claude else model_name
        kwargs = {"model": llm_model, "api_key": api_key}
        if not is_claude:
            kwargs["temperature"] = temperature
        return _TrackingWrapper(ChatLiteLLM(**kwargs), llm_model, component)
    except Exception:
        pass

    try:
        from langchain_openai import ChatOpenAI
        return _TrackingWrapper(
            ChatOpenAI(model=model_name, temperature=temperature, api_key=api_key), model_name, component
        )
    except Exception as exc:
        raise ImportError(
            "No compatible chat model client found. Install `langchain-openai` for OpenAI "
            "or `langchain-community` with litellm support for other providers."
        ) from exc
