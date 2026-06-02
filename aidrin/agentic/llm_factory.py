"""
Lightweight chat LLM factory with optional provider flexibility.

Supports:
- OpenAI Chat models via langchain-openai (gpt-4o, gpt-3.5, etc.)
- Any model supported by litellm through langchain_community ChatLiteLLM (e.g., Anthropic, Llama, Qwen, Mistral)

Usage:
    llm = create_chat_model(model_name="gpt-4o", api_key=None, temperature=0)

If ChatLiteLLM is available it is used first for broad provider coverage; otherwise
it falls back to ChatOpenAI for OpenAI models.
"""

from __future__ import annotations

from typing import Any


class _ResponsesWrapper:
    """
    Minimal wrapper to expose an .invoke([...]) API for models that require
    the OpenAI `responses` endpoint (e.g., gpt-5.2, gpt-5-codex).
    """

    def __init__(self, model: str, api_key: str | None, temperature: float, base_url: str | None = None) -> None:
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


class _FallbackWrapper:
    """Tries a primary LLM; falls back to standard OpenAI on any invoke failure."""

    def __init__(self, primary: Any, fallback: Any) -> None:
        self._primary = primary
        self._fallback = fallback
        self._use_fallback = False

    def invoke(self, messages: Any) -> Any:
        if self._use_fallback:
            return self._fallback.invoke(messages)
        try:
            return self._primary.invoke(messages)
        except Exception as exc:
            import sys
            sys.stderr.write(f"[aidrin] Custom endpoint failed ({exc}); falling back to OpenAI API.\n")
            self._use_fallback = True
            return self._fallback.invoke(messages)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._primary, name)


class _TrackingWrapper:
    """Wraps a LangChain chat model to record token usage after each invoke."""

    def __init__(self, llm: Any, model_name: str) -> None:
        self._llm = llm
        self._model_name = model_name

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
                )
            else:
                token_usage = getattr(resp, "response_metadata", {}).get("token_usage", {})
                if token_usage:
                    tracker.record_chat(
                        self._model_name,
                        int(token_usage.get("prompt_tokens", 0)),
                        int(token_usage.get("completion_tokens", 0)),
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
) -> Any:
    """
    Create a chat model client that works across providers when possible.

    When ``base_url`` is provided the client targets that OpenAI-compatible endpoint
    (e.g. LBL CBORG at https://api.cborg.lbl.gov) using ChatOpenAI directly.

    Otherwise tries, in order:
    1) ChatLiteLLM (langchain_community) for broad provider support.
    2) ChatOpenAI for OpenAI models.
    Raises ImportError if neither path is available.
    """
    if any(x in model_name.lower() for x in ["gpt-5", "codex"]):
        return _ResponsesWrapper(model=model_name, api_key=api_key, temperature=temperature, base_url=base_url)

    # Custom OpenAI-compatible endpoint (CBORG, science clouds, local servers, etc.)
    # Falls back to the standard OpenAI API if the custom endpoint fails.
    if base_url:
        try:
            from langchain_openai import ChatOpenAI
            primary = _TrackingWrapper(
                ChatOpenAI(model=model_name, temperature=temperature, api_key=api_key, base_url=base_url),
                model_name,
            )
            fallback = _TrackingWrapper(
                ChatOpenAI(model=model_name, temperature=temperature, api_key=api_key),
                model_name,
            )
            return _FallbackWrapper(primary, fallback)
        except ImportError as exc:
            raise ImportError("langchain-openai is required for custom base_url endpoints.") from exc

    try:
        import litellm  # type: ignore
        litellm.drop_params = True
    except Exception:
        pass
    try:
        from langchain_litellm import ChatLiteLLM  # type: ignore
        llm_model = model_name
        if model_name.lower().startswith("claude"):
            llm_model = f"anthropic/{model_name}"
        return _TrackingWrapper(ChatLiteLLM(model=llm_model, temperature=temperature, api_key=api_key), llm_model)
    except ImportError:
        pass
    try:
        from langchain_community.chat_models import ChatLiteLLM  # type: ignore
        llm_model = model_name
        if model_name.lower().startswith("claude"):
            llm_model = f"anthropic/{model_name}"
        return _TrackingWrapper(ChatLiteLLM(model=llm_model, temperature=temperature, api_key=api_key), llm_model)
    except Exception:
        pass

    try:
        from langchain_openai import ChatOpenAI
        return _TrackingWrapper(ChatOpenAI(model=model_name, temperature=temperature, api_key=api_key), model_name)
    except Exception as exc:
        raise ImportError(
            "No compatible chat model client found. Install `langchain-openai` for OpenAI "
            "or `langchain-community` with litellm support for other providers."
        ) from exc
