"""
Agentic evaluation pipeline entry point.

Run the full five-stage pipeline (profile → vector build → retrieve → execute → score → remediate)
for all questions defined in a YAML config.

Example:
    python -m aidrin.agentic.run -c configs/my_dataset.yaml -o results/output.json
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime
from pathlib import Path

from aidrin.agentic.retriever import VectorRetriever
from aidrin.agentic.executor import CodeExecutor
from aidrin.agentic.complexity_scorer import QueryComplexityScorer
from aidrin.agentic.remediation_generator import RemediationGenerator

try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None

try:
    import numpy as np  # type: ignore
except Exception:
    np = None


def _json_safe(obj):
    if pd is not None:
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="list")
        if isinstance(obj, pd.Series):
            return obj.to_dict()
    if np is not None:
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            return obj.item()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


def _write_run_log(payload: dict, out_dir: Path) -> Path:
    run_id = datetime.now().strftime("log_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _run_query(
    config_path: Path,
    question: str,
    profile_result: dict,
    loader_override: str | None = None,
) -> dict:
    """Run retrieve → execute → score → remediate for a single question."""
    retrieval_result = None
    try:
        retriever = VectorRetriever(config_path)
        retrieval_result = retriever.retrieve(profile_summary=profile_result, question=question)
    except Exception as exc:
        retrieval_result = {"error": str(exc)}

    executor_result = None
    try:
        executor = CodeExecutor(config_path)
        if loader_override:
            executor.data_loader_path = loader_override
        executor_result = executor.run(retrieval_result=retrieval_result, profile_result=profile_result)
    except Exception as exc:
        executor_result = {"error": str(exc)}

    complexity_result = None
    if retrieval_result and not retrieval_result.get("error"):
        try:
            scorer = QueryComplexityScorer(config_path)
            complexity_result = scorer.score(
                retrieval_result=retrieval_result,
                profile_summary=profile_result,
            )
        except Exception as exc:
            complexity_result = {"error": str(exc)}

    remediation_result = None
    try:
        rem_gen = RemediationGenerator(config_path)
        remediation_result = rem_gen.generate({
            "question": question,
            "retrieval": retrieval_result,
            "execution": executor_result,
            "complexity": complexity_result,
        })
    except Exception as exc:
        remediation_result = {"error": str(exc)}

    return {
        "question": question,
        "retrieval": retrieval_result,
        "execution": executor_result,
        "complexity": complexity_result,
        "remediation": remediation_result,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the domain-aware agentic data readiness evaluation pipeline.")
    parser.add_argument("-c", "--config", type=Path, required=True,
                        help="Path to YAML config file.")
    parser.add_argument("-o", "--output", type=Path,
                        help="Optional path to write JSON results.")
    parser.add_argument("--full", action="store_true",
                        help="Disable compact profiling (include all columns).")
    parser.add_argument("--max-columns", type=int, default=3,
                        help="Max columns per type in compact mode.")
    parser.add_argument("--max-metadata-rows", type=int, default=20)
    parser.add_argument("--max-metadata-bytes", type=int, default=4000)
    parser.add_argument("--skip-vector", action="store_true",
                        help="Skip vector store building (use existing index).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    from aidrin.headless.api import run_agentic_pipeline

    result = run_agentic_pipeline(
        str(args.config),
        output_path=str(args.output) if args.output else None,
        skip_vector=args.skip_vector,
        compact=False if args.full else None,
        max_columns=args.max_columns,
        max_metadata_rows=args.max_metadata_rows,
        max_metadata_bytes=args.max_metadata_bytes,
    )

    saved_to = result.pop("_saved_to", None)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if saved_to:
        print(f"\n[run log] {saved_to}")


if __name__ == "__main__":
    main()
