"""
RemediationGenerator: synthesises actionable remediation recommendations for
detected data readiness gaps, grounded in retrieved domain literature.

Optional config section (falls back to retrieval.answer_model if absent):

.. code-block:: yaml

    remediation:
      enabled: true
      model: gpt-4o
      openai_api_key: null
      context_chars: 3000
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from aidrin.agentic.llm_factory import create_chat_model


_CONTEXT_CHARS = 3000
_RESULT_CHARS = 1500

_SYSTEM_PROMPT = (
    "You are a data readiness remediation advisor. "
    "A data readiness assessment pipeline has evaluated a dataset against a specific query. "
    "You are given: (1) the query asked, (2) the finding from executing the assessment code "
    "over the actual dataset, and (3) authoritative domain documentation that was used to "
    "derive the expected outcome for this query.\n\n"
    "Your task is to produce concrete, actionable remediation recommendations that would "
    "help a data practitioner resolve the identified data readiness gap. "
    "Ground every recommendation in the same authoritative domain literature and documentation "
    "provided — cite the source when referencing a standard, threshold, or regulation. "
    "Recommendations must be operationally specific: name the column, code, threshold, or "
    "process step that needs to change. Avoid generic advice.\n\n"
    "Categorise each action using exactly one of: "
    "data_quality, compliance, feature_engineering, documentation, governance.\n\n"
    "Assign priority based on impact on dataset fitness for AI use:\n"
    "  high   — blocks model training or violates a mandatory standard\n"
    "  medium — degrades model performance or violates a recommended standard\n"
    "  low    — minor improvement or optional best practice\n\n"
    "Return strict JSON only, no code fences, with these keys:\n"
    "  recommended_actions: list of objects, each with:\n"
    "    action   (string — specific step to take),\n"
    "    rationale (string — reason, citing domain source where applicable),\n"
    "    priority  (high | medium | low),\n"
    "    category  (string from the list above).\n"
    "  domain_grounding: string — which domain sources informed these recommendations.\n"
    "  summary: string — 1-2 sentence overview of the primary gap and remediation path."
)


class RemediationGenerator:
    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)
        cfg = self._load_config(self.config_path)
        self.enabled: bool = cfg["enabled"]
        self.model: str = cfg["model"]
        self.api_key: str | None = cfg["api_key"]
        self.base_url: str | None = cfg["base_url"]
        self.context_chars: int = cfg["context_chars"]
        self._llm: Any = None

    def generate(self, query_result: dict[str, Any]) -> dict[str, Any]:
        """Generate remediation recommendations for a completed query result dict."""
        if not self.enabled:
            return {"enabled": False, "message": "Remediation generator disabled in config."}

        question = query_result.get("question", "")
        retrieval = query_result.get("retrieval") or {}
        execution = query_result.get("execution") or {}
        complexity = query_result.get("complexity") or {}

        if retrieval.get("error") or execution.get("error"):
            return {
                "enabled": True,
                "skipped": True,
                "reason": "Upstream retrieval or execution error; remediation skipped.",
            }

        prompt_context = (retrieval.get("prompt_context") or "")[:self.context_chars]
        exec_result = execution.get("result") or {}
        exec_answer = exec_result.get("answer", exec_result.get("preview", "(no result)"))
        exec_success = execution.get("success", False)
        query_class = complexity.get("query_class") or "unknown"
        primary_source = complexity.get("primary_knowledge_source") or "unknown"

        finding_text = "\n".join([
            f"Execution success: {exec_success}",
            f"Query complexity class: {query_class}",
            f"Primary knowledge source: {primary_source}",
            f"Finding / answer from data:\n{self._serialise(exec_answer)[:_RESULT_CHARS]}",
        ])

        human_msg = "\n\n".join([
            f"Data readiness query: {question}",
            f"Assessment finding:\n{finding_text}",
            (
                f"Domain literature context (same sources used to derive expected outcome):\n{prompt_context}"
                if prompt_context
                else "Domain literature context: (no domain context retrieved)"
            ),
            "Produce remediation recommendations as JSON.",
        ])

        llm = self._get_llm()
        try:
            resp = llm.invoke([("system", _SYSTEM_PROMPT), ("human", human_msg)])
            content = getattr(resp, "content", str(resp)).strip()
            content = self._strip_fence(content)
            data = json.loads(content)
        except Exception as exc:
            return {"enabled": True, "error": f"Remediation generation failed: {exc}", "query": question}

        return {
            "enabled": True,
            "query": question,
            "summary": data.get("summary", ""),
            "domain_grounding": data.get("domain_grounding", ""),
            "recommended_actions": data.get("recommended_actions", []),
        }

    def _get_llm(self) -> Any:
        if self._llm is None:
            api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
            self._llm = create_chat_model(self.model, api_key=api_key, temperature=0, base_url=self.base_url)
        return self._llm

    def _load_config(self, config_path: Path) -> dict[str, Any]:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        rem_cfg = raw.get("remediation", {}) or {}
        retrieval_cfg = raw.get("retrieval", {}) or {}
        llm_cfg = raw.get("llm", {}) or {}
        enabled = bool(rem_cfg.get("enabled", True))
        model = rem_cfg.get("model") or retrieval_cfg.get("answer_model", "gpt-4o")
        api_key = (
            rem_cfg.get("openai_api_key")
            or retrieval_cfg.get("openai_api_key")
            or llm_cfg.get("api_key")
            or os.environ.get("OPENAI_API_KEY")
        )
        base_url = llm_cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL")
        context_chars = int(rem_cfg.get("context_chars", _CONTEXT_CHARS))
        return {
            "enabled": enabled,
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "context_chars": context_chars,
        }

    @staticmethod
    def _serialise(obj: Any) -> str:
        if obj is None:
            return ""
        if isinstance(obj, str):
            return obj
        try:
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return str(obj)

    @staticmethod
    def _strip_fence(text: str) -> str:
        if text.startswith("```"):
            text = text.strip("` \n")
            if text.startswith("json"):
                text = text[4:].lstrip()
        return text
