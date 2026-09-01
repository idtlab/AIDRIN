"""Validate per-variable measurement-unit metadata without inspecting values."""

import logging
import re
from typing import Any, Dict, List, Optional

import h5py
import pandas as pd
import pyarrow.parquet as pq
from celery import shared_task
from pint import UnitRegistry

from aidrin.file_handling.value_iterators import iter_targets
from aidrin.file_handling.readers.hdf5_reader import hdf5Reader


logger = logging.getLogger(__name__)

_UNIT_REGISTRY = UnitRegistry()
_NAME_ANNOTATION = re.compile(
    r"^.+?\s*(?:\((?P<parenthesized>[^()]*)\)|\[(?P<bracketed>[^\[\]]*)\])\s*$"
)
_READY_STATUSES = {"valid", "dimensionless", "not_applicable"}


def _decode_metadata(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def _name_unit(name: str) -> Optional[str]:
    match = _NAME_ANNOTATION.fullmatch(name)
    if not match:
        return None
    unit = (match.group("parenthesized") or match.group("bracketed") or "").strip()
    if not unit:
        return None
    if match.group("bracketed") is not None and unit == "g":
        return "[g]"
    return unit


def _candidate(source: str, unit: str) -> Dict[str, str]:
    return {"source": source, "unit": unit}


def _discover_parquet(file_path: str) -> List[Dict[str, Any]]:
    targets = []
    for field in pq.read_schema(file_path):
        metadata = field.metadata or {}
        candidates = []
        for key in (b"units", b"unit"):
            if key in metadata:
                candidates.append(_candidate(f"native:{key.decode()}", _decode_metadata(metadata[key])))
        annotation = _name_unit(field.name)
        if annotation is not None:
            candidates.append(_candidate("name", annotation))
        targets.append({
            "name": field.name,
            "dtype": str(field.type),
            "target_type": "column",
            "unit_candidates": candidates,
        })
    return targets


def _pandas_hdf_columns(file_path: str) -> List[Dict[str, Any]]:
    targets = []
    with pd.HDFStore(file_path, mode="r") as store:
        keys = store.keys()
        for key in keys:
            storer = store.get_storer(key)
            columns = []
            for _axis, labels in getattr(storer, "non_index_axes", []):
                columns.extend(str(label) for label in labels)
            for column in dict.fromkeys(columns):
                name = column if len(keys) == 1 else f"{key.lstrip('/')}:{column}"
                candidates = []
                annotation = _name_unit(column)
                if annotation is not None:
                    candidates.append(_candidate("name", annotation))
                targets.append({
                    "name": name,
                    "dtype": "unknown",
                    "target_type": "column",
                    "unit_candidates": candidates,
                })
    return targets


def _discover_hdf5(file_info: tuple) -> List[Dict[str, Any]]:
    file_path = file_info[0]
    reader = hdf5Reader(file_path, logger)
    if reader._is_pandas_pytables_store():
        return _pandas_hdf_columns(file_path)

    selected = None
    if len(file_info) > 3 and file_info[3]:
        selected = {str(value).lstrip("/") for value in file_info[3]}

    targets = []
    with h5py.File(file_path, "r") as h5:
        def visit(name, obj):
            if not isinstance(obj, h5py.Dataset) or (selected is not None and name not in selected):
                return
            candidates = []
            for key in ("units", "unit"):
                if key in obj.attrs:
                    candidates.append(_candidate(f"native:{key}", _decode_metadata(obj.attrs[key])))
            path = f"/{name}"
            annotation = _name_unit(path)
            if annotation is not None:
                candidates.append(_candidate("name", annotation))
            targets.append({
                "name": path,
                "dtype": str(obj.dtype),
                "target_type": "hdf5_dataset",
                "unit_candidates": candidates,
            })

        h5.visititems(visit)
    return targets


def discover_variable_units(file_info: tuple) -> List[Dict[str, Any]]:
    """Discover logical variables and embedded unit declarations."""
    file_type = str(file_info[2] or "").lower()
    if file_type in {".h5", ".hdf5"}:
        return _discover_hdf5(file_info)
    if file_type == ".parquet":
        return _discover_parquet(file_info[0])

    targets = []
    for target in iter_targets(file_info):
        candidate = _name_unit(target["name"])
        normalized = dict(target)
        normalized["unit_candidates"] = [] if candidate is None else [_candidate("name", candidate)]
        targets.append(normalized)
    return targets


def _validate_mapping(unit_declarations: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    if unit_declarations is None:
        return {}
    if not isinstance(unit_declarations, dict):
        raise ValueError("unit_declarations must be a JSON object keyed by exact variable name")

    validated = {}
    for raw_name, declaration in unit_declarations.items():
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError("unit_declarations keys must be non-empty strings")
        if not isinstance(declaration, dict):
            raise ValueError(f"Declaration for {raw_name!r} must be an object")
        extra = set(declaration) - {"unit", "status"}
        if extra:
            raise ValueError(f"Declaration for {raw_name!r} has unknown fields: {sorted(extra)}")
        has_unit = "unit" in declaration
        has_status = "status" in declaration
        if has_unit == has_status:
            raise ValueError(f"Declaration for {raw_name!r} must contain exactly one of unit or status")
        if has_unit:
            unit = declaration["unit"]
            if not isinstance(unit, str) or not unit.strip():
                raise ValueError(f"Unit for {raw_name!r} must be a non-empty string")
            validated[raw_name] = {"unit": unit.strip()}
        elif declaration["status"] != "not_applicable":
            raise ValueError(f"Status for {raw_name!r} must be not_applicable")
        else:
            validated[raw_name] = {"status": "not_applicable"}
    return validated


def _parse_unit(unit: str) -> Dict[str, Any]:
    original = unit
    if unit.strip() == "g":
        return {
            "status": "ambiguous",
            "original_unit": original,
            "normalized_unit": None,
            "dimensionality": None,
            "message": "Bare 'g' is ambiguous. Use 'gram' for mass or '[g]', 'g_0', or 'standard_gravity' for acceleration.",
        }

    if "//" in unit:
        return {
            "status": "invalid",
            "original_unit": original,
            "normalized_unit": None,
            "dimensionality": None,
            "message": "Unit contains the unsupported floor-division operator '//'. Use '/' for division.",
        }

    parse_value = "standard_gravity" if unit.strip() == "[g]" else unit.strip()
    try:
        parsed = _UNIT_REGISTRY.Unit(parse_value)
    except Exception as exc:
        return {
            "status": "invalid",
            "original_unit": original,
            "normalized_unit": None,
            "dimensionality": None,
            "message": f"Unit is not recognized by Pint: {exc}",
        }

    status = "dimensionless" if parse_value == "1" else "valid"
    return {
        "status": status,
        "original_unit": original,
        "normalized_unit": format(parsed, "~"),
        "dimensionality": str(parsed.dimensionality),
        "message": "Dimensionless variable is explicitly declared with '1'." if status == "dimensionless" else "Unit is recognized by Pint.",
        "_parsed": parsed,
    }


def _units_equivalent(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    if left["status"] not in _READY_STATUSES or right["status"] not in _READY_STATUSES:
        return False
    if left["status"] == "not_applicable" or right["status"] == "not_applicable":
        return left["status"] == right["status"]
    return left.get("_parsed") == right.get("_parsed")


def _public_declaration(candidate: Dict[str, Any], parsed: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": candidate["source"],
        "original_unit": parsed.get("original_unit"),
        "normalized_unit": parsed.get("normalized_unit"),
        "status": parsed["status"],
    }


def _record_for_target(target: Dict[str, Any], explicit: Optional[Dict[str, str]]) -> Dict[str, Any]:
    candidates = list(target.get("unit_candidates", []))
    parsed_candidates = [(candidate, _parse_unit(candidate["unit"])) for candidate in candidates]
    warnings = []

    if explicit is not None:
        if "status" in explicit:
            chosen_candidate = {"source": "mapping"}
            chosen = {
                "status": "not_applicable",
                "original_unit": None,
                "normalized_unit": None,
                "dimensionality": None,
                "message": "Variable is explicitly classified as not applicable.",
            }
        else:
            chosen_candidate = {"source": "mapping", "unit": explicit["unit"]}
            chosen = _parse_unit(explicit["unit"])
        if candidates:
            warnings.append("Explicit mapping overrides lower-priority embedded or name declarations.")
    elif parsed_candidates:
        chosen_index = next(
            (index for index, item in enumerate(parsed_candidates) if item[0]["source"].startswith("native")),
            0,
        )
        chosen_candidate, chosen = parsed_candidates[chosen_index]
        comparisons = [item for index, item in enumerate(parsed_candidates) if index != chosen_index]
        if any(not _units_equivalent(chosen, other) for _candidate_item, other in comparisons):
            chosen = {
                "status": "conflicting",
                "original_unit": chosen.get("original_unit"),
                "normalized_unit": chosen.get("normalized_unit"),
                "dimensionality": chosen.get("dimensionality"),
                "message": "Embedded metadata and variable-name declarations conflict; add an explicit mapping to resolve them.",
            }
    else:
        chosen_candidate = {"source": None}
        chosen = {
            "status": "missing",
            "original_unit": None,
            "normalized_unit": None,
            "dimensionality": None,
            "message": "Add a recognized unit, '1' for dimensionless, or status 'not_applicable'.",
        }

    lower = [
        _public_declaration(candidate, parsed)
        for candidate, parsed in parsed_candidates
        if candidate is not chosen_candidate
    ]
    status = chosen["status"]
    return {
        "name": target["name"],
        "dtype": target.get("dtype", "unknown"),
        "chosen_source": chosen_candidate.get("source"),
        "classification": status,
        "original_unit": chosen.get("original_unit"),
        "normalized_unit": chosen.get("normalized_unit"),
        "dimensionality": chosen.get("dimensionality"),
        "status": "ready" if status in _READY_STATUSES else "not_ready",
        "message": chosen["message"],
        "lower_priority_declarations": lower,
        "warnings": warnings,
    }


def calculate_variable_unit_validation(
    file_info: tuple,
    unit_declarations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate that every logical variable has usable unit metadata."""
    mapping = _validate_mapping(unit_declarations)
    targets = discover_variable_units(file_info)
    target_names = {target["name"] for target in targets}
    unknown = sorted(set(mapping) - target_names)
    records = [_record_for_target(target, mapping.get(target["name"])) for target in targets]

    counts = {
        "total": len(records),
        "valid": 0,
        "missing": 0,
        "invalid": 0,
        "ambiguous": 0,
        "conflicting": 0,
        "dimensionless": 0,
        "not_applicable": 0,
    }
    for record in records:
        counts[record["classification"]] += 1

    total = counts["total"]
    ready = counts["valid"] + counts["dimensionless"] + counts["not_applicable"]
    coverage = None if total == 0 else (total - counts["missing"]) / total
    validity = None if total == 0 else ready / total
    warnings = [
        {"variable": record["name"], "message": warning}
        for record in records
        for warning in record["warnings"]
    ]
    return {
        "coverage_score": coverage,
        "validity_score": validity,
        "all_variables_ready": bool(total and ready == total and not unknown),
        "counts": counts,
        "variables": records,
        "override_warnings": warnings,
        "unknown_mapping_variables": unknown,
    }


@shared_task(ignore_result=False)
def variable_unit_validation(file_info: tuple, unit_declarations: Optional[Dict[str, Any]] = None):
    """Celery task wrapper for the variable-unit validation metric."""
    return calculate_variable_unit_validation(file_info, unit_declarations)


__all__ = [
    "calculate_variable_unit_validation",
    "discover_variable_units",
    "variable_unit_validation",
]
