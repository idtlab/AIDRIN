import logging
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


def calculate_custom_outliers(file_info, rules, max_outliers=100):
    """Evaluate custom range/regex outlier rules over iterator targets."""
    validated = _validate_rules(rules)
    max_outliers = _validate_max_outliers(max_outliers)
    target_map = _target_map(file_info)

    summaries = {}
    previews = {}
    errors = []

    for rule in validated:
        key = _internal_rule_key(rule["id"])
        summaries[key] = _base_summary(rule, max_outliers)
        previews[key] = []

        target = target_map.get((rule["target_type"], rule["target"]))
        if target is None:
            message = f"Target not found: {rule['target']}"
            summaries[key]["errors"] = [message]
            errors.append({"rule_id": rule["id"], "target": rule["target"], "error": message})
            continue

        try:
            for block in iter_value_blocks(file_info, target):
                _apply_rule_to_block(rule, block, summaries[key], previews[key], max_outliers)
        except Exception as exc:
            message = str(exc)
            summaries[key]["errors"] = [message]
            errors.append({"rule_id": rule["id"], "target": rule["target"], "error": message})

        total = summaries[key]["total"]
        outlier_count = summaries[key]["outlier"]
        summaries[key]["outlier_rate"] = (outlier_count / total) if total else 0.0
        summaries[key]["truncated"] = outlier_count > len(previews[key])

    result = {
        "Rule summaries": summaries,
        "Outlier preview": previews,
    }
    if errors:
        result["Errors"] = errors
    return result


@shared_task(bind=True, ignore_result=False)
def custom_outliers(self: Task, file_info, rules, max_outliers=100):
    return calculate_custom_outliers(file_info, rules, max_outliers=max_outliers)


def _validate_max_outliers(max_outliers):
    try:
        value = int(max_outliers)
    except (TypeError, ValueError):
        raise ValueError("max_outliers must be an integer")
    if value < 0:
        raise ValueError("max_outliers must be non-negative")
    return value


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

        criteria_type = str(raw_rule.get("criteria_type", "")).strip()
        if criteria_type not in {"range", "regex"}:
            raise ValueError(f"Rule {rule_id} has unsupported criteria_type: {criteria_type}")

        rule = {
            "id": rule_id,
            "name": str(raw_rule.get("name") or rule_id),
            "target": target,
            "target_type": target_type,
            "criteria_type": criteria_type,
            "allow_missing": bool(raw_rule.get("allow_missing", False)),
        }

        if criteria_type == "range":
            has_min = raw_rule.get("min") is not None and raw_rule.get("min") != ""
            has_max = raw_rule.get("max") is not None and raw_rule.get("max") != ""
            if not has_min and not has_max:
                raise ValueError(f"Range rule {rule_id} requires min or max")
            if has_min:
                rule["min"] = _coerce_bound(raw_rule.get("min"), rule_id, "min")
            if has_max:
                rule["max"] = _coerce_bound(raw_rule.get("max"), rule_id, "max")
            rule["min_inclusive"] = bool(raw_rule.get("min_inclusive", True))
            rule["max_inclusive"] = bool(raw_rule.get("max_inclusive", True))
        else:
            pattern = raw_rule.get("pattern")
            if pattern is None:
                raise ValueError(f"Regex rule {rule_id} requires pattern")
            try:
                rule["pattern"] = str(pattern)
                rule["_compiled_pattern"] = re.compile(rule["pattern"])
            except re.error as exc:
                raise ValueError(f"Regex rule {rule_id} has invalid pattern: {exc}")

        validated.append(rule)
    return validated


def _coerce_bound(value, rule_id, field):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Range rule {rule_id} has non-numeric {field}: {value}")


def _target_map(file_info):
    return {(target["target_type"], target["name"]): target for target in iter_targets(file_info)}


def _internal_rule_key(rule_id):
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", rule_id).strip("_")
    return key or "rule"


def _base_summary(rule, max_outliers):
    return {
        "id": rule["id"],
        "name": rule["name"],
        "target": rule["target"],
        "target_type": rule["target_type"],
        "criteria_type": rule["criteria_type"],
        "total": 0,
        "valid": 0,
        "outlier": 0,
        "missing": 0,
        "outlier_rate": 0.0,
        "preview_limit": max_outliers,
        "truncated": False,
    }


def _apply_rule_to_block(rule, block, summary, preview, max_outliers):
    values = block["values"]
    locate = block["locate"]
    is_missing = _build_missing_checker(block)

    for index_tuple, value in iter_indexed_values(values):
        summary["total"] += 1
        missing = is_missing(index_tuple, value)
        if missing:
            summary["missing"] += 1
            if rule["allow_missing"]:
                summary["valid"] += 1
                continue
            _record_outlier(rule, block, value, "missing", locate(index_tuple), summary, preview, max_outliers)
            continue

        reason = _invalid_reason(rule, value)
        if reason is None:
            summary["valid"] += 1
        else:
            _record_outlier(rule, block, value, reason, locate(index_tuple), summary, preview, max_outliers)


def _build_missing_checker(block):
    if "missing_mask" in block:
        mask_at = mask_lookup(block["missing_mask"])
        return lambda idx, _value: mask_at(idx)
    return lambda _idx, value: bool(pd.isna(value))


def _invalid_reason(rule, value):
    if rule["criteria_type"] == "range":
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric):
            return "non_numeric"
        number = float(numeric)
        if "min" in rule:
            if rule["min_inclusive"]:
                if number < rule["min"]:
                    return "below_min"
            elif number <= rule["min"]:
                return "below_min"
        if "max" in rule:
            if rule["max_inclusive"]:
                if number > rule["max"]:
                    return "above_max"
            elif number >= rule["max"]:
                return "above_max"
        return None

    text = _canonical_string(value)
    if rule["_compiled_pattern"].fullmatch(text):
        return None
    return "regex_mismatch"


def _canonical_string(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        value = value.item()
    return str(value)


def _record_outlier(rule, block, value, reason, location, summary, preview, max_outliers):
    summary["outlier"] += 1
    if len(preview) >= max_outliers:
        return
    preview.append({
        "target": rule["target"],
        "target_type": rule["target_type"],
        "value": _json_scalar(value),
        "reason": reason,
        "location": location,
    })


def _json_scalar(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value):
        return None
    return value
