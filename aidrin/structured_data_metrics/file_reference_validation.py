import errno
import math
import os
import stat
from datetime import datetime, timezone

import pandas as pd
from celery import shared_task

from aidrin.file_handling.value_iterators import (
    iter_indexed_values,
    iter_targets,
    iter_value_blocks,
    mask_lookup,
)


DESCRIPTION = "Validates dataset values as references to regular files on the execution host."
_STRING_DTYPES = {"object", "string", "str", "category", "bytes"}


def _non_negative_int(value, default, field):
    if value is None or value == "":
        return default
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative integer") from exc
    if normalized < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return normalized


def _normalize_targets(path_targets):
    if isinstance(path_targets, str):
        values = path_targets.split(",")
    elif isinstance(path_targets, (list, tuple, set)):
        values = path_targets
    elif path_targets is None:
        values = []
    else:
        values = [path_targets]

    normalized = []
    seen = set()
    for value in values:
        name = str(value).strip()
        if name and name not in seen:
            seen.add(name)
            normalized.append(name)
    if not normalized:
        raise ValueError("path_targets must contain at least one target")
    return normalized


def _stat_directory(path, field):
    try:
        result = os.stat(path)
    except OSError as exc:
        raise ValueError(f"{field} is not a readable directory: {path}") from exc
    if not stat.S_ISDIR(result.st_mode):
        raise ValueError(f"{field} is not a directory: {path}")


def _canonical_directory(path, field):
    try:
        expanded = os.path.expanduser(os.fspath(path))
        canonical = os.path.realpath(os.path.abspath(expanded))
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    _stat_directory(canonical, field)
    return canonical


def _prepare_directories(file_info, base_dir, allowed_roots):
    if not isinstance(file_info, (list, tuple)) or not file_info or not file_info[0]:
        raise ValueError("file_info must include a dataset path")

    default_base = os.path.dirname(os.path.realpath(os.path.abspath(os.fspath(file_info[0]))))
    canonical_base = _canonical_directory(base_dir if base_dir is not None else default_base, "base_dir")

    if allowed_roots is None:
        return canonical_base, None

    roots = []
    seen = set()
    for root in allowed_roots:
        canonical = _canonical_directory(root, "allowed_roots entry")
        key = os.path.normcase(canonical)
        if key not in seen:
            seen.add(key)
            roots.append(canonical)

    if not _is_within_roots(canonical_base, roots):
        raise ValueError("base_dir must be inside an allowed root")
    return canonical_base, roots


def _is_within_roots(path, roots):
    if roots is None:
        return True
    normalized_path = os.path.normcase(os.path.realpath(path))
    for root in roots:
        normalized_root = os.path.normcase(os.path.realpath(root))
        try:
            if os.path.commonpath([normalized_path, normalized_root]) == normalized_root:
                return True
        except ValueError:
            continue
    return False


def _target_is_string_capable(target):
    dtype = str(target.get("dtype", "")).strip()
    lowered = dtype.lower()
    if lowered in _STRING_DTYPES:
        return True
    if any(token in lowered for token in ("string", "bytes", "unicode")):
        return True
    return dtype.startswith(("|S", "<S", ">S", "|U", "<U", ">U"))


def _target_size(target):
    shape = target.get("shape")
    if shape is None:
        return 0
    if len(shape) == 0:
        return 1
    return int(math.prod(int(dimension) for dimension in shape))


def _timestamp(value):
    return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _owner_name(stat_result):
    try:
        import pwd

        return pwd.getpwuid(stat_result.st_uid).pw_name
    except (ImportError, KeyError, AttributeError, OSError):
        return None


def _creation_time(stat_result, os_name=None):
    if hasattr(stat_result, "st_birthtime"):
        return _timestamp(stat_result.st_birthtime), "birthtime"
    if (os_name or os.name) == "nt":
        return _timestamp(stat_result.st_ctime), "windows_ctime"
    return None, "unavailable"


def _lstat_target(path):
    return os.lstat(path)


def _stat_target(path):
    return os.stat(path)


def _failure(reason, message, normalized_value=None, resolved_path=None):
    return {
        "valid": False,
        "reason": reason,
        "message": message,
        "normalized_value": normalized_value,
        "resolved_path": resolved_path,
    }


def _os_failure(exc, is_symlink, normalized_value, resolved_path):
    if isinstance(exc, PermissionError) or exc.errno in {errno.EACCES, errno.EPERM}:
        return _failure("permission_denied", "Permission denied while inspecting the referenced path.", normalized_value, resolved_path)
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        reason = "broken_symlink" if is_symlink else "not_found"
        message = "The symbolic link target does not exist." if is_symlink else "The referenced path does not exist."
        return _failure(reason, message, normalized_value, resolved_path)
    if exc.errno == errno.ELOOP:
        return _failure("broken_symlink", "The symbolic link could not be resolved.", normalized_value, resolved_path)
    return _failure("invalid_path", "The referenced path could not be inspected.", normalized_value, resolved_path)


def _resolve_alias(reference, base_dir, allowed_roots, alias_cache, target_cache):
    if reference in alias_cache:
        return alias_cache[reference]

    if "\x00" in reference or "://" in reference:
        result = _failure("invalid_path", "The value is not a supported local file path.", reference)
        alias_cache[reference] = result
        return result

    try:
        expanded = os.path.expanduser(reference)
        joined = expanded if os.path.isabs(expanded) else os.path.join(base_dir, expanded)
        absolute_alias = os.path.abspath(joined)
        resolved_path = os.path.realpath(absolute_alias)
        alias_key = os.path.normcase(os.path.normpath(absolute_alias))
        target_key = os.path.normcase(resolved_path)
    except (TypeError, ValueError, OSError):
        result = _failure("invalid_path", "The value could not be resolved as a local file path.", reference)
        alias_cache[reference] = result
        return result

    if not _is_within_roots(resolved_path, allowed_roots):
        result = _failure(
            "outside_allowed_root",
            "The referenced path is outside the configured allowed roots.",
            reference,
            resolved_path,
        )
        alias_cache[reference] = result
        return result

    try:
        alias_stat = _lstat_target(absolute_alias)
    except OSError as exc:
        result = _os_failure(exc, False, reference, resolved_path)
        alias_cache[reference] = result
        return result

    is_symlink = stat.S_ISLNK(alias_stat.st_mode)
    cached_target = target_cache.get(target_key)
    if cached_target is not None:
        result = dict(cached_target)
        result["referenced_via_symlink"] = is_symlink
        result["alias_key"] = alias_key
        alias_cache[reference] = result
        return result

    try:
        target_stat = _stat_target(absolute_alias)
    except OSError as exc:
        result = _os_failure(exc, is_symlink, reference, resolved_path)
        alias_cache[reference] = result
        return result

    if not stat.S_ISREG(target_stat.st_mode):
        result = _failure("not_a_file", "The referenced path is not a regular file.", reference, resolved_path)
        alias_cache[reference] = result
        return result

    created_at, created_at_source = _creation_time(target_stat)
    metadata = {
        "resolved_path": resolved_path,
        "occurrences": 0,
        "size_bytes": int(target_stat.st_size),
        "owner_name": _owner_name(target_stat),
        "created_at": created_at,
        "created_at_source": created_at_source,
        "modified_at": _timestamp(target_stat.st_mtime),
        "referenced_via_symlink": False,
    }
    target_result = {
        "valid": True,
        "resolved_path": resolved_path,
        "target_key": target_key,
        "metadata": metadata,
    }
    target_cache[target_key] = target_result
    result = dict(target_result)
    result["referenced_via_symlink"] = is_symlink
    result["alias_key"] = alias_key
    alias_cache[reference] = result
    return result


def _new_target_summary(target):
    return {
        "target_type": target["target_type"],
        "candidate_values": _target_size(target),
        "scanned_values": 0,
        "unscanned_values": _target_size(target),
        "scan_complete": False,
        "valid_references": 0,
        "invalid_references": 0,
        "missing_references": 0,
        "validity_rate": 0.0,
    }


def _is_missing(value, lookup, index_tuple):
    if lookup is not None and lookup(index_tuple):
        return True
    try:
        missing = pd.isna(value)
        return bool(missing) if not hasattr(missing, "shape") or missing.shape == () else False
    except (TypeError, ValueError):
        return False


def calculate_file_reference_validation(
    file_info,
    path_targets,
    base_dir=None,
    max_results=100,
    scan_limit=None,
    allowed_roots=None,
):
    path_targets = _normalize_targets(path_targets)
    max_results = _non_negative_int(max_results, 100, "max_results")
    scan_limit = _non_negative_int(scan_limit, None, "scan_limit")
    base_dir, allowed_roots = _prepare_directories(file_info, base_dir, allowed_roots)

    discovered = {target["name"]: target for target in iter_targets(file_info)}
    selected = []
    errors = []
    target_summaries = {}

    for name in path_targets:
        target = discovered.get(name)
        if target is None:
            errors.append({"target": name, "error": f"Target not found: {name}"})
            continue
        if not _target_is_string_capable(target):
            errors.append({"target": name, "error": f"Target must contain string file paths; found dtype {target.get('dtype', 'unknown')}"})
            continue
        selected.append(target)
        target_summaries[name] = _new_target_summary(target)

    candidate_values = sum(summary["candidate_values"] for summary in target_summaries.values())
    invalid_details = []
    unique_reference_values = set()
    unique_resolved_paths = set()
    alias_cache = {}
    target_cache = {}
    scanned_values = 0

    for target in selected:
        name = target["name"]
        summary = target_summaries[name]
        if scan_limit and scanned_values >= scan_limit:
            break
        try:
            for block in iter_value_blocks(file_info, target):
                missing_lookup = mask_lookup(block["missing_mask"]) if "missing_mask" in block else None
                for index_tuple, value in iter_indexed_values(block["values"]):
                    if scan_limit and scanned_values >= scan_limit:
                        break

                    scanned_values += 1
                    summary["scanned_values"] += 1
                    location = block["locate"](index_tuple)

                    if _is_missing(value, missing_lookup, index_tuple):
                        summary["missing_references"] += 1
                        continue

                    if isinstance(value, bytes):
                        try:
                            original_value = value.decode("utf-8")
                        except UnicodeDecodeError:
                            summary["invalid_references"] += 1
                            if max_results == 0 or len(invalid_details) < max_results:
                                invalid_details.append({
                                    "target": name,
                                    "target_type": target["target_type"],
                                    "location": location,
                                    "value": repr(value),
                                    "normalized_value": None,
                                    "resolved_path": None,
                                    "reason": "unsupported_value",
                                    "message": "The byte value is not valid UTF-8.",
                                })
                            continue
                    elif isinstance(value, str):
                        original_value = value
                    else:
                        summary["invalid_references"] += 1
                        if max_results == 0 or len(invalid_details) < max_results:
                            invalid_details.append({
                                "target": name,
                                "target_type": target["target_type"],
                                "location": location,
                                "value": repr(value),
                                "normalized_value": None,
                                "resolved_path": None,
                                "reason": "unsupported_value",
                                "message": "The value is not a string file path.",
                            })
                        continue

                    normalized_value = original_value.strip()
                    if not normalized_value:
                        summary["missing_references"] += 1
                        continue

                    unique_reference_values.add(normalized_value)
                    result = _resolve_alias(normalized_value, base_dir, allowed_roots, alias_cache, target_cache)
                    if result.get("resolved_path"):
                        unique_resolved_paths.add(os.path.normcase(result["resolved_path"]))

                    if result["valid"]:
                        summary["valid_references"] += 1
                        metadata = result["metadata"]
                        metadata["occurrences"] += 1
                        metadata["referenced_via_symlink"] = (
                            metadata["referenced_via_symlink"] or result.get("referenced_via_symlink", False)
                        )
                    else:
                        summary["invalid_references"] += 1
                        if max_results == 0 or len(invalid_details) < max_results:
                            invalid_details.append({
                                "target": name,
                                "target_type": target["target_type"],
                                "location": location,
                                "value": original_value,
                                "normalized_value": normalized_value,
                                "resolved_path": result.get("resolved_path"),
                                "reason": result["reason"],
                                "message": result["message"],
                            })

                if scan_limit and scanned_values >= scan_limit:
                    break
        except Exception as exc:
            errors.append({"target": name, "error": str(exc)})

    valid_references = 0
    invalid_references = 0
    missing_references = 0
    for summary in target_summaries.values():
        summary["unscanned_values"] = max(0, summary["candidate_values"] - summary["scanned_values"])
        summary["scan_complete"] = summary["unscanned_values"] == 0
        summary["validity_rate"] = (
            summary["valid_references"] / summary["scanned_values"] if summary["scanned_values"] else 0.0
        )
        valid_references += summary["valid_references"]
        invalid_references += summary["invalid_references"]
        missing_references += summary["missing_references"]

    metadata = [result["metadata"] for result in target_cache.values()]
    metadata_details_truncated = max_results != 0 and len(metadata) > max_results
    if max_results:
        metadata = metadata[:max_results]

    unscanned_values = max(0, candidate_values - scanned_values)
    scan_complete = unscanned_values == 0
    summary = {
        "candidate_values": candidate_values,
        "scanned_values": scanned_values,
        "unscanned_values": unscanned_values,
        "scan_limit": scan_limit,
        "scan_complete": scan_complete,
        "valid_references": valid_references,
        "invalid_references": invalid_references,
        "missing_references": missing_references,
        "unique_reference_values": len(unique_reference_values),
        "unique_resolved_paths": len(unique_resolved_paths),
        "unique_valid_files": len(target_cache),
        "validity_rate": valid_references / scanned_values if scanned_values else 0.0,
        "all_references_valid": (
            scan_complete
            and scanned_values > 0
            and invalid_references == 0
            and missing_references == 0
            and not errors
        ),
        "invalid_details_truncated": max_results != 0 and invalid_references > len(invalid_details),
        "metadata_details_truncated": metadata_details_truncated,
    }

    return {
        "Description": DESCRIPTION,
        "Summary": summary,
        "Target summaries": target_summaries,
        "Invalid references": invalid_details,
        "File metadata": metadata,
        "Errors": errors,
    }


@shared_task(bind=True, ignore_result=False)
def file_reference_validation(
    self,
    path_targets,
    file_info,
    base_dir=None,
    max_results=100,
    scan_limit=None,
    allowed_roots=None,
):
    return calculate_file_reference_validation(
        file_info,
        path_targets,
        base_dir=base_dir,
        max_results=max_results,
        scan_limit=scan_limit,
        allowed_roots=allowed_roots,
    )
