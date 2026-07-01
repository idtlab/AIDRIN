"""
QueryComplexityScorer: rates how hard a data readiness query is for a data preparer.

Scores three dimensions (each 0.0–1.0, LLM-assigned):

- ``profile_score``  — how much the data profile contributed to answering the query
- ``domain_score``   — how much retrieved domain knowledge contributed
- ``code_score``     — complexity of the generated code

``overall_score`` is a weighted sum (0.2 × profile + 0.5 × domain + 0.3 × code).
``query_class``: ``"easy"`` < 0.35, ``"moderate"`` < 0.65, ``"hard"`` ≥ 0.65.

Optional config section (falls back to retrieval.answer_model if absent):

.. code-block:: yaml

    complexity_scorer:
      enabled: true
      model: gpt-4o
      openai_api_key: null
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from aidrin.agentic.llm_factory import create_chat_model


_SYSTEM_PROMPT = (
    "You are an expert evaluator for data readiness assessment pipelines. "
    "All queries in this system concern evaluating whether a dataset is fit for AI use — "
    "covering multiple dimensions such as data quality, understandability and usability, "
    "fitness for a specific AI task, fairness and bias, data governance, data structure, etc. "
    "You receive a query together with the retrieval context, generated plan, and code produced "
    "by an automated pipeline. Score the query complexity as it would appear to a *data readiness "
    "analyst* — someone who understands both data quality assessment and domain regulatory "
    "requirements, but relies on an automated pipeline for computation.\n\n"

    "Score each dimension from 0.0 to 1.0 using the anchors below. "
    "Anchors at 0.0 / 0.25 / 0.5 / 0.75 / 1.0 — interpolate for in-between cases.\n\n"

    "--- profile_score ---\n"
    "How much did the DATA PROFILE (column stats, distributions, null rates, value ranges) "
    "contribute to answering this query — beyond merely confirming column names exist?\n"
    "  0.00 — profile is completely irrelevant: query is conceptual or definitional.\n"
    "  0.25 — profile only confirms schema: column presence, data type, or category list.\n"
    "  0.50 — profile provides contextual support: summary statistics inform strategy.\n"
    "  0.75 — profile supplies computation-critical values used directly in the answer.\n"
    "  1.00 — profile alone is sufficient without code execution or external knowledge.\n\n"

    "--- domain_score ---\n"
    "How much did RETRIEVED EXTERNAL KNOWLEDGE contribute?\n"
    "  0.00 — no external knowledge needed; entirely derivable from data.\n"
    "  0.25 — background context only; query could be answered without it.\n"
    "  0.50 — domain knowledge meaningfully guides methodology or interpretation.\n"
    "  0.75 — external knowledge provides specific values or thresholds directly applied.\n"
    "  1.00 — without retrieved context the question literally cannot be answered.\n\n"

    "--- code_score ---\n"
    "How complex was the CODE required to compute the answer?\n"
    "  0.00 — hard-coded return: code echoes retrieved text or a profile-derived constant.\n"
    "  0.25 — single-step operation: one filter, one aggregation, or one type cast.\n"
    "  0.50 — multi-step standard pipeline: coerce + transform + aggregate.\n"
    "  0.75 — complex operations: self-joins, window functions, or custom metric computation.\n"
    "  1.00 — iterative or recursive data readiness logic.\n\n"

    "primary_knowledge_source — pick what primarily drove the answer:\n"
    "  'profile' | 'domain' | 'both' | 'code_execution'\n\n"

    "Return strict JSON only, no code fences, with these keys:\n"
    "  profile_score (float 0.0-1.0), domain_score (float 0.0-1.0), "
    "code_score (float 0.0-1.0),\n"
    "  primary_knowledge_source (string),\n"
    "  reasoning (object with keys: profile, domain, code — each a one-sentence string)."
)

_PROFILE_CHARS = 3000
_CONTEXT_CHARS = 2000
_CODE_CHARS = 2000

_WEIGHTS = {"profile": 0.2, "domain": 0.5, "code": 0.3}
_THRESHOLDS = {"easy": 0.35, "moderate": 0.65}


class QueryComplexityScorer:
    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)
        cfg = self._load_config(self.config_path)
        self.enabled: bool = cfg["enabled"]
        self.model: str = cfg["model"]
        self.api_key: str | None = cfg["api_key"]
        self.base_url: str | None = cfg["base_url"]
        self._llm: Any = None

    def score(
        self,
        retrieval_result: dict[str, Any],
        profile_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Score query complexity using the retriever output dict as evidence."""
        if not self.enabled:
            return {"enabled": False, "message": "Complexity scorer disabled in config."}

        query = retrieval_result.get("query", "")
        code = retrieval_result.get("code", "") or ""
        plan_steps = retrieval_result.get("plan_steps") or []
        reasoning_strategy = retrieval_result.get("reasoning_strategy") or []
        assumptions = retrieval_result.get("assumptions") or []
        prompt_context = retrieval_result.get("prompt_context", "") or ""
        retrieved = retrieval_result.get("retrieved", []) or []
        retrieval_enabled = retrieval_result.get("enabled", False)

        profile_text = self._serialise(profile_summary)[:_PROFILE_CHARS] if profile_summary else "(not provided)"
        source_names = [item.get("source", "unknown") for item in retrieved]

        human_msg = "\n\n".join([
            f"Query: {query}",
            f"Retrieval used: {retrieval_enabled}",
            f"Retrieved sources: {source_names if source_names else 'none'}",
            f"Reasoning strategy:\n{self._serialise(reasoning_strategy)}",
            f"Plan steps:\n{self._serialise(plan_steps)}",
            f"Assumptions:\n{self._serialise(assumptions)}",
            f"Generated code (first {_CODE_CHARS} chars):\n{code[:_CODE_CHARS] or '(none)'}",
            f"Data profile summary (first {_PROFILE_CHARS} chars):\n{profile_text}",
            f"Retrieved context (first {_CONTEXT_CHARS} chars):\n{prompt_context[:_CONTEXT_CHARS] or '(none)'}",
            "Return complexity scores as JSON.",
        ])

        llm = self._get_llm()
        try:
            resp = llm.invoke([("system", _SYSTEM_PROMPT), ("human", human_msg)])
            content = getattr(resp, "content", str(resp)).strip()
            content = self._strip_fence(content)
            scores = json.loads(content)
        except Exception as exc:
            return {"enabled": True, "error": f"Scoring failed: {exc}", "query": query}

        profile_score = scores.get("profile_score") or 0.0
        domain_score = scores.get("domain_score") or 0.0
        code_score = scores.get("code_score") or 0.0
        overall_score = round(
            _WEIGHTS["profile"] * profile_score
            + _WEIGHTS["domain"] * domain_score
            + _WEIGHTS["code"] * code_score,
            2,
        )
        if overall_score < _THRESHOLDS["easy"]:
            query_class = "easy"
        elif overall_score < _THRESHOLDS["moderate"]:
            query_class = "moderate"
        else:
            query_class = "hard"

        return {
            "enabled": True,
            "query": query,
            "query_class": query_class,
            "overall_score": overall_score,
            "profile_score": profile_score,
            "domain_score": domain_score,
            "code_score": code_score,
            "primary_knowledge_source": scores.get("primary_knowledge_source"),
            "reasoning": scores.get("reasoning", {}),
        }

    def _get_llm(self) -> Any:
        if self._llm is None:
            api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
            self._llm = create_chat_model(self.model, api_key=api_key, temperature=0, base_url=self.base_url)
        return self._llm

    def _load_config(self, config_path: Path) -> dict[str, Any]:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        scorer_cfg = raw.get("complexity_scorer", {}) or {}
        retrieval_cfg = raw.get("retrieval", {}) or {}
        llm_cfg = raw.get("llm", {}) or {}
        enabled = bool(scorer_cfg.get("enabled", True))
        model = scorer_cfg.get("model") or retrieval_cfg.get("answer_model", "gpt-4o")
        api_key = (
            scorer_cfg.get("openai_api_key")
            or retrieval_cfg.get("openai_api_key")
            or llm_cfg.get("api_key")
            or os.environ.get("OPENAI_API_KEY")
        )
        base_url = llm_cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL")
        return {"enabled": enabled, "model": model, "api_key": api_key, "base_url": base_url}

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
