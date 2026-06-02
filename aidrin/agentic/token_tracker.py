"""Thread-safe token usage accumulator shared across all LLM calls in a run."""

from __future__ import annotations

import threading
from typing import Any


class TokenUsageTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reset_state()

    def reset(self) -> None:
        with self._lock:
            self._reset_state()

    def _reset_state(self) -> None:
        self.chat_calls = 0
        self.chat_input_tokens = 0
        self.chat_output_tokens = 0
        self.embedding_calls = 0
        self.embedding_tokens = 0
        self.embedding_chars = 0
        self._chat_models: dict[str, dict[str, int]] = {}
        self._embedding_models: dict[str, dict[str, Any]] = {}

    def record_chat(self, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.chat_calls += 1
            self.chat_input_tokens += input_tokens
            self.chat_output_tokens += output_tokens
            entry = self._chat_models.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            entry["calls"] += 1
            entry["input_tokens"] += input_tokens
            entry["output_tokens"] += output_tokens

    def record_embedding(self, model: str, tokens: int, chars: int, tokens_unreported: bool = False) -> None:
        with self._lock:
            self.embedding_calls += 1
            self.embedding_tokens += tokens
            self.embedding_chars += chars
            entry = self._embedding_models.setdefault(model, {"calls": 0, "tokens": 0, "chars": 0})
            entry["calls"] += 1
            entry["tokens"] += tokens
            entry["chars"] += chars
            if tokens_unreported:
                entry["tokens_unreported"] = True

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "chat_calls": self.chat_calls,
                "chat_input_tokens": self.chat_input_tokens,
                "chat_output_tokens": self.chat_output_tokens,
                "chat_total_tokens": self.chat_input_tokens + self.chat_output_tokens,
                "embedding_calls": self.embedding_calls,
                "embedding_tokens": self.embedding_tokens,
                "embedding_chars": self.embedding_chars,
                "models": {
                    "chat": dict(self._chat_models),
                    "embedding": dict(self._embedding_models),
                },
            }


_tracker = TokenUsageTracker()


def get_tracker() -> TokenUsageTracker:
    return _tracker
