"""Audit and resolve per-variable measurement-unit metadata without changing data."""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import h5py
import pandas as pd
import pyarrow.parquet as pq
from celery import shared_task
from pint import UnitRegistry

from aidrin.file_handling.value_iterators import iter_targets
from aidrin.file_handling.readers.hdf5_reader import hdf5Reader


logger = logging.getLogger(__name__)

SIDECAR_FORMAT = "aidrin.variable-unit-metadata"
SIDECAR_VERSION = 1
UNIT_VOCABULARY = "pint"

_UNIT_REGISTRY = UnitRegistry()
_NAME_ANNOTATION = re.compile(
    r"^.+?\s*(?:\((?P<parenthesized>[^()]*)\)|\[(?P<bracketed>[^\[\]]*)\])\s*$"
)
_READY_STATUSES = {"valid", "dimensionless", "not_applicable"}
_RESOLUTION_KINDS = {"unit", "dimensionless", "not_applicable", "unresolved"}
_RESOLUTION_SOURCES = {"detected", "user", "none"}


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
                annotation = _name_unit(column)
                targets.append({
                    "name": name,
                    "dtype": "unknown",
                    "target_type": "column",
                    "unit_candidates": [] if annotation is None else [_candidate("name", annotation)],
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
        annotation = _name_unit(target["name"])
        targets.append({
            "name": target["name"],
            "dtype": target.get("dtype", "unknown"),
            "target_type": target.get("target_type", "column"),
            "unit_candidates": [] if annotation is None else [_candidate("name", annotation)],
        })
    return targets


def _schema_fingerprint(targets: List[Dict[str, Any]]) -> str:
    schema = [
        {
            "name": target["name"],
            "target_type": target.get("target_type", "column"),
            "dtype": target.get("dtype", "unknown"),
        }
        for target in targets
    ]
    encoded = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


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


def _public_observation(candidate: Dict[str, Any], parsed: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": candidate["source"],
        "unit": candidate["unit"],
        "normalized_unit": parsed.get("normalized_unit"),
        "dimensionality": parsed.get("dimensionality"),
        "status": parsed["status"],
        "message": parsed["message"],
    }


def _validate_resolution(name: str, resolution: Any) -> Dict[str, Any]:
    if not isinstance(resolution, dict):
        raise ValueError(f"Resolution for {name!r} must be an object")
    extra = set(resolution) - {"kind", "unit", "source"}
    if extra:
        raise ValueError(f"Resolution for {name!r} has unknown fields: {sorted(extra)}")
    kind = resolution.get("kind")
    source = resolution.get("source")
    if kind not in _RESOLUTION_KINDS:
        raise ValueError(f"Resolution kind for {name!r} must be one of {sorted(_RESOLUTION_KINDS)}")
    if source not in _RESOLUTION_SOURCES:
        raise ValueError(f"Resolution source for {name!r} must be one of {sorted(_RESOLUTION_SOURCES)}")
    unit = resolution.get("unit")
    if kind == "unit":
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError(f"Unit resolution for {name!r} must contain a non-empty unit")
        return {"kind": kind, "unit": unit.strip(), "source": source}
    if kind == "dimensionless":
        if unit != "1":
            raise ValueError(f"Dimensionless resolution for {name!r} must use unit '1'")
        return {"kind": kind, "unit": "1", "source": source}
    if unit is not None:
        raise ValueError(f"Resolution kind {kind!r} for {name!r} must not contain a unit")
    return {"kind": kind, "source": source}


def _validate_sidecar(
    sidecar: Optional[Dict[str, Any]],
    targets: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    if sidecar is None:
        return {}
    if not isinstance(sidecar, dict):
        raise ValueError("Variable-unit metadata must be a JSON object")
    required = {"format", "version", "unit_vocabulary", "dataset", "variables", "summary"}
    if set(sidecar) != required:
        raise ValueError(f"Variable-unit metadata fields must be exactly {sorted(required)}")
    if sidecar["format"] != SIDECAR_FORMAT or sidecar["version"] != SIDECAR_VERSION:
        raise ValueError(f"Variable-unit metadata must use {SIDECAR_FORMAT!r} version {SIDECAR_VERSION}")
    if sidecar["unit_vocabulary"] != UNIT_VOCABULARY:
        raise ValueError(f"unit_vocabulary must be {UNIT_VOCABULARY!r}")
    dataset = sidecar["dataset"]
    if not isinstance(dataset, dict) or set(dataset) != {"name", "file_type", "schema_fingerprint"}:
        raise ValueError("Variable-unit metadata dataset must contain name, file_type, and schema_fingerprint")
    if dataset["schema_fingerprint"] != _schema_fingerprint(targets):
        raise ValueError("Variable-unit metadata schema fingerprint does not match the dataset")
    if not isinstance(sidecar["variables"], list):
        raise ValueError("Variable-unit metadata variables must be an array")

    resolutions = {}
    for variable in sidecar["variables"]:
        if not isinstance(variable, dict):
            raise ValueError("Each variable-unit metadata entry must be an object")
        fields = {"name", "target_type", "dtype", "observed", "resolution", "finding"}
        if set(variable) != fields:
            raise ValueError(f"Variable-unit metadata entries must contain exactly {sorted(fields)}")
        name = variable.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Variable-unit metadata names must be non-empty strings")
        if name in resolutions:
            raise ValueError(f"Duplicate variable-unit metadata entry: {name!r}")
        resolutions[name] = _validate_resolution(name, variable.get("resolution"))

    target_names = {target["name"] for target in targets}
    supplied_names = set(resolutions)
    if supplied_names != target_names:
        missing = sorted(target_names - supplied_names)
        unknown = sorted(supplied_names - target_names)
        raise ValueError(f"Variable-unit metadata variables do not match the dataset; missing={missing}, unknown={unknown}")
    return resolutions


def _detected_resolution(candidate: Dict[str, Any], parsed: Dict[str, Any]) -> Dict[str, Any]:
    kind = "dimensionless" if parsed["status"] == "dimensionless" else "unit"
    return {"kind": kind, "unit": candidate["unit"], "source": "detected"}


def _is_current_detected_resolution(
    resolution: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> bool:
    if resolution.get("source") != "detected" or resolution.get("kind") not in {"unit", "dimensionless"}:
        return False
    return any(resolution["unit"] == candidate["unit"] for candidate in candidates)


def _record_for_target(
    target: Dict[str, Any],
    supplied_resolution: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    candidates = list(target.get("unit_candidates", []))
    parsed_candidates = [(candidate, _parse_unit(candidate["unit"])) for candidate in candidates]
    observed = [_public_observation(candidate, parsed) for candidate, parsed in parsed_candidates]
    warnings = []
    explicit = supplied_resolution
    if explicit and explicit["kind"] == "unresolved":
        explicit = None
    if explicit and _is_current_detected_resolution(explicit, candidates):
        explicit = None

    if explicit is not None:
        if explicit["kind"] == "not_applicable":
            chosen = {
                "status": "not_applicable",
                "normalized_unit": None,
                "dimensionality": None,
                "message": "Variable is explicitly classified as not applicable.",
            }
            resolution = {"kind": "not_applicable", "source": "user"}
        else:
            unit = "1" if explicit["kind"] == "dimensionless" else explicit["unit"]
            chosen = _parse_unit(unit)
            kind = "dimensionless" if chosen["status"] == "dimensionless" else "unit"
            resolution = {"kind": kind, "unit": unit, "source": "user"}
        if candidates:
            warnings.append("User resolution overrides detected unit metadata.")
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
                "normalized_unit": chosen.get("normalized_unit"),
                "dimensionality": chosen.get("dimensionality"),
                "message": "Detected unit declarations conflict; add a user resolution.",
            }
        resolution = _detected_resolution(chosen_candidate, chosen)
    else:
        chosen = {
            "status": "missing",
            "normalized_unit": None,
            "dimensionality": None,
            "message": "No unit metadata was detected. Add a unit, mark the variable dimensionless, or mark units not applicable.",
        }
        resolution = {"kind": "unresolved", "source": "none"}

    status = chosen["status"]
    return {
        "name": target["name"],
        "target_type": target.get("target_type", "column"),
        "dtype": target.get("dtype", "unknown"),
        "observed": observed,
        "resolution": resolution,
        "finding": {
            "status": status,
            "readiness": "ready" if status in _READY_STATUSES else "not_ready",
            "normalized_unit": chosen.get("normalized_unit"),
            "dimensionality": chosen.get("dimensionality"),
            "message": chosen["message"],
            "warnings": warnings,
        },
    }


def _summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
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
        counts[record["finding"]["status"]] += 1

    total = counts["total"]
    accounted = total - counts["missing"]
    ready = counts["valid"] + counts["dimensionless"] + counts["not_applicable"]
    applicable = total - counts["not_applicable"]
    valid_applicable = counts["valid"] + counts["dimensionless"]
    return {
        "counts": counts,
        "classification_coverage": None if total == 0 else accounted / total,
        "applicable_unit_coverage": None if total == 0 else (1.0 if applicable == 0 else valid_applicable / applicable),
        "metadata_validity": None if accounted == 0 else ready / accounted,
        "all_variables_ready": bool(total and ready == total),
    }


def calculate_variable_unit_validation(
    file_info: tuple,
    unit_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a complete, validated unit-metadata sidecar for a dataset."""
    targets = discover_variable_units(file_info)
    resolutions = _validate_sidecar(unit_metadata, targets)
    records = [_record_for_target(target, resolutions.get(target["name"])) for target in targets]
    return {
        "format": SIDECAR_FORMAT,
        "version": SIDECAR_VERSION,
        "unit_vocabulary": UNIT_VOCABULARY,
        "dataset": {
            "name": str(file_info[1] or Path(file_info[0]).name),
            "file_type": str(file_info[2] or "").lower(),
            "schema_fingerprint": _schema_fingerprint(targets),
        },
        "variables": records,
        "summary": _summarize(records),
    }


@shared_task(ignore_result=False)
def variable_unit_validation(file_info: tuple, unit_metadata: Optional[Dict[str, Any]] = None):
    """Celery task wrapper for the variable-unit metadata audit."""
    return calculate_variable_unit_validation(file_info, unit_metadata)


__all__ = [
    "SIDECAR_FORMAT",
    "SIDECAR_VERSION",
    "UNIT_VOCABULARY",
    "calculate_variable_unit_validation",
    "discover_variable_units",
    "variable_unit_validation",
]
