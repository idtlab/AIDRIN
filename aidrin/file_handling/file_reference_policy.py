"""Filesystem policy shared by local Web and remote Compute execution."""

import json
import logging
import os


DEFAULT_SCAN_LIMIT = 10000
ALLOWED_ROOTS_ENV = "AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS"
SCAN_LIMIT_ENV = "AIDRIN_FILE_REFERENCE_WEB_SCAN_LIMIT"

logger = logging.getLogger(__name__)


def allowed_roots(configured=None):
    """Return unique canonical roots from explicit config or the environment."""
    if configured is None:
        raw = os.environ.get(ALLOWED_ROOTS_ENV, "")
        if raw:
            try:
                configured = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("%s must be a JSON array", ALLOWED_ROOTS_ENV)
                configured = []

    if not isinstance(configured, (list, tuple)):
        if configured is not None:
            logger.warning("File-reference allowed roots must be a list of absolute directories")
        return []

    roots = []
    seen = set()
    for value in configured:
        try:
            path = os.fspath(value)
            if not os.path.isabs(path):
                raise ValueError("not absolute")
            canonical = os.path.realpath(path)
            if not os.path.isdir(canonical):
                raise ValueError("not an existing directory")
        except (TypeError, ValueError, OSError) as exc:
            logger.warning("Ignoring invalid file-reference root %r: %s", value, exc)
            continue
        key = os.path.normcase(canonical)
        if key not in seen:
            seen.add(key)
            roots.append(canonical)
    return roots


def scan_limit(configured=None):
    """Return the positive administrator scan cap."""
    value = configured
    if value is None:
        value = os.environ.get(SCAN_LIMIT_ENV, DEFAULT_SCAN_LIMIT)
    try:
        limit = int(value)
        if limit <= 0:
            raise ValueError
    except (TypeError, ValueError):
        logger.warning("Invalid file-reference scan limit %r; using %d", value, DEFAULT_SCAN_LIMIT)
        return DEFAULT_SCAN_LIMIT
    return limit


def root_choices(roots):
    """Return opaque browser choices for canonical roots."""
    return [{"id": f"root-{index}", "label": root} for index, root in enumerate(roots)]


def resolve_base_dir(roots, root_id, subdirectory):
    """Resolve a selected relative subdirectory without escaping its root."""
    choices = {f"root-{index}": root for index, root in enumerate(roots)}
    if root_id not in choices:
        raise ValueError("Select an allowed filesystem root.")
    root = choices[root_id]
    relative = (subdirectory or "").strip()
    if os.path.isabs(relative):
        raise ValueError("Base subdirectory must be relative to the selected root.")

    candidate = os.path.realpath(os.path.join(root, relative))
    try:
        inside_root = os.path.commonpath([
            os.path.normcase(candidate),
            os.path.normcase(root),
        ]) == os.path.normcase(root)
    except ValueError:
        inside_root = False
    if not inside_root:
        raise ValueError("Base subdirectory must stay inside the selected root.")
    if not os.path.isdir(candidate):
        raise ValueError("Base subdirectory must identify an existing directory.")
    return candidate


def discovery_configuration(configured_roots=None, configured_scan_limit=None):
    """Build the public discovery payload without accepting browser policy."""
    roots = allowed_roots(configured_roots)
    result = {
        "enabled": bool(roots),
        "roots": root_choices(roots),
        "scan_limit": scan_limit(configured_scan_limit),
    }
    if not roots:
        result["message"] = "File-reference validation is not configured by the administrator."
    return result
