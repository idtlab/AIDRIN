import logging
import math
import re

import numpy as np
import pandas as pd
from celery import Task, shared_task

from aidrin.file_handling.value_iterators import (
    iter_indexed_values,
    iter_targets,
    iter_value_blocks,
    mask_lookup,
)

logger = logging.getLogger(__name__)


def calculate_custom_outliers(
    file_info,
    rules,
    max_outliers=100,
    scan_limit=None,
    stop_after_outliers=False,
    max_export_rows=10000,
):
    """Evaluate custom range/regex outlier rules over iterator targets."""
    validated = _validate_rules(rules)
    max_outliers = _validate_max_outliers(max_outliers)
    scan_limit = _validate_optional_non_negative_int(scan_limit, "scan_limit")
    max_export_rows = _validate_optional_non_negative_int(max_export_rows, "max_export_rows")
    stop_after_outliers = _coerce_bool(stop_after_outliers)
    target_map = _target_map(file_info)

    summaries = {}
    previews = {}
    exports = {}
    hdf5_aggregates = {}
    errors = []

    for rule in validated:
        key = _internal_rule_key(rule["id"])
        summaries[key] = _base_summary(rule, max_outliers, scan_limit, stop_after_outliers, max_export_rows)
        previews[key] = []
        exports[key] = []
        hdf5_aggregates[key] = _new_hdf5_aggregate_state()

        target = target_map.get((rule["target_type"], rule["target"]))
        if target is None:
            message = f"Target not found: {rule['target']}"
            summaries[key]["errors"] = [message]
            errors.append({"rule_id": rule["id"], "target": rule["target"], "error": message})
            continue

        try:
            for block in iter_value_blocks(file_info, target):
                should_stop = _apply_rule_to_block(
                    rule,
                    block,
                    summaries[key],
                    previews[key],
                    exports[key],
                    hdf5_aggregates[key],
                    max_outliers,
                    max_export_rows,
                    scan_limit,
                    stop_after_outliers,
                )
                if should_stop:
                    break
        except Exception as exc:
            message = str(exc)
            summaries[key]["errors"] = [message]
            errors.append({"rule_id": rule["id"], "target": rule["target"], "error": message})

        total = summaries[key]["total"]
        outlier_count = summaries[key]["outlier"]
        summaries[key]["outlier_rate"] = (outlier_count / total) if total else 0.0
        summaries[key]["truncated"] = outlier_count > len(previews[key])
        summaries[key]["export_truncated"] = outlier_count > len(exports[key])

    result = {
        "Rule summaries": summaries,
        "Outlier preview": previews,
        "Outlier export": exports,
    }
    hdf5_summary = _finalize_hdf5_aggregates(hdf5_aggregates)
    if hdf5_summary:
        result["HDF5 aggregates"] = hdf5_summary
    if errors:
        result["Errors"] = errors
    return result


@shared_task(bind=True, ignore_result=False)
def custom_outliers(
    self: Task,
    file_info,
    rules,
    max_outliers=100,
    scan_limit=None,
    stop_after_outliers=False,
    max_export_rows=10000,
):
    return calculate_custom_outliers(
        file_info,
        rules,
        max_outliers=max_outliers,
        scan_limit=scan_limit,
        stop_after_outliers=stop_after_outliers,
        max_export_rows=max_export_rows,
    )


def _validate_max_outliers(max_outliers):
    try:
        value = int(max_outliers)
    except (TypeError, ValueError):
        raise ValueError("max_outliers must be an integer")
    if value < 0:
        raise ValueError("max_outliers must be non-negative")
    return value


def _validate_optional_non_negative_int(value, field):
    if value in (None, ""):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer")
    if normalized < 0:
        raise ValueError(f"{field} must be non-negative")
    return normalized


def _coerce_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _validate_rules(rules):
    if not isinstance(rules, list) or not rules:
        raise ValueError("custom outlier rules must be a non-empty list")

    seen_ids = set()
    seen_keys = {}
    validated = []
    for index, raw_rule in enumerate(rules):
        if not isinstance(raw_rule, dict):
            raise ValueError(f"Rule {index} must be an object")

        rule_id = str(raw_rule.get("id", "")).strip()
        if not rule_id:
            raise ValueError("Each custom outlier rule requires a non-empty id")
        if rule_id in seen_ids:
            raise ValueError(f"Duplicate custom outlier rule id: {rule_id}")
        seen_ids.add(rule_id)
        rule_key = _internal_rule_key(rule_id)
        if rule_key in seen_keys:
            raise ValueError(
                "Custom outlier rule ids resolve to the same output key: "
                f"{seen_keys[rule_key]} and {rule_id}"
            )
        seen_keys[rule_key] = rule_id

        target = str(raw_rule.get("target", "")).strip()
        if not target:
            raise ValueError(f"Rule {rule_id} requires a target")
        target_type = str(raw_rule.get("target_type", "")).strip()
        if target_type not in {"column", "hdf5_dataset"}:
            raise ValueError(f"Rule {rule_id} has unsupported target_type: {target_type}")

        if "criteria_type" in raw_rule or any(
            field in raw_rule for field in ("min", "max", "pattern", "min_inclusive", "max_inclusive")
        ):
            raise ValueError(f"Rule {rule_id} must use criteria tree syntax")
        criteria = _validate_rule_criteria(raw_rule.get("criteria"), rule_id)

        rule = {
            "id": rule_id,
            "name": str(raw_rule.get("name") or rule_id),
            "target": target,
            "target_type": target_type,
            "criteria": criteria,
            "allow_missing": bool(raw_rule.get("allow_missing", False)),
        }

        validated.append(rule)
    return validated


def _validate_range_criteria(raw_rule, rule_id):
    has_min = raw_rule.get("min") is not None and raw_rule.get("min") != ""
    has_max = raw_rule.get("max") is not None and raw_rule.get("max") != ""
    if not has_min and not has_max:
        raise ValueError(f"Range rule {rule_id} requires min or max")

    criteria = {
        "type": "range",
        "min_inclusive": bool(raw_rule.get("min_inclusive", True)),
        "max_inclusive": bool(raw_rule.get("max_inclusive", True)),
    }
    if has_min:
        criteria["min"] = _coerce_bound(raw_rule.get("min"), rule_id, "min")
    if has_max:
        criteria["max"] = _coerce_bound(raw_rule.get("max"), rule_id, "max")
    return criteria


def _validate_regex_criteria(raw_rule, rule_id):
    pattern = raw_rule.get("pattern")
    if pattern is None:
        raise ValueError(f"Regex rule {rule_id} requires pattern")
    try:
        return {
            "type": "regex",
            "pattern": str(pattern),
            "_compiled_pattern": re.compile(str(pattern)),
        }
    except re.error as exc:
        raise ValueError(f"Regex rule {rule_id} has invalid pattern: {exc}")


def _validate_rule_criteria(raw_criteria, rule_id):
    if not isinstance(raw_criteria, dict):
        raise ValueError(f"Rule {rule_id} requires criteria")
    return _validate_criteria_node(raw_criteria, rule_id, "criteria")


def _validate_criteria_node(node, rule_id, path):
    if not isinstance(node, dict):
        raise ValueError(f"Compound rule {rule_id} has invalid {path}")

    op = str(node.get("op", "")).strip().lower()
    if op:
        if op in {"and", "or"}:
            children = node.get("conditions")
            if not isinstance(children, list) or not children:
                raise ValueError(f"Compound rule {rule_id} {path}.{op} requires conditions")
            return {
                "op": op,
                "conditions": [
                    _validate_criteria_node(child, rule_id, f"{path}.conditions[{i}]")
                    for i, child in enumerate(children)
                ],
            }
        if op == "not":
            child = node.get("condition")
            if child is None:
                children = node.get("conditions")
                if isinstance(children, list) and len(children) == 1:
                    child = children[0]
            if child is None:
                raise ValueError(f"Compound rule {rule_id} {path}.not requires condition")
            return {
                "op": "not",
                "condition": _validate_criteria_node(child, rule_id, f"{path}.condition"),
            }
        raise ValueError(f"Compound rule {rule_id} has unsupported operator: {op}")

    condition_type = str(node.get("type") or "").strip()
    if condition_type == "range":
        return _validate_range_criteria(node, rule_id)
    if condition_type == "regex":
        return _validate_regex_criteria(node, rule_id)
    raise ValueError(f"Compound rule {rule_id} has unsupported condition type: {condition_type}")


def _coerce_bound(value, rule_id, field):
    try:
        bound = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Range rule {rule_id} has non-numeric {field}: {value}")
    if not math.isfinite(bound):
        raise ValueError(f"Range rule {rule_id} has non-finite {field}: {value}")
    return bound


def _target_map(file_info):
    return {(target["target_type"], target["name"]): target for target in iter_targets(file_info)}


def _internal_rule_key(rule_id):
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", rule_id).strip("_")
    return key or "rule"


def _base_summary(rule, max_outliers, scan_limit, stop_after_outliers, max_export_rows):
    return {
        "id": rule["id"],
        "name": rule["name"],
        "target": rule["target"],
        "target_type": rule["target_type"],
        "total": 0,
        "valid": 0,
        "outlier": 0,
        "missing": 0,
        "outlier_rate": 0.0,
        "preview_limit": max_outliers,
        "scan_limit": scan_limit,
        "scan_stopped_early": False,
        "stop_after_outliers": stop_after_outliers,
        "export_limit": max_export_rows,
        "export_truncated": False,
        "truncated": False,
    }


def _apply_rule_to_block(
    rule,
    block,
    summary,
    preview,
    export_rows,
    hdf5_aggregates,
    max_outliers,
    max_export_rows,
    scan_limit,
    stop_after_outliers,
):
    values = block["values"]
    locate = block["locate"]
    is_missing = _build_missing_checker(block)

    for index_tuple, value in iter_indexed_values(values):
        if _scan_limit_reached(summary, scan_limit):
            return True
        summary["total"] += 1
        location = locate(index_tuple)
        missing = is_missing(index_tuple, value)
        if missing:
            summary["missing"] += 1
            if rule["allow_missing"]:
                _record_hdf5_aggregate(rule, block, location, hdf5_aggregates, missing=True, outlier=False)
                summary["valid"] += 1
                continue
            _record_outlier(
                rule,
                block,
                value,
                "missing",
                "missing",
                location,
                summary,
                preview,
                export_rows,
                max_outliers,
                max_export_rows,
                hdf5_aggregates,
            )
            if _should_stop_after_outlier(summary, stop_after_outliers, max_outliers):
                return True
            continue

        reason, flag = _invalid_result(rule, value)
        if reason is None:
            summary["valid"] += 1
            _record_hdf5_aggregate(rule, block, location, hdf5_aggregates, missing=False, outlier=False)
        else:
            _record_outlier(
                rule,
                block,
                value,
                reason,
                flag,
                location,
                summary,
                preview,
                export_rows,
                max_outliers,
                max_export_rows,
                hdf5_aggregates,
            )
            if _should_stop_after_outlier(summary, stop_after_outliers, max_outliers):
                return True
    return False


def _scan_limit_reached(summary, scan_limit):
    if scan_limit is None:
        return False
    reached = summary["total"] >= scan_limit
    if reached:
        summary["scan_stopped_early"] = True
    return reached


def _should_stop_after_outlier(summary, stop_after_outliers, max_outliers):
    if not stop_after_outliers:
        return False
    reached = summary["outlier"] >= max_outliers
    if reached:
        summary["scan_stopped_early"] = True
    return reached


def _build_missing_checker(block):
    if "missing_mask" in block:
        mask_at = mask_lookup(block["missing_mask"])
        return lambda idx, _value: mask_at(idx)
    return lambda _idx, value: bool(pd.isna(value))


def _invalid_result(rule, value):
    return _criteria_invalid_result(rule["criteria"], value)


def _criteria_invalid_result(criteria, value):
    if criteria.get("op") == "and":
        for child in criteria["conditions"]:
            reason, flag = _criteria_invalid_result(child, value)
            if reason is not None:
                return reason, flag
        return None, None
    if criteria.get("op") == "or":
        failures = []
        for child in criteria["conditions"]:
            reason, flag = _criteria_invalid_result(child, value)
            if reason is None:
                return None, None
            failures.append((reason, flag))
        if len(failures) == 1:
            return failures[0]
        return "or_mismatch", "no match"
    if criteria.get("op") == "not":
        reason, _flag = _criteria_invalid_result(criteria["condition"], value)
        if reason is None:
            return "not_mismatch", "NOT"
        return None, None

    if criteria["type"] == "range":
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric):
            return "non_numeric", "NaN"
        number = float(numeric)
        if "min" in criteria:
            if criteria["min_inclusive"]:
                if number < criteria["min"]:
                    return "below_min", _format_bound_flag("<", value, criteria["min"])
            elif number <= criteria["min"]:
                return "below_min", _format_bound_flag("<=", value, criteria["min"])
        if "max" in criteria:
            if criteria["max_inclusive"]:
                if number > criteria["max"]:
                    return "above_max", _format_bound_flag(">", value, criteria["max"])
            elif number >= criteria["max"]:
                return "above_max", _format_bound_flag(">=", value, criteria["max"])
        return None, None

    text = _canonical_string(value)
    if criteria["_compiled_pattern"].fullmatch(text):
        return None, None
    return "regex_mismatch", f"!= /{criteria.get('pattern', '')}/"


def _canonical_string(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        value = value.item()
    return str(value)


def _record_outlier(
    rule,
    block,
    value,
    reason,
    flag,
    location,
    summary,
    preview,
    export_rows,
    max_outliers,
    max_export_rows,
    hdf5_aggregates,
):
    summary["outlier"] += 1
    _record_hdf5_aggregate(rule, block, location, hdf5_aggregates, missing=(reason == "missing"), outlier=True)
    row = {
        "rule_id": rule["id"],
        "rule_name": rule["name"],
        "target": rule["target"],
        "target_type": rule["target_type"],
        "value": _json_scalar(value),
        "reason": reason,
        "flag": flag or _format_outlier_flag(rule, value, reason),
        "location": location,
    }
    if len(preview) < max_outliers:
        preview.append(row)
    if max_export_rows is None or len(export_rows) < max_export_rows:
        export_rows.append(row)


def _format_outlier_flag(rule, value, reason):
    if reason == "below_min" and "min" in rule:
        return _format_bound_flag("<", value, rule["min"])
    if reason == "above_max" and "max" in rule:
        return _format_bound_flag(">", value, rule["max"])
    if reason == "regex_mismatch":
        return f"!= /{rule.get('pattern', '')}/"
    if reason == "non_numeric":
        return "NaN"
    if reason == "missing":
        return "missing"
    return reason


def _format_bound_flag(operator, value, bound):
    try:
        number = float(pd.to_numeric(value, errors="raise"))
        delta = abs(number - float(bound))
        return f"{operator} {_format_compact_number(bound)} by {_format_compact_number(delta)}"
    except (TypeError, ValueError):
        return f"{operator} {_format_compact_number(bound)}"


def _format_compact_number(value):
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _new_hdf5_aggregate_state():
    return {
        "by_leading_index": {},
        "by_chunk": {},
    }


def _record_hdf5_aggregate(rule, block, location, aggregate_state, missing, outlier):
    if rule["target_type"] != "hdf5_dataset":
        return
    index = location.get("index")
    if not isinstance(index, list) or len(index) <= 1:
        return

    leading_key = str(index[0])
    _update_hdf5_aggregate_bucket(
        aggregate_state["by_leading_index"],
        leading_key,
        label=f"index {index[0]}",
        location=location,
        missing=missing,
        outlier=outlier,
    )

    offset = block.get("offset")
    if offset:
        chunk_key = ",".join(str(i) for i in offset)
        _update_hdf5_aggregate_bucket(
            aggregate_state["by_chunk"],
            chunk_key,
            label=f"offset [{chunk_key}]",
            location=location,
            missing=missing,
            outlier=outlier,
        )


def _update_hdf5_aggregate_bucket(buckets, key, label, location, missing, outlier):
    bucket = buckets.setdefault(
        key,
        {
            "key": key,
            "label": label,
            "total": 0,
            "missing": 0,
            "outlier": 0,
            "first_outlier": None,
        },
    )
    bucket["total"] += 1
    if missing:
        bucket["missing"] += 1
    if outlier:
        bucket["outlier"] += 1
        if bucket["first_outlier"] is None:
            bucket["first_outlier"] = location


def _finalize_hdf5_aggregates(aggregate_states, limit=50):
    result = {}
    for key, state in aggregate_states.items():
        by_leading = _top_hdf5_aggregate_rows(state["by_leading_index"], limit)
        by_chunk = _top_hdf5_aggregate_rows(state["by_chunk"], limit)
        if by_leading or by_chunk:
            result[key] = {}
            if by_leading:
                result[key]["by_leading_index"] = by_leading
            if by_chunk:
                result[key]["by_chunk"] = by_chunk
    return result


def _top_hdf5_aggregate_rows(buckets, limit):
    rows = [row for row in buckets.values() if row["outlier"] or row["missing"]]
    rows.sort(key=lambda row: (-row["outlier"], -row["missing"], row["key"]))
    return rows[:limit]


def _json_scalar(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value):
        return None
    return value
