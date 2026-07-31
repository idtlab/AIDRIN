import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional
import os

from aidrin.file_handling.file_parser import clear_frame_cache

from aidrin.headless import api as _local_api
from aidrin.compute.executor import AsyncSubmitted

from .api import (
    METRIC_REGISTRY,
    list_available_metrics,
    generate_metric_template,
    run_custom_metric_remedy,
)
from .config import HeadlessConfig


def _parse_list(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _parse_custom_outlier_rule_texts(rule_texts: Optional[List[str]]) -> Optional[List[dict]]:
    if not rule_texts:
        return None

    rules = []
    for index, rule_text in enumerate(rule_texts, start=1):
        target = None
        conditions = []
        for part in re.split(r"\s*&&\s*", rule_text):
            part = part.strip()
            if not part:
                raise ValueError(f"Empty condition in --rule: {rule_text}")
            match = re.fullmatch(r"(.+?)\s*(>=|<=|==|~=|>|<)\s*(.+)", part)
            if not match:
                raise ValueError(
                    "--rule supports simple conditions like "
                    "'score >= 0 && score <= 1' or 'name ~= ^[A-Z]+$'"
                )
            condition_target, operator, raw_value = (
                match.group(1).strip(),
                match.group(2),
                match.group(3).strip(),
            )
            if not condition_target:
                raise ValueError(f"Missing target in --rule condition: {part}")
            if target is None:
                target = condition_target
            elif condition_target != target:
                raise ValueError("--rule && shorthand must use the same target in every condition")

            if operator == "~=":
                conditions.append({"type": "regex", "pattern": raw_value})
                continue

            try:
                value = float(raw_value)
            except ValueError as exc:
                raise ValueError(f"Numeric --rule condition requires a finite number: {part}") from exc
            if not value == value or value in (float("inf"), float("-inf")):
                raise ValueError(f"Numeric --rule condition requires a finite number: {part}")

            if operator == ">=":
                conditions.append({"type": "range", "min": value, "min_inclusive": True})
            elif operator == ">":
                conditions.append({"type": "range", "min": value, "min_inclusive": False})
            elif operator == "<=":
                conditions.append({"type": "range", "max": value, "max_inclusive": True})
            elif operator == "<":
                conditions.append({"type": "range", "max": value, "max_inclusive": False})
            elif operator == "==":
                conditions.append({"type": "range", "min": value, "max": value})

        assert target is not None
        criteria = conditions[0] if len(conditions) == 1 else {"op": "and", "conditions": conditions}
        rule_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", target).strip("-") or f"rule-{index}"
        rules.append({
            "id": f"{rule_id}-{index}",
            "name": rule_text,
            "target": target,
            "target_type": "column",
            "criteria": criteria,
        })
    return rules


def _dump_result(result: object) -> None:
    sys.stdout.write(json.dumps(result, indent=2))
    sys.stdout.write("\n")


def _summarize_data_quality(result: dict) -> None:
    """Print a compact summary of data quality results."""
    # Completeness
    comp = result.get("completeness", {})
    overall_comp = comp.get("Overall Completeness", "N/A")
    scores = comp.get("Completeness scores", {})
    n_features = len(scores)
    if scores:
        vals = list(scores.values())
        min_comp = min(vals)
        incomplete = sum(1 for v in vals if v < 1.0)
    else:
        min_comp = "N/A"
        incomplete = 0

    # Duplicity
    dup = result.get("duplicity", {})
    dup_scores = dup.get("Duplicity scores", {})
    dup_ratio = dup_scores.get("Overall duplicity of the dataset", "N/A")

    # Outliers
    out = result.get("outliers", {})
    out_scores = out.get("Outlier scores", {})
    overall_outlier = out_scores.get("Overall outlier score", "N/A")
    feature_outliers = {k: v for k, v in out_scores.items() if k != "Overall outlier score"}
    if feature_outliers:
        max_outlier = max(feature_outliers.values())
        high_outlier = sum(1 for v in feature_outliers.values() if v > 0.05)
    else:
        max_outlier = "N/A"
        high_outlier = 0

    print(f"Data Quality Summary ({n_features} features)")
    print(f"{'='*45}")
    print(f"Completeness:  {_fmt(overall_comp)}  (min: {_fmt(min_comp)}, incomplete: {incomplete}/{n_features})")
    print(f"Duplicity:     {_fmt(dup_ratio)}")
    print(f"Outliers:      {_fmt(overall_outlier)}  (max: {_fmt(max_outlier)}, >5%: {high_outlier}/{n_features})")


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _round_floats(obj, ndigits: int = 4):
    """Recursively round float values for cleaner CLI output."""
    from numbers import Number

    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, list):
        return [_round_floats(item, ndigits) for item in obj]
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    # Keep other numerics (int, Decimal) unchanged
    if isinstance(obj, Number):
        return obj
    return obj


def _summarize_metric(metric_name: str, result: dict) -> None:
    """Print a compact summary for a single metric result."""
    if metric_name == "completeness":
        overall = result.get("Overall Completeness", "N/A")
        scores = result.get("Completeness scores", {})
        n = len(scores)
        if scores:
            vals = list(scores.values())
            incomplete = sum(1 for v in vals if v < 1.0)
            print(f"Completeness ({n} features): {_fmt(overall)}  (min: {_fmt(min(vals))}, incomplete: {incomplete}/{n})")
        else:
            print(f"Completeness: {_fmt(overall)}")
    elif metric_name == "duplicity":
        dup_scores = result.get("Duplicity scores", {})
        ratio = dup_scores.get("Overall duplicity of the dataset", "N/A")
        print(f"Duplicity: {_fmt(ratio)}")
    elif metric_name == "outliers":
        scores = result.get("Outlier scores", {})
        overall = scores.get("Overall outlier score", "N/A")
        feature_scores = {k: v for k, v in scores.items() if k != "Overall outlier score"}
        n = len(feature_scores)
        if feature_scores:
            mx = max(feature_scores.values())
            high = sum(1 for v in feature_scores.values() if v > 0.05)
            print(f"Outliers ({n} features): {_fmt(overall)}  (max: {_fmt(mx)}, >5%: {high}/{n})")
        else:
            print(f"Outliers: {_fmt(overall)}")
    elif metric_name == "hipaa_compliance":
        if not result:
            print("No PHI detected.")
        else:
            for col, findings in result.items():
                types_str = ", ".join(findings.get("potential_types_detected", []))
                print(f"{col}: {findings.get('total_flags', 0)} flag(s)  [{types_str}]")
    else:
        # Generic: print top-level keys with scalar values, count dict/list values
        for k, v in result.items():
            if "visualization" in k.lower():
                continue
            if isinstance(v, dict):
                print(f"{k}: ({len(v)} entries)")
            elif isinstance(v, list):
                print(f"{k}: [{len(v)} items]")
            else:
                print(f"{k}: {_fmt(v)}")


def _print_summary_table(result: dict, file_path: str) -> None:
    """Print a human-readable summary of summarize_dataset output."""
    import os
    name = os.path.basename(file_path)
    rows = result["shape"]["rows"]
    cols = result["shape"]["columns"]
    print(f"{name} — {rows:,} rows × {cols} columns")

    numerical = result.get("numerical", {})
    if numerical:
        print(f"\nNumerical ({len(numerical)}):")
        for col, s in numerical.items():
            print(
                f"  {col:<22} mean={_fmt(s['mean']):<12} std={_fmt(s['std']):<12}"
                f" min={_fmt(s['min']):<10} max={_fmt(s['max']):<10} missing={s['missing']}"
            )

    categorical = result.get("categorical", {})
    if categorical:
        print(f"\nCategorical ({len(categorical)}):")
        for col, s in categorical.items():
            pct = 100.0 * s["freq"] / s["count"] if s["count"] else 0.0
            print(
                f"  {col:<22} {s['unique']:>6} unique"
                f"  top={str(s['top'])[:16]:<18} ({pct:.1f}%)  missing={s['missing']}"
            )

    if result.get("truncated"):
        print(f"\n[truncated to {result['max_features']} features — pass --max-features to adjust]")


def _build_run_kwargs(args: argparse.Namespace) -> dict:
    rule_texts = getattr(args, "rule_texts", None)
    parsed_rules = _parse_custom_outlier_rule_texts(rule_texts)
    rules_json = getattr(args, "rules_json", None)
    rules_file = getattr(args, "rules_file", None)
    sources = [
        ("rules-json", rules_json),
        ("--rule", parsed_rules),
        ("--rules-file", rules_file),
    ]
    if sum(value is not None and value != "" and value != [] for _, value in sources) > 1:
        raise ValueError("Use exactly one custom-outlier rule source: rules-json, --rule, or --rules-file")
    return {
        "columns": _parse_list(getattr(args, "columns", None)),
        "target_column": getattr(args, "target_column", None),
        "quasi_identifiers": _parse_list(getattr(args, "quasi_identifiers", None)),
        "sensitive_column": getattr(args, "sensitive_column", None),
        "epsilon": getattr(args, "epsilon", None),
        "id_column": getattr(args, "id_column", None),
        "eval_columns": _parse_list(getattr(args, "eval_columns", None)),
        "distance_metric": getattr(args, "distance_metric", None),
        "cat_columns": _parse_list(getattr(args, "cat_columns", None)),
        "num_columns": _parse_list(getattr(args, "num_columns", None)),
        "y_true_column": getattr(args, "y_true_column", None),
        "sensitive_attribute_column": getattr(args, "sensitive_attribute_column", None),
        "required_columns": _parse_list(getattr(args, "required_columns", None)),
        "duplicate_columns": _parse_list(getattr(args, "duplicate_columns", None)),
        "threshold": getattr(args, "threshold", None),
        "frequency": getattr(args, "frequency", None),
        "timestamp_column": getattr(args, "timestamp_column", None),
        "batch_column": getattr(args, "batch_column", None),
        "target_columns": _parse_list(getattr(args, "target_columns", None)),
        "rules": parsed_rules,
        "rules_json": rules_json,
        "rules_file": rules_file,
        "max_outliers": getattr(args, "max_outliers", 100),
        "max_export_rows": getattr(args, "max_export_rows", 10000),
        "scan_limit": getattr(args, "scan_limit", None),
        "stop_after_outliers": getattr(args, "stop_after_outliers", False),
        # Default to no image generation/saving for headless usage
        "save_images": getattr(args, "save_images", False),
        "image_dir": getattr(args, "image_dir", None),
        "verbose": getattr(args, "verbose", False),
        # Do not emit viz payloads by default
        "strip_visualizations": getattr(args, "no_viz", True),
    }


def _configure_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--file-type", dest="file_type", default=None, help="Input file type override")
    parser.add_argument("--save-images", dest="save_images", action="store_true", help="Save visualizations to disk")
    parser.add_argument("--no-save-images", dest="save_images", action="store_false", help="Do not save visualizations")
    parser.set_defaults(save_images=True)
    parser.add_argument("--image-dir", default=None, help="Directory to write images")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show progress output")
    parser.add_argument("--no-viz", action="store_true", help="Strip visualization data from output", default=True)
    parser.add_argument("--detail", action="store_true", help="Output full JSON instead of summary", default=True)


def _configure_minimal_run_args(parser: argparse.ArgumentParser) -> None:
    """Lightweight args for top-level metric shortcuts."""
    parser.add_argument("-v", "--verbose", action="store_true", help="Show progress output")


def _add_required_metric_args(parser: argparse.ArgumentParser, required_args: List[str]) -> None:
    """Attach only the args needed for a specific metric."""
    for arg in required_args:
        if arg == "columns":
            parser.add_argument("columns", help="Comma-separated column list", metavar="columns")
        elif arg == "target-column":
            parser.add_argument("target_column", help="Target column name", metavar="target-column")
        elif arg == "quasi-identifiers":
            parser.add_argument("quasi_identifiers", help="Comma-separated quasi-identifier columns", metavar="quasi-identifiers")
        elif arg == "sensitive-column":
            parser.add_argument("sensitive_column", help="Sensitive column name", metavar="sensitive-column")
        elif arg == "epsilon":
            parser.add_argument("epsilon", type=float, help="Epsilon for differential privacy", metavar="epsilon")
        elif arg == "id-column":
            parser.add_argument("id_column", help="ID column for Markov risk metrics", metavar="id-column")
        elif arg == "eval-columns":
            parser.add_argument("eval_columns", help="Comma-separated eval columns", metavar="eval-columns")
        elif arg == "distance-metric":
            parser.add_argument("distance_metric", help="Distance metric", metavar="distance-metric")
        elif arg == "cat-columns":
            parser.add_argument(
                "cat_columns",
                nargs="?",
                default=None,
                help="Comma-separated categorical columns (optional; provide at least one of categorical-columns or numerical-columns)",
                metavar="categorical-columns",
            )
        elif arg == "num-columns":
            parser.add_argument(
                "num_columns",
                nargs="?",
                default=None,
                help="Comma-separated numerical columns (optional; provide at least one of categorical-columns or numerical-columns)",
                metavar="numerical-columns",
            )
        elif arg == "y-true-column":
            parser.add_argument("y_true_column", help="Ground truth column", metavar="y-true-column")
        elif arg == "rules-json":
            parser.add_argument(
                "rules_json",
                nargs="?",
                help="JSON array of custom outlier rules. Use 0 for unlimited preview/export caps.",
                metavar="rules-json",
            )
        elif arg == "sensitive-attribute-column":
            parser.add_argument("sensitive_attribute_column", help="Sensitive attribute column", metavar="sensitive-attribute-column")
        elif arg == "required-columns":
            parser.add_argument("--required-columns", dest="required_columns", default=None,
                                help="Comma-separated required columns (rows missing any are incomplete)")
        elif arg == "duplicate-columns":
            parser.add_argument("--duplicate-columns", dest="duplicate_columns", default=None,
                                help="Comma-separated columns to compare when detecting duplicate rows")
        elif arg == "threshold":
            parser.add_argument("--threshold", dest="threshold", type=float, default=None,
                                help="Coverage threshold in [0, 1] (default 0.9)")
        elif arg == "frequency":
            parser.add_argument("--frequency", dest="frequency", default=None,
                                choices=["ms", "s", "min", "h", "D", "W", "ME", "QE", "YE"],
                                help='Interval frequency (default "D"): '
                                     'ms, s, min, h, D, W, ME, QE, YE')
        elif arg == "timestamp-column":
            parser.add_argument("--timestamp-column", dest="timestamp_column", default=None,
                                help="Datetime column name")
        elif arg == "batch-column":
            parser.add_argument("--batch-column", dest="batch_column", default=None,
                                help="Column that groups rows into batches")
        elif arg == "target-columns":
            parser.add_argument("--target-columns", dest="target_columns", default=None,
                                help="Comma-separated columns to count nulls in (optional)")


def _agentic_build_index(args: argparse.Namespace) -> None:
    try:
        from aidrin.agentic.vector_db_builder import VectorDBBuilder
    except ImportError:
        sys.stderr.write("Error: agentic dependencies not installed. Run: pip install 'aidrin[agentic]'\n")
        sys.exit(1)
    result = VectorDBBuilder(Path(args.config).resolve()).build()
    print(json.dumps(result, indent=2))


def _agentic_run(args: argparse.Namespace) -> None:
    try:
        import yaml
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from aidrin.agentic.data_profiler import DataProfiler
        from aidrin.agentic.vector_db_builder import VectorDBBuilder
        from aidrin.agentic.run import _run_query, _json_safe
        from aidrin.agentic.token_tracker import get_tracker
    except ImportError:
        sys.stderr.write("Error: agentic dependencies not installed. Run: pip install 'aidrin[agentic]'\n")
        sys.exit(1)

    config_path = Path(args.config).resolve()
    get_tracker().reset()

    profiler = DataProfiler(config_path=config_path)
    profile_result = profiler.profile()

    cfg = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}

    if not args.skip_vector and cfg.get("vector_store"):
        builder = VectorDBBuilder(config_path)
        if not builder.exists():
            vector_result = builder.build()
            if getattr(args, "verbose", False):
                sys.stderr.write(json.dumps(vector_result, indent=2) + "\n")

    retrieval_cfg = cfg.get("retrieval", {}) or {}
    questions_raw = retrieval_cfg.get("questions") or []
    if not questions_raw:
        single = retrieval_cfg.get("question", "")
        questions_raw = single if isinstance(single, list) else ([single] if single else [])

    def _parse_q(q):
        return (q["text"], q.get("loader")) if isinstance(q, dict) else (q, None)

    parsed_questions = [_parse_q(q) for q in questions_raw]

    max_workers = int(retrieval_cfg.get("max_workers", 4))
    query_results = []
    if parsed_questions:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(parsed_questions))) as pool:
            futures = {
                pool.submit(_run_query, config_path, text, profile_result, loader): text
                for text, loader in parsed_questions
            }
            for future in as_completed(futures):
                try:
                    query_results.append(future.result())
                except Exception as exc:
                    query_results.append({"question": futures[future], "error": str(exc)})

    combined = _json_safe({
        "profile": profile_result,
        "queries": query_results,
        "token_usage": get_tracker().to_dict(),
    })

    if args.output:
        out = Path(args.output).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
        sys.stderr.write(f"Results written to: {out}\n")

    print(json.dumps(combined, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Remote execution (aidrin remote ...)
# ---------------------------------------------------------------------------

REMOTE_MANAGEMENT = {
    "configure", "list", "remove", "check", "login", "logout", "status", "task",
}

# Commands that cannot run on an endpoint: they need files or credentials that
# live on the client machine.
REMOTE_FORBIDDEN = {"add-custom-module", "agentic"}


REMOTE_HELP = """usage: aidrin remote [--profile NAME] [--endpoint UUID] [--async] [--timeout SECONDS] <command> ...

Run an aidrin command on a Globus Compute endpoint. Every command takes exactly
the same arguments as its local counterpart, because the same parser handles it:

  aidrin remote summarize /scratch/data.csv
  aidrin remote run completeness /scratch/data.csv

Paths are resolved on the endpoint, not on this machine.

management commands:
  configure --name NAME --endpoint UUID   probe an endpoint and save it as a profile
  list                                    show saved profiles as JSON
  remove NAME                             delete a saved profile
  check                                   report the endpoint's aidrin and python versions
  login, status                           confirm Globus authentication
  logout                                  drop the cached Globus tokens
  task ID [--wait | --cancel]             inspect, wait on, or cancel a submitted task

flags (before the command):
  --profile NAME      use a saved profile
  --endpoint UUID     use this endpoint, ignoring profiles
  --async             submit and print the task id instead of waiting
  --timeout SECONDS   how long to wait for a result (default 600)

Per-command help is the local help: aidrin remote summarize --help
"""


def _split_remote_argv(argv: List[str]):
    """Pull remote-only flags out of argv, leaving the local command untouched."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--profile", default=None)
    pre.add_argument("--endpoint", default=None)
    pre.add_argument("--timeout", type=float, default=None)
    pre.add_argument("--async", dest="detach", action="store_true")
    return pre.parse_known_args(argv)


def _remote_management(argv: List[str], opts) -> None:
    """Handle `aidrin remote <configure|list|remove|check|login|logout|status|task>`."""
    from aidrin.compute import client as compute_client
    from aidrin.compute import profiles

    action = argv[0]
    rest = argv[1:]

    if action == "configure":
        parser = argparse.ArgumentParser(prog="aidrin remote configure")
        parser.add_argument("--name", required=True, help="Profile name, e.g. nersc")
        # `--endpoint` is one of the remote-only flags, so `_split_remote_argv`
        # has already taken it out of `rest`; it arrives here via `opts`. The
        # argument stays declared so `--help` still documents it.
        parser.add_argument("--endpoint", default=opts.endpoint, help="Globus Compute endpoint UUID")
        parser.add_argument("--default", action="store_true", help="Make this the default profile")
        parser.add_argument("--local", action="store_true", help="Write ./.aidrin.json instead of ~/.aidrin/config.json")
        args = parser.parse_args(rest)
        if not args.endpoint:
            # Exit 2 like every other usage error in this feature; argparse
            # would have done the same had it seen the missing flag itself.
            sys.stderr.write("Error: aidrin remote configure needs --endpoint <uuid>\n")
            sys.exit(2)
        sys.stderr.write(f"Probing endpoint {args.endpoint}...\n")
        env = compute_client.probe(compute_client.get_client(), args.endpoint)
        path = profiles.save_profile(
            args.name,
            args.endpoint,
            default=args.default,
            local=args.local,
            aidrin_version=env.get("aidrin_version"),
        )
        sys.stderr.write(
            f"  aidrin {env.get('aidrin_version')}, python {env.get('python_version')}\n"
            f"Saved profile '{args.name}' to {path}\n"
        )
        return

    if action == "list":
        _dump_result(profiles.list_profiles())
        return

    if action == "remove":
        parser = argparse.ArgumentParser(prog="aidrin remote remove")
        parser.add_argument("name")
        parser.add_argument("--local", action="store_true")
        args = parser.parse_args(rest)
        if not profiles.remove_profile(args.name, local=args.local):
            raise ValueError(f"No such profile: {args.name}")
        sys.stderr.write(f"Removed profile '{args.name}'\n")
        return

    if action == "check":
        target = profiles.resolve(endpoint=opts.endpoint, profile=opts.profile)
        env = compute_client.probe(compute_client.get_client(), target.endpoint)
        _dump_result({"endpoint": target.endpoint, "profile": target.profile, **env})
        return

    if action in {"login", "logout", "status"}:
        conn = compute_client.get_client()
        if action == "logout":
            conn.logout()
            sys.stderr.write("Logged out of Globus.\n")
            return
        # `get_client()` triggers the SDK's own login flow when needed, so
        # reaching this line means the client is authenticated.
        sys.stderr.write("Globus login OK (tokens cached by globus-compute-sdk).\n")
        return

    if action == "task":
        parser = argparse.ArgumentParser(prog="aidrin remote task")
        parser.add_argument("task_id")
        parser.add_argument("--wait", action="store_true", help="Block until the task finishes")
        parser.add_argument("--cancel", action="store_true", help="Cancel the task")
        args = parser.parse_args(rest)
        conn = compute_client.get_client()
        if args.cancel:
            compute_client.cancel(conn, args.task_id)
            sys.stderr.write(f"Cancelled {args.task_id}\n")
            return
        if args.wait:
            timeout = opts.timeout or compute_client.DEFAULT_TIMEOUT
            _dump_result(_round_floats(compute_client.poll(conn, args.task_id, timeout=timeout)))
            return
        _dump_result(compute_client.check(conn, args.task_id))
        return

    raise ValueError(f"Unknown remote subcommand: {action}")


def _make_remote_executor(opts, on_submit=None):
    """Resolve the endpoint and build the executor the dispatch will use."""
    from aidrin import __version__ as local_version
    from aidrin.compute import client as compute_client
    from aidrin.compute.executor import RemoteExecutor
    from aidrin.compute import profiles

    target = profiles.resolve(endpoint=opts.endpoint, profile=opts.profile)

    if target.aidrin_version:
        local_minor = ".".join(str(local_version).split(".")[:2])
        remote_minor = ".".join(str(target.aidrin_version).split(".")[:2])
        if local_minor != remote_minor:
            sys.stderr.write(
                f"Warning: endpoint runs aidrin {target.aidrin_version}, "
                f"this client is {local_version}. Metrics added since the "
                "endpoint's version will fail there.\n"
            )

    label = target.profile or target.endpoint
    sys.stderr.write(f"Running on Globus Compute endpoint {label}\n")
    return RemoteExecutor(
        target,
        timeout=opts.timeout or compute_client.DEFAULT_TIMEOUT,
        detach=opts.detach,
        on_submit=on_submit,
    )


def main() -> None:
    argv = sys.argv[1:]
    executor = _local_api
    remote_opts = None
    remote_task_id = None

    if argv and argv[0] == "remote":
        remote_opts, argv = _split_remote_argv(argv[1:])
        if argv and argv[0] in {"-h", "--help"}:
            # `aidrin remote <command> --help` is deliberately left to the local
            # parser: identical help is what proves identical arguments.
            sys.stdout.write(REMOTE_HELP)
            return
        if not argv:
            sys.stderr.write(
                "Error: 'aidrin remote' needs a subcommand, e.g. "
                "'aidrin remote configure --name <name> --endpoint <uuid>' or "
                "'aidrin remote summarize <path>'\n"
            )
            sys.exit(2)
        if argv[0] in REMOTE_FORBIDDEN:
            sys.stderr.write(
                f"Error: '{argv[0]}' is local-only. It needs files or credentials "
                f"on this machine. Run it without the 'remote' prefix.\n"
            )
            sys.exit(2)
        if argv[0] in REMOTE_MANAGEMENT:
            try:
                _remote_management(argv, remote_opts)
            except Exception as exc:
                sys.stderr.write(f"Error: {exc}\n")
                sys.exit(1)
            return

    parser = argparse.ArgumentParser(prog="aidrin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "add-custom-module",
        help="Create a new custom module template (metric + remedy) in a directory you specify",
    )
    create_parser.add_argument(
        "name",
        help="Name of the custom module (e.g. 'my_audit'). No spaces or special characters.",
    )
    create_parser.add_argument(
        "--dir",
        dest="custom_dir",
        required=True,
        help="Directory to create the module in (e.g. --dir /path/to/my_project)",
    )

    list_parser = subparsers.add_parser("list", help="List available metrics")
    list_parser.add_argument("--category", default=None)

    run_parser = subparsers.add_parser("run", help="Run a metric (per-metric help via: aidrin run <metric> -h)")
    run_subparsers = run_parser.add_subparsers(dest="metric", required=True)

    # Built-in metrics
    for metric_name, meta in METRIC_REGISTRY.items():
        extra_help = ""
        if metric_name == "feature_relevance":
            extra_help = (
                " (provide categorical-columns or numerical-columns; example: "
                "aidrin feature-relevance data.csv \"gender\" \"age,income\" target)"
            )
        metric_cli = metric_name.replace("_", "-")
        mparser = run_subparsers.add_parser(metric_cli, help=meta["description"] + extra_help)
        mparser.add_argument("file_path", help="Path to the dataset CSV")
        _add_required_metric_args(mparser, meta.get("required_args", []))
        if metric_name == "outliers_custom":
            mparser.add_argument(
                "--rule",
                dest="rule_texts",
                action="append",
                help=(
                    "Simple rule shorthand, repeatable. Supports same-target conditions "
                    "joined by &&, e.g. --rule 'score >= 0 && score <= 1'. "
                    "Rules describe valid values; use rules-json for OR/NOT/nested rules."
                ),
            )
            mparser.add_argument("--rules-file", help="Path to a JSON array of custom outlier rules")
            mparser.add_argument("--max-outliers", type=int, default=100, help="Preview cap per rule; 0 means unlimited")
            mparser.add_argument("--max-export-rows", type=int, default=10000, help="Export row cap per rule; 0 means unlimited")
            mparser.add_argument("--scan-limit", type=int, default=None, help="Maximum values to scan per rule")
            mparser.add_argument("--stop-after-outliers", action="store_true", help="Stop scanning after preview cap is reached")
        _configure_minimal_run_args(mparser)
        mparser.set_defaults(_metric_key=metric_name, _action="metric")

    # Custom metric / remedy runner
    custom_parser = run_subparsers.add_parser(
        "custom",
        help="Run a custom metric or remedy from a .py file",
    )
    custom_parser.add_argument("name", help="Path to the custom module file (e.g. /path/to/my_audit.py)")
    custom_parser.add_argument("file_path", help="Path to the dataset CSV")
    custom_parser.add_argument("action", nargs="?", choices=["metric", "remedy"], default="metric", help="Run metric (default) or remedy")
    _configure_minimal_run_args(custom_parser)

    batch_parser = subparsers.add_parser("batch", help="Run metrics from config file (JSON or YAML)")
    batch_parser.add_argument("config_path")
    batch_parser.add_argument("-v", "--verbose", action="store_true", help="Show progress output")
    batch_parser.add_argument(
        "--viz",
        dest="no_viz",
        action="store_false",
        help="Include visualization data in output",
        default=True,
    )

    # Fast data quality command
    dq_parser = subparsers.add_parser("data-quality", help="Run fast data quality metrics (completeness, duplicity, outliers)")
    dq_parser.add_argument("file_path")
    dq_parser.add_argument("--file-type", dest="file_type", default=None)
    dq_parser.add_argument("-v", "--verbose", action="store_true", help="Show progress output")
    dq_parser.add_argument("--detail", action="store_true", help="Output full per-feature JSON instead of summary")

    # Dataset summary command
    summarize_parser = subparsers.add_parser("summarize", help="Describe numerical and categorical features of a dataset")
    summarize_parser.add_argument("file_path", help="Path to the dataset")
    summarize_parser.add_argument("--file-type", dest="file_type", default=None, help="File type override (csv, parquet, xlsx, hdf5, json, npz)")
    summarize_parser.add_argument(
        "--max-features", dest="max_features", type=int, default=None,
        help="Limit stats to N features (split evenly between numerical and categorical)"
    )
    summarize_parser.add_argument("--summary", dest="human_readable", action="store_true", help="Print human-readable table instead of JSON")

    # Agentic evaluation commands
    agentic_parser = subparsers.add_parser("agentic", help="Agentic evaluation commands (requires aidrin[agentic])")
    agentic_sub = agentic_parser.add_subparsers(dest="agentic_command", required=True)

    build_parser = agentic_sub.add_parser("build-index", help="Build vector index from domain literature")
    build_parser.add_argument("-c", "--config", required=True, help="Path to YAML config")
    build_parser.add_argument("-v", "--verbose", action="store_true", help="Show progress output")

    agentic_run_parser = agentic_sub.add_parser("run", help="Run the agentic evaluation pipeline")
    agentic_run_parser.add_argument("-c", "--config", required=True, help="Path to YAML config")
    agentic_run_parser.add_argument("-o", "--output", default=None, help="Path to write JSON results")
    agentic_run_parser.add_argument("--skip-vector", dest="skip_vector", action="store_true",
                                    help="Skip rebuilding the vector index; use existing one")
    agentic_run_parser.add_argument("-v", "--verbose", action="store_true", help="Print vector build info to stderr")

    # argv was computed at the top of main() so the `remote` prefix could be
    # stripped before the local parser ever sees it.
    # Shortcut: allow `aidrin <metric> ...` (dash or underscore) to map to `aidrin run <metric> ...`
    if argv:
        metric_key = argv[0].replace("-", "_")
        if metric_key in METRIC_REGISTRY:
            argv = ["run", metric_key.replace("_", "-")] + argv[1:]
    args = parser.parse_args(argv)

    if remote_opts is not None:
        if args.command == "run" and getattr(args, "metric", None) == "custom":
            sys.stderr.write(
                "Error: custom metrics and remedies are local-only. The custom "
                "module lives on this machine and the endpoint cannot import it.\n"
            )
            sys.exit(2)

        def _note_submission(task_id: str) -> None:
            """Report the task on stderr and remember it for the Ctrl-C path."""
            nonlocal remote_task_id
            remote_task_id = task_id
            sys.stderr.write(f"Submitted task {task_id}; waiting for the result...\n")

        try:
            executor = _make_remote_executor(remote_opts, on_submit=_note_submission)
        except Exception as exc:
            sys.stderr.write(f"Error: {exc}\n")
            sys.exit(2)

    # Cache sidecar cleanup: unlike the web app (whose uploads live in a
    # managed, periodically-reaped folder), the CLI reads files from
    # arbitrary locations on disk, so nothing else will clean up the
    # ``.aidrin.feather`` cache written by read_file(). Track the dataset
    # path(s) touched by this invocation and sweep them in `finally` below.
    cleanup_path = getattr(args, "file_path", None)

    try:
        if args.command == "add-custom-module":
            target_dir = args.custom_dir or os.getcwd()
            try:
                path = generate_metric_template(args.name, target_dir)
                print(f"Template successfully created at: {path}")
                print("Edit the 'metric' and 'remedy' methods to add your logic.")
                print(f"Run the metric via: aidrin run custom {path} <dataset> metric")
                print(f"Run the remedy via: aidrin run custom {path} <dataset> remedy")
            except FileExistsError as e:
                print(f"{e}")
            return
        if args.command == "list":
            _dump_result(_round_floats(list_available_metrics(category=args.category)))
            return

        if args.command == "run":
            # Built-in metrics
            metric_key = getattr(args, "_metric_key", None)
            if metric_key:
                if metric_key == "feature_relevance" and not (args.cat_columns or args.num_columns):
                    sys.stderr.write(
                        "Error: provide at least one of categorical-columns or numerical-columns\n"
                    )
                    sys.exit(2)
                result = executor.run_metric(
                    metric_key,
                    args.file_path,
                    file_type=getattr(args, "file_type", None),
                    **_build_run_kwargs(args),
                )
                if getattr(args, "detail", True):
                    _dump_result(_round_floats(result))
                else:
                    _summarize_metric(metric_key, result)
                return

            # Custom metrics/remedies
            if args.metric == "custom":
                if args.action == "remedy":
                    output_path = run_custom_metric_remedy(
                        args.name,
                        args.file_path,
                        output_dir=None,
                        file_type=getattr(args, "file_type", None),
                        **_build_run_kwargs(args),
                    )
                    print(f"Remedied data saved to: {output_path}")
                    return
                result = executor.run_metric(
                    args.name,
                    args.file_path,
                    file_type=getattr(args, "file_type", None),
                    **_build_run_kwargs(args),
                )
                if getattr(args, "detail", True):
                    _dump_result(_round_floats(result))
                else:
                    _summarize_metric(args.name.strip().lower(), result)
                return

        # Top-level metric shortcut (e.g., `aidrin completeness ...`)
        if args.command in METRIC_REGISTRY:
            if args.command == "feature_relevance" and not (args.cat_columns or args.num_columns):
                sys.stderr.write(
                    "Error: provide at least one of categorical-columns or numerical-columns\n"
                )
                sys.exit(2)
            result = executor.run_metric(
                args.command,
                args.file_path,
                file_type=getattr(args, "file_type", None),
                **_build_run_kwargs(args),
            )
            if getattr(args, "detail", True):
                _dump_result(_round_floats(result))
            else:
                _summarize_metric(args.command, result)
            return

        if args.command == "batch":
            config = HeadlessConfig.from_file(args.config_path)
            cleanup_path = config.file_path
            result = executor.run_batch_metrics(
                config,
                verbose=args.verbose,
                strip_visualizations=args.no_viz,
            )
            _dump_result(_round_floats(result))
            return

        if args.command == "summarize":
            result = executor.summarize_dataset(
                args.file_path,
                file_type=args.file_type,
                max_features=args.max_features,
            )
            if args.human_readable:
                _print_summary_table(result, args.file_path)
            else:
                _dump_result(_round_floats(result))
            return

        if args.command == "data-quality":
            result = executor.run_data_quality(
                args.file_path,
                file_type=args.file_type,
                verbose=args.verbose,
                strip_visualizations=True,
            )
            if args.detail:
                _dump_result(_round_floats(result))
            else:
                _summarize_data_quality(result)
            return

        if args.command == "agentic":
            if args.agentic_command == "build-index":
                _agentic_build_index(args)
            elif args.agentic_command == "run":
                _agentic_run(args)
            return
    except AsyncSubmitted as submitted:
        _dump_result({"task_id": submitted.task_id})
        return
    except KeyboardInterrupt:
        # Only claim a cancellation when there was a task to cancel: a local run,
        # or an interrupt that lands before submission, cancelled nothing.
        if remote_task_id:
            sys.stderr.write(f"\nInterrupted; cancelled remote task {remote_task_id}.\n")
        else:
            sys.stderr.write("\nInterrupted.\n")
        sys.exit(130)
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)
    finally:
        # Under `remote`, file_path names a file on the endpoint. This client
        # never read it and must not delete a sidecar next to it, which a shared
        # filesystem would happily let it do.
        if cleanup_path and remote_opts is None:
            clear_frame_cache(cleanup_path)


if __name__ == "__main__":
    main()
