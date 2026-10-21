"""
CodeExecutor: executes LLM-generated analysis code against a dataset,
with a self-healing loop that asks the LLM to repair failing code.

Config (YAML) expected keys:

.. code-block:: yaml

    llm:
      base_url: "https://openrouter.ai/api/v1"   # or "https://api.cborg.lbl.gov" — one provider for the whole pipeline
      model: openai/gpt-oss-120b                   # used here and by retrieval/complexity_scorer/remediation

    executor:
      enabled: true
      max_attempts: 3
      timeout_seconds: 60    # wall-clock limit per execution attempt
      temperature: 0.0

The API key is resolved from ``llm.base_url`` — ``OPENROUTER_API_KEY`` for OpenRouter,
``CBORG_API_KEY`` for CBORG (or an explicit ``llm.api_key`` in config).
"""

from __future__ import annotations

import importlib
import importlib.util
import multiprocessing
import traceback
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

try:
    import numpy as np
except Exception:
    np = None

from aidrin.agentic.llm_factory import create_chat_model, resolve_provider_api_key


def _run_code_in_subprocess(code: str, df: pd.DataFrame, queue: "multiprocessing.Queue") -> None:
    """
    Module-level (picklable, spawn-safe) worker: exec() the LLM-provided code
    against its own copy of the dataframe in this child process, then reduce
    the result to the same JSON-safe payload CodeExecutor.run() returns —
    computed here, not in the parent, because the raw namespace (`pd`/`np`
    modules, arbitrary LLM-created objects) generally isn't picklable across
    the process boundary, while the reduced payload always is.

    Puts exactly one ("success", result_payload) or ("error", formatted_text)
    tuple onto `queue` before exiting.
    """
    ns: dict[str, Any] = {"pd": pd, "df": df, "result": None}
    if np is not None:
        ns["np"] = np
    before_keys = set(ns.keys())
    try:
        exec(code, ns, ns)  # noqa: S102
        value, chosen_key = CodeExecutor._select_result(ns, before_keys)
        result_payload = CodeExecutor._summarize(value, ns, before_keys, chosen_key)
        answer_value, answer_truncated = CodeExecutor._answer_value(value)
        result_payload["answer"] = answer_value
        result_payload["answer_truncated"] = answer_truncated
        queue.put(("success", result_payload))
    except BaseException as exc:  # noqa: BLE001 - reported back to the parent, not re-raised here
        queue.put(("error", f"{exc}\n{traceback.format_exc()}"))


class CodeExecutor:
    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)
        cfg = self._load_config(self.config_path)
        self.enabled: bool = cfg["enabled"]
        self.max_attempts: int = cfg["max_attempts"]
        self.timeout_seconds: float = cfg["timeout_seconds"]
        self.model: str = cfg["model"]
        self.temperature: float = cfg["temperature"]
        self.api_key: str | None = cfg["api_key"]
        self.base_url: str | None = cfg["base_url"]
        self.data_path: Path | None = cfg.get("data_path")
        self.data_loader_path: str | None = cfg.get("data_loader")

        self.llm = None
        if self.enabled:
            self.llm = create_chat_model(
                self.model, temperature=self.temperature, api_key=self.api_key, base_url=self.base_url,
                component="execution",
            )

    def run(
        self,
        retrieval_result: dict[str, Any] | None,
        profile_result: dict[str, Any] | None = None,
        data_loader_override: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute generated code with optional self-healing repairs.

        data_loader_override: if given, takes precedence over paths.data_loader
        from the config for this call only (e.g. a per-question loader), so the
        executed code runs against the same dataset the profile/retrieval used.
        """
        if not self.enabled:
            return {"enabled": False, "message": "Executor disabled in config."}

        if not retrieval_result or not retrieval_result.get("code"):
            return {"enabled": True, "error": "No code provided for execution."}

        initial_code = self._sanitize(retrieval_result.get("code", ""))
        question = retrieval_result.get("query") or ""
        plan_steps = retrieval_result.get("plan_steps")
        prompt_context = retrieval_result.get("prompt_context")

        data_loader_path = data_loader_override or self.data_loader_path
        if data_loader_path:
            df = self._load_via_loader(data_loader_path)
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
                result_payload = self._execute(code, df)
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
                    data_loader_path=data_loader_path,
                )

        return {
            "enabled": True,
            "success": False,
            "attempts": attempts,
            "final_code": code,
            "last_error": last_error,
        }

    def _execute(self, code: str, df: pd.DataFrame) -> dict[str, Any]:
        """
        Run the LLM-provided code against the dataframe, in an isolated child
        process, under a hard wall-clock timeout (executor.timeout_seconds,
        default 60s). Returns the JSON-safe result payload (with `answer`/
        `answer_truncated` already set) on success.

        A thread can't be force-killed in Python, so an earlier version of
        this ran the code on a daemon thread and simply abandoned it on
        timeout — but an abandoned thread keeps running: it can still mutate
        shared state, perform I/O, or finish late and race a subsequent
        repair attempt. A process can actually be terminated, so on timeout
        the child is killed (terminate(), escalating to kill() if it ignores
        SIGTERM) and joined — reaped, confirmed dead — before this returns,
        so the next attempt never overlaps with a still-running previous one
        and no abandoned workers accumulate across repeated timeouts.

        Uses the "spawn" start method explicitly rather than the platform
        default: run_agentic_pipeline dispatches questions across a
        ThreadPoolExecutor, so _execute can be called from a worker thread,
        and fork()ing a multi-threaded process is unsafe (locks held by
        other threads at fork time can deadlock the child).

        Note: spawning a process and reimporting this package costs real
        wall-clock time (~1-2s measured), which counts against
        timeout_seconds before any generated code even runs. Negligible
        against the 60s default; a very low timeout_seconds risks spurious
        timeouts on trivial code.
        """
        ctx = multiprocessing.get_context("spawn")
        queue: multiprocessing.Queue = ctx.Queue()
        process = ctx.Process(target=_run_code_in_subprocess, args=(code, df, queue), daemon=True)
        process.start()
        process.join(self.timeout_seconds)

        if process.is_alive():
            process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join()
            raise TimeoutError(
                f"Code execution exceeded the {self.timeout_seconds:g}s timeout and was terminated. "
                "This usually means the generated code has an inefficient or infinite loop "
                "(e.g. re-reading/re-scanning the full dataset repeatedly instead of using "
                "the already-loaded `df`). Rewrite it as a single vectorised pandas/numpy pass."
            )

        try:
            status, payload = queue.get(timeout=5)
        except Exception as exc:
            raise RuntimeError(
                f"Code execution subprocess exited without a result (exit code {process.exitcode})."
            ) from exc
        if status == "error":
            raise RuntimeError(payload)
        return payload

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
        data_loader_path: str | None = None,
    ) -> str:
        """Ask the LLM to minimally patch the code using the error details."""
        if not self.llm:
            return code

        profile_summary = ""
        if profile_result and profile_result.get("summary"):
            profile_summary = str(profile_result.get("summary"))

        dataset_label = self.data_path or (f"loader:{data_loader_path}" if data_loader_path else None)

        messages = [
            (
                "system",
                "You repair Python pandas/numpy analysis code. Fix only the error shown. "
                "Do not change the objective, query, or dataset focus. Keep imports minimal. Return only code.",
            ),
            (
                "human",
                f"Question: {question}\n"
                f"Dataset: {dataset_label}\n"
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

    @staticmethod
    def _answer_value(result: Any) -> tuple[Any, bool]:
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
        timeout_seconds = float(exec_cfg.get("timeout_seconds", 60))
        temperature = float(exec_cfg.get("temperature", 0.0))
        llm_cfg = cfg.get("llm", {}) or {}
        model = llm_cfg.get("model", "gpt-4o")
        base_url = llm_cfg.get("base_url")
        # One provider (llm.base_url) for the whole pipeline — no mixing OpenRouter and
        # CBORG keys within a single run. See resolve_provider_api_key for the inference.
        api_key = resolve_provider_api_key(base_url, llm_cfg.get("api_key"))

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
            "timeout_seconds": timeout_seconds,
            "model": model,
            "temperature": temperature,
            "api_key": api_key,
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
