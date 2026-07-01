"""
VectorRetriever: loads a built vector store, runs a similarity search for a query from YAML,
and formats a prompt context for the answer LLM.

Config expects a ``retrieval`` section:

.. code-block:: yaml

    retrieval:
      enabled: true
      question: "What does the dataset cover?"
      top_k: 3
      vector_store_name: my_vector_store   # name of directory under project root
      embedding_model: text-embedding-3-small
      answer_model: gpt-4o
      openai_api_key: null   # falls back to OPENAI_API_KEY env var

Requires: langchain-openai, faiss-cpu (optional, falls back to brute-force cosine search).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import yaml

try:
    import faiss  # type: ignore
except Exception:
    faiss = None

try:
    from langchain_openai import OpenAIEmbeddings
except ImportError as exc:
    raise ImportError(
        "langchain-openai is required. Install with: pip install 'aidrin[agentic]'"
    ) from exc

try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
except ImportError:
    GoogleGenerativeAIEmbeddings = None  # type: ignore

from aidrin.agentic.llm_factory import create_chat_model


def _make_embeddings(
    model_name: str,
    openai_api_key: str | None = None,
    google_api_key: str | None = None,
    base_url: str | None = None,
):
    if "gemini" in model_name or "embedding-001" in model_name:
        if GoogleGenerativeAIEmbeddings is None:
            raise ImportError(
                "langchain-google-genai is required for Gemini embeddings. "
                "Install with: pip install langchain-google-genai"
            )
        kwargs: dict[str, Any] = {"model": model_name}
        if google_api_key:
            kwargs["google_api_key"] = google_api_key
        return GoogleGenerativeAIEmbeddings(**kwargs)

    kwargs: dict[str, Any] = {"model": model_name}
    if openai_api_key:
        kwargs["api_key"] = openai_api_key
    if base_url:
        kwargs["base_url"] = base_url
    model = OpenAIEmbeddings(**kwargs)
    if not base_url:
        return model

    # Wrap with fallback to standard OpenAI when a custom endpoint is configured.
    fallback_kwargs: dict[str, Any] = {"model": model_name}
    if openai_api_key:
        fallback_kwargs["api_key"] = openai_api_key
    fallback = OpenAIEmbeddings(**fallback_kwargs)

    import sys as _sys

    class _FallbackEmbeddings:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            try:
                return model.embed_documents(texts)
            except Exception as exc:
                _sys.stderr.write(f"[aidrin] Embedding via custom endpoint failed ({exc}); falling back to OpenAI API.\n")
                return fallback.embed_documents(texts)

        def embed_query(self, text: str) -> list[float]:
            try:
                return model.embed_query(text)
            except Exception as exc:
                _sys.stderr.write(f"[aidrin] Embedding via custom endpoint failed ({exc}); falling back to OpenAI API.\n")
                return fallback.embed_query(text)

    return _FallbackEmbeddings()


class VectorRetriever:
    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)
        cfg = self._load_config(self.config_path)
        self.enabled = cfg["enabled"]
        self.question = cfg["question"]
        self.top_k = cfg["top_k"]
        self.vector_dir = cfg["vector_store_dir"]
        self.embedding_model = cfg["embedding_model"]
        self.api_key = cfg["openai_api_key"]
        self.google_api_key = cfg["google_api_key"]
        self.base_url = cfg["base_url"]
        self.answer_model = cfg["answer_model"]
        self.preview_chars = cfg["preview_chars"]
        self.context_compression = cfg["context_compression"]
        self.metadata_path = self.vector_dir / "metadata.json"
        self.embeddings_path = self.vector_dir / "embeddings.npy"
        self.index_path = self.vector_dir / "index.faiss"

    def _load_config(self, config_path: Path) -> dict[str, Any]:
        with config_path.open("r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        retrieval_cfg = cfg.get("retrieval", {}) or {}
        vector_store_cfg = cfg.get("vector_store", {}) or {}
        enabled = bool(retrieval_cfg.get("enabled", False))
        question = retrieval_cfg.get("question", "")
        top_k = int(retrieval_cfg.get("top_k", 3))

        store_name = (
            retrieval_cfg.get("vector_store_name")
            or vector_store_cfg.get("vector_store_name", "vector_store")
        )
        base = config_path.parent
        default_dir = (base.parent / store_name).resolve()
        vector_dir_raw = retrieval_cfg.get("vector_store_dir", default_dir)
        if Path(vector_dir_raw).is_absolute():
            vector_dir = Path(vector_dir_raw)
        else:
            candidate1 = (base / vector_dir_raw).resolve()
            candidate2 = (base.parent / vector_dir_raw).resolve()
            vector_dir = candidate1 if candidate1.exists() else candidate2

        embedding_model = (
            retrieval_cfg.get("embedding_model")
            or vector_store_cfg.get("embedding_model", "text-embedding-3-small")
        )
        llm_cfg = cfg.get("llm", {}) or {}
        openai_api_key = (
            retrieval_cfg.get("openai_api_key")
            or llm_cfg.get("api_key")
            or os.environ.get("OPENAI_API_KEY")
        )
        google_api_key = retrieval_cfg.get("google_api_key") or os.environ.get("GOOGLE_API_KEY")
        base_url = llm_cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL")
        answer_model = retrieval_cfg.get("answer_model", "gpt-4o")
        preview_chars = int(retrieval_cfg.get("preview_chars", 500))
        context_compression = bool(retrieval_cfg.get("context_compression", False))

        return {
            "enabled": enabled,
            "question": question,
            "top_k": top_k,
            "vector_store_dir": vector_dir,
            "embedding_model": embedding_model,
            "openai_api_key": openai_api_key,
            "google_api_key": google_api_key,
            "base_url": base_url,
            "answer_model": answer_model,
            "preview_chars": preview_chars,
            "context_compression": context_compression,
        }

    def _load_store(self) -> tuple[np.ndarray, list[dict[str, Any]]]:
        if not self.embeddings_path.exists() or not self.metadata_path.exists():
            raise FileNotFoundError(f"Vector store not found under {self.vector_dir}")
        embeddings = np.load(self.embeddings_path)
        raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            stored_model = raw.get("embedding_model")
            if stored_model and stored_model != self.embedding_model:
                raise ValueError(
                    f"Embedding model mismatch: the store was built with '{stored_model}' "
                    f"but the config specifies '{self.embedding_model}'. "
                    "Delete the store directory and rebuild with the new model."
                )
            metadata = raw.get("chunks", [])
        else:
            metadata = raw
        return embeddings, metadata

    def _embed_query(self, text: str) -> np.ndarray:
        is_gemini = "gemini" in self.embedding_model or "embedding-001" in self.embedding_model
        if is_gemini:
            if not (self.google_api_key or "GOOGLE_API_KEY" in os.environ):
                raise ValueError("Google API key missing. Set GOOGLE_API_KEY or retrieval.google_api_key in config.")
        elif not (self.api_key or "OPENAI_API_KEY" in os.environ):
            raise ValueError("OpenAI API key missing. Set OPENAI_API_KEY or retrieval.openai_api_key in config.")
        model = _make_embeddings(self.embedding_model, self.api_key, self.google_api_key, self.base_url)
        vec = model.embed_query(text)
        try:
            from aidrin.agentic.token_tracker import get_tracker
            get_tracker().record_embedding(self.embedding_model, tokens=0, chars=len(text), tokens_unreported=True)
        except Exception:
            pass
        return np.array(vec, dtype="float32")

    def _search(self, query_vec: np.ndarray, embeddings: np.ndarray, top_k: int) -> list[int]:
        if faiss and self.index_path.exists():
            index = faiss.read_index(str(self.index_path))
            _, idxs = index.search(query_vec.reshape(1, -1), top_k)
            return list(idxs[0])
        norms = np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query_vec)
        sims = embeddings @ query_vec / (norms + 1e-10)
        top = np.argsort(-sims)[:top_k]
        return list(top)

    def retrieve(self, profile_summary: dict[str, Any] | None = None, question: str | None = None) -> dict[str, Any]:
        api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
        llm = create_chat_model(self.answer_model, api_key=api_key, temperature=0, base_url=self.base_url)

        question = question or self.question

        profile_text = ""
        if profile_summary:
            try:
                profile_text = json.dumps(profile_summary, ensure_ascii=False)
            except Exception:
                profile_text = str(profile_summary)
        profile_text = self._sanitize(profile_text)

        if not self.enabled:
            resp = llm.invoke(
                [
                    (
                        "system",
                        "You are a concise assistant. Prefer JSON with keys: reasoning_strategy (list), plan_steps (list), "
                        "code (string), assumptions (list). The code must set a variable named result to the final answer "
                        "using pandas/numpy only and the already-loaded dataframe `df` (do not re-read files). "
                        "If you cannot return JSON, return just the Python code that sets result. "
                        "No prints or extra text.",
                    ),
                    (
                        "human",
                        f"Question: {question}\n\nProfile Summary:\n{profile_text}\n\nReturn JSON if possible; otherwise return only the code.",
                    ),
                ]
            )
            answer_raw = resp.content if hasattr(resp, "content") else str(resp)
            answer = self._sanitize(answer_raw)
            structured = self._to_structured(answer)
            if not structured.get("code") or "LLM failed to supply code" in str(structured.get("code", "")):
                structured = self._regenerate_plan(
                    llm,
                    question=question,
                    profile_summary=profile_summary,
                    prompt_context=profile_text,
                )
            return {
                "enabled": False,
                "message": "Retrieval disabled; plan generated from LLM knowledge and profiling summary.",
                "query": question,
                **structured,
                "profile_used": bool(profile_summary),
            }

        embeddings, metadata = self._load_store()
        query_vec = self._embed_query(question)
        idxs = self._search(query_vec, embeddings, self.top_k)

        retrieved = []
        for i in idxs:
            if i < len(metadata):
                item = dict(metadata[i])
                raw = item.get("text", "") or item.get("full_text", "") or ""
                text = self._sanitize(raw)
                item["full_text"] = text
                item["preview"] = text[: self.preview_chars] if text.strip() else "(no text extracted for this chunk)"
                retrieved.append(item)

        if self.context_compression:
            def _compress_one(item: dict[str, Any]) -> str:
                resp = llm.invoke([
                    (
                        "system",
                        "Given the following question and context, extract any part of the context "
                        "*AS IS* that is relevant to answer the question. "
                        "If none of the context is relevant return NO_OUTPUT.",
                    ),
                    (
                        "human",
                        f"Question: {question}\n\nContext:\n{item['full_text']}\n\nExtracted relevant parts:",
                    ),
                ])
                text = getattr(resp, "content", str(resp)).strip()
                return "" if text == "NO_OUTPUT" else text
            with ThreadPoolExecutor(max_workers=len(retrieved)) as pool:
                context_texts = list(pool.map(_compress_one, retrieved))
        else:
            context_texts = [item.get("full_text", "") for item in retrieved]

        prompt_context = "\n\n".join(
            f"[Source: {item.get('source','unknown')}]\n{self._sanitize(text)}"
            for item, text in zip(retrieved, context_texts)
        )

        resp = llm.invoke(
            [
                (
                    "system",
                    "You are a concise assistant. Use the provided context/profile AND the already-loaded dataframe `df` "
                    "to produce JSON with keys: reasoning_strategy (list), plan_steps (list), code (string), assumptions (list). "
                    "The code must directly compute the answer from `df` and assign it to variable result (scalar or JSON-serializable). "
                    "Do not re-read files. If you cannot return JSON, return only the Python code that sets result. "
                    "If required fields are missing, still produce code that best approximates the answer from `df` and state assumptions.",
                ),
                (
                    "human",
                    f"Question: {question}\n\nProfile Summary:\n{profile_text}\n\nContext:\n{prompt_context}\n\n"
                    "Return JSON if possible; otherwise return only the code.",
                ),
            ]
        )
        answer_raw = resp.content if hasattr(resp, "content") else str(resp)
        answer = self._sanitize(answer_raw)
        structured = self._to_structured(answer)

        if not structured.get("code") or "LLM failed to supply code" in str(structured.get("code", "")) or structured.get("parse_error"):
            structured = self._regenerate_plan(
                llm,
                question=question,
                profile_summary=profile_summary,
                prompt_context=prompt_context,
            )
            if not structured.get("code"):
                structured["code"] = self._auto_code_for_question(question)

        return {
            "enabled": True,
            "query": question,
            "retrieved": [{k: v for k, v in item.items() if k != "full_text"} for item in retrieved],
            "prompt_context": prompt_context,
            **structured,
            "profile_used": bool(profile_summary),
        }

    @staticmethod
    def _to_structured(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("` \n")
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return {
                    "reasoning_strategy": data.get("reasoning_strategy"),
                    "plan_steps": data.get("plan_steps"),
                    "code": data.get("code"),
                    "assumptions": data.get("assumptions"),
                }
        except Exception:
            pass

        if cleaned:
            return {
                "reasoning_strategy": None,
                "plan_steps": None,
                "code": cleaned,
                "assumptions": None,
                "parse_error": "Could not parse LLM JSON; treated content as code",
            }
        return {
            "reasoning_strategy": None,
            "plan_steps": None,
            "code": None,
            "assumptions": None,
            "parse_error": "Could not parse LLM JSON",
        }

    def _regenerate_plan(
        self,
        llm: Any,
        *,
        question: str,
        profile_summary: Any,
        prompt_context: str,
    ) -> dict[str, Any]:
        resp = llm.invoke(
            [
                (
                    "system",
                    "Return strict JSON only with keys: reasoning_strategy (list), plan_steps (list), "
                    "code (string of executable pandas/numpy Python using dataframe `df` and assigning the final answer to variable `result`), "
                    "assumptions (list). No extra text or code fences. Do not re-read files; assume df is loaded.",
                ),
                (
                    "human",
                    f"Question: {question}\n\nProfile Summary:\n{profile_summary}\n\nContext:\n{prompt_context}\n\n"
                    "Return JSON only.",
                ),
            ]
        )
        content = getattr(resp, "content", str(resp))
        structured = self._to_structured(self._sanitize(content))
        if not structured.get("code") or "LLM failed to supply code" in str(structured.get("code", "")):
            structured["code"] = self._synthesize_answer_code(
                llm,
                question=question,
                profile_summary=profile_summary,
                prompt_context=prompt_context,
            )
        return structured

    def _synthesize_answer_code(
        self,
        llm: Any,
        *,
        question: str,
        profile_summary: Any,
        prompt_context: str,
    ) -> str:
        try:
            resp = llm.invoke(
                [
                    (
                        "system",
                        "Answer the user's question concisely (2-3 sentences max). "
                        "Use only the provided context/profile; if unknown, say so briefly. "
                        "Return JSON with one key 'answer' containing the string answer.",
                    ),
                    (
                        "human",
                        f"Question: {question}\n\nProfile Summary:\n{profile_summary}\n\nContext:\n{prompt_context}\n\nReturn JSON only.",
                    ),
                ]
            )
            content = getattr(resp, "content", str(resp))
            as_text = self._sanitize(content)
            if "answer" in as_text:
                m = re.search(r'"answer"\s*:\s*"([^"]+)"', as_text)
                answer = m.group(1) if m else as_text
            else:
                answer = as_text
            return f'result = """{answer}"""'
        except Exception:
            return f"result = \"Unable to answer based on available context for: {question}\""

    def _auto_code_for_question(self, question: str) -> str:
        safe_q = question.replace('"', "'")
        return (
            "result = \"No executable plan was generated for this query. "
            f"Question: {safe_q}. Provide code or enable retrieval to answer.\""
        )

    @staticmethod
    def _sanitize(text: str) -> str:
        if not isinstance(text, str):
            return ""
        text = unicodedata.normalize("NFKD", text)
        for dash in ["‒", "–", "—", "―", "−"]:
            text = text.replace(dash, "-")
        text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return text
