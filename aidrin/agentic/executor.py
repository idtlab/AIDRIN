"""
CodeExecutor: executes LLM-generated analysis code against a dataset,
with a self-healing loop that asks the LLM to repair failing code.

Config (YAML) expected keys:

.. code-block:: yaml

    executor:
      enabled: true
      max_attempts: 3
      model: gpt-4o-mini
      temperature: 0.0
      openai_api_key: null   # falls back to OPENAI_API_KEY env var
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import traceback
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

try:
    import numpy as np
except Exception:
    np = None

from aidrin.agentic.llm_factory import create_chat_model


class CodeExecutor:
    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)
        cfg = self._load_config(self.config_path)
        self.enabled: bool = cfg["enabled"]
        self.max_attempts: int = cfg["max_attempts"]
        self.model: str = cfg["model"]
        self.temperature: float = cfg["temperature"]
        self.api_key: str | None = cfg["openai_api_key"]
        self.base_url: str | None = cfg["base_url"]
        self.data_path: Path | None = cfg.get("data_path")
        self.data_loader_path: str | None = cfg.get("data_loader")

        api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
        self.llm = None
        if self.enabled:
            self.llm = create_chat_model(self.model, temperature=self.temperature, api_key=api_key, base_url=self.base_url)

    def run(self, retrieval_result: dict[str, Any] | None, profile_result: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute generated code with optional self-healing repairs."""
        if not self.enabled:
            return {"enabled": False, "message": "Executor disabled in config."}

        if not retrieval_result or not retrieval_result.get("code"):
            return {"enabled": True, "error": "No code provided for execution."}

        initial_code = self._sanitize(retrieval_result.get("code", ""))
        question = retrieval_result.get("query") or ""
        plan_steps = retrieval_result.get("plan_steps")
        prompt_context = retrieval_result.get("prompt_context")

        if self.data_loader_path:
            df = self._load_via_loader(self.data_loader_path)
        else:
            if not self.data_path or not self.data_path.exists():
                raise FileNotFoundError(f"Data file not found: {self.data_path}")
            df = pd.read_csv(self.data_path, low_memory=False)

        attempts: list[dict[str, Any]] = []
        code = initial_code
        last_error: str | None = None
        result_payload: dict[str, Any] = {}

        for attempt in range(1, self.max_attempts + 1):
            try:
                exec_result, exec_ns, before_keys, chosen_key = self._execute(code, df)
                result_payload = self._summarize(exec_result, exec_ns, before_keys, chosen_key)
                answer_value, answer_truncated = self._answer_value(exec_result)
                result_payload["answer"] = answer_value
                result_payload["answer_truncated"] = answer_truncated
                attempts.append({"attempt": attempt, "status": "success"})
                return {
                    "enabled": True,
                    "success": True,
                    "attempts": attempts,
                    "final_code": code,
                    "result": result_payload,
                }
            except Exception as exc:
                last_error = f"{exc}\n{traceback.format_exc()}"
                attempts.append({"attempt": attempt, "status": "error", "error": str(exc)})
                if attempt >= self.max_attempts:
                    break
                code = self._repair_code(
                    code=code,
                    error_text=last_error,
                    question=question,
                    plan_steps=plan_steps,
                    prompt_context=prompt_context,
                    profile_result=profile_result,
                    original_code=initial_code,
                )

        return {
            "enabled": True,
            "success": False,
            "attempts": attempts,
            "final_code": code,
            "last_error": last_error,
        }

    def _execute(self, code: str, df: pd.DataFrame) -> tuple[Any, dict[str, Any], set[str], str | None]:
        ns: dict[str, Any] = {"pd": pd, "df": df.copy(), "result": None}
        if np is not None:
            ns["np"] = np
        before_keys = set(ns.keys())
        exec(code, ns, ns)  # noqa: S102
        value, chosen_key = self._select_result(ns, before_keys)
        return value, ns, before_keys, chosen_key

    @staticmethod
    def _select_result(ns: dict[str, Any], before_keys: set[str]) -> tuple[Any, str | None]:
        priority = ("result", "answer", "output", "final", "response")
        summary_like = ("summary", "valid_summary", "report", "metrics", "table", "analysis")

        for key in priority:
            if key in ns and ns[key] is not None:
                return ns[key], key

        for key in summary_like:
            if key in ns and ns[key] is not None:
                return ns[key], key

        new_keys = [k for k in ns.keys() if k not in before_keys and not k.startswith("__")]
        for key in new_keys:
            if key in {"pd", "np", "df"}:
                continue
            val = ns.get(key)
            if isinstance(val, (pd.DataFrame, pd.Series)):
                return val, key
            if np is not None and isinstance(val, np.ndarray):
                return val, key

        for key in new_keys:
            if key in {"pd", "np", "df"}:
                continue
            val = ns.get(key)
            if val is not None:
                return val, key

        return ns.get("result"), "result"

    def _repair_code(
        self,
        *,
        code: str,
        error_text: str,
        question: str,
        plan_steps: Any,
        prompt_context: str | None,
        profile_result: dict[str, Any] | None,
        original_code: str,
    ) -> str:
        if not self.llm:
            return code

        profile_summary = ""
        if profile_result and profile_result.get("summary"):
            profile_summary = str(profile_result.get("summary"))

        messages = [
            (
                "system",
                "You repair Python pandas/numpy analysis code. Fix only the error shown. "
                "Do not change the objective, query, or dataset focus. Keep imports minimal. Return only code.",
            ),
            (
                "human",
                f"Question: {question}\n"
                f"Dataset: {self.data_path}\n"
                f"Plan steps: {plan_steps}\n"
                f"Context: {prompt_context}\n"
                f"Profile summary: {profile_summary}\n"
                f"Original code (must stay semantically similar):\n{original_code}\n"
                f"Current code:\n{code}\n"
                f"Error:\n{error_text}\n"
                "Return the corrected Python code only.",
            ),
        ]

        resp = self.llm.invoke(messages)
        content = getattr(resp, "content", str(resp))
        return self._strip_fence(content.strip())

    def _strip_fence(self, text: str) -> str:
        if text.startswith("```"):
            text = text.strip("`\n ")
            if "\n" in text:
                parts = text.split("\n", 1)
                if parts[0].startswith("python"):
                    return parts[1]
        return text

    @staticmethod
    def _summarize(
        result: Any,
        ns: dict[str, Any],
        before_keys: set[str],
        chosen_key: str | None,
    ) -> dict[str, Any]:
        if result is None:
            new_keys = [
                k
                for k in ns.keys()
                if k not in before_keys and not k.startswith("__") and k not in {"pd", "np", "df"}
            ]
            snapshot = {k: repr(ns.get(k))[:300] for k in new_keys}
            return {
                "type": "none",
                "preview": snapshot if snapshot else "No result returned; no new variables captured.",
                "chosen_key": chosen_key,
            }
        if isinstance(result, (str, int, float, bool)):
            return {"type": "scalar", "preview": result, "chosen_key": chosen_key}

        if isinstance(result, pd.DataFrame):
            return {
                "type": "dataframe",
                "preview": result.to_dict(orient="list"),
                "shape": list(result.shape),
                "chosen_key": chosen_key,
            }
        if hasattr(result, "to_dict"):
            try:
                return {"type": "object", "preview": result.to_dict(), "chosen_key": chosen_key}
            except Exception:
                pass
        if isinstance(result, (list, tuple)):
            return {
                "type": type(result).__name__,
                "preview": list(result),
                "length": len(result),
                "chosen_key": chosen_key,
            }
        return {"type": type(result).__name__, "preview": str(result), "chosen_key": chosen_key}

    def _answer_value(self, result: Any) -> tuple[Any, bool]:
        if isinstance(result, (str, int, float, bool)):
            return result, False
        if isinstance(result, (list, tuple)):
            return list(result), False
        if isinstance(result, dict):
            return dict(result), False
        if isinstance(result, pd.DataFrame):
            return result.to_dict(orient="records"), False
        if isinstance(result, pd.Series):
            return result.to_list(), False
        if np is not None and isinstance(result, np.ndarray):
            return result.tolist(), False
        return str(result), False

    def _load_config(self, config_path: Path) -> dict[str, Any]:
        cfg = yaml.safe_load(config_path.read_text()) or {}
        exec_cfg = cfg.get("executor", {}) or {}
        enabled = bool(exec_cfg.get("enabled", True))
        max_attempts = max(1, int(exec_cfg.get("max_attempts", 1)))
        model = exec_cfg.get("model", "gpt-4o")
        temperature = float(exec_cfg.get("temperature", 0.0))
        llm_cfg = cfg.get("llm", {}) or {}
        openai_api_key = (
            exec_cfg.get("openai_api_key")
            or llm_cfg.get("api_key")
            or os.environ.get("OPENAI_API_KEY")
        )
        base_url = llm_cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL")

        paths_cfg = cfg.get("paths", {}) or {}
        data_loader = paths_cfg.get("data_loader")
        data_csv_raw = Path(paths_cfg.get("data_csv")) if paths_cfg.get("data_csv") else None
        base = config_path.parent
        data_csv = self._resolve_child(base, data_csv_raw) if data_csv_raw else None
        if not data_loader and not data_csv:
            raise ValueError("Config must define paths.data_loader or paths.data_csv for executor.")
        if data_csv and not data_csv.exists():
            raise FileNotFoundError(f"Data file not found: {data_csv}")

        return {
            "enabled": enabled,
            "max_attempts": max_attempts,
            "model": model,
            "temperature": temperature,
            "openai_api_key": openai_api_key,
            "base_url": base_url,
            "data_path": data_csv,
            "data_loader": data_loader,
        }

    @staticmethod
    def _resolve_child(base: Path, child: Path) -> Path:
        if child.is_absolute():
            return child
        candidate = (base / child).resolve()
        if candidate.exists():
            return candidate
        alt = (base.parent / child).resolve()
        return alt

    @staticmethod
    def _sanitize(text: str) -> str:
        return text.replace("\r", "").strip()

    def _load_via_loader(self, path: str) -> pd.DataFrame:
        if ":" not in path:
            raise ValueError("paths.data_loader must be in form 'module_or_file.py:function'")
        module_name, func_name = path.split(":", 1)
        p = Path(module_name)
        if p.suffix == ".py":
            candidates = [p, self.config_path.parent / p]
            for candidate in candidates:
                candidate = candidate.resolve()
                if candidate.exists():
                    spec = importlib.util.spec_from_file_location(candidate.stem, str(candidate))
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)  # type: ignore[arg-type]
                        func = getattr(mod, func_name, None)
                        if not callable(func):
                            raise ValueError(f"Loader function '{func_name}' not found in {candidate}")
                        df = func()
                        if not isinstance(df, pd.DataFrame):
                            raise TypeError("Data loader must return a pandas DataFrame")
                        return df
            raise FileNotFoundError(f"Loader file not found: {module_name} (looked relative to config and cwd)")
        module = importlib.import_module(module_name)
        func = getattr(module, func_name, None)
        if not callable(func):
            raise ValueError(f"Loader function '{func_name}' not found in {module_name}")
        df = func()
        if not isinstance(df, pd.DataFrame):
            raise TypeError("Data loader must return a pandas DataFrame")
        return df
