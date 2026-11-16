"""Read deployment-managed formats without importing their trusted Python code."""

import json
import os
from pathlib import Path
import re

from aidrin.file_handling.custom_loader import CustomLoaderError, parse_loader_spec


def read_registered_loaders(registry_path):
    """Load a JSON list of named formats. Relative scripts resolve beside the JSON.

    Only administrators should be able to modify this file or its scripts. Reading
    the registry never imports a loader; execution happens only when loading data.
    """
    if not registry_path:
        return {}
    path = Path(registry_path).resolve()
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("Registered loaders must be a JSON list")
    formats = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each registered loader must be an object")
        identifier = entry.get("id", "")
        name = entry.get("name", "")
        extensions = entry.get("extensions", [])
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", identifier):
            raise ValueError("Registered loader id must use lowercase letters, digits, underscores or hyphens")
        if identifier in formats:
            raise ValueError(f"Duplicate registered loader id: {identifier}")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError(f"Registered loader {identifier} needs a name of 1-100 characters")
        if not isinstance(extensions, list) or not extensions or any(
            not isinstance(ext, str) or not re.fullmatch(r"\.[a-z0-9][a-z0-9._-]*", ext) for ext in extensions
        ):
            raise ValueError(f"Registered loader {identifier} needs lowercase dotted extensions")
        module, function = parse_loader_spec(entry.get("loader"))
        if module.endswith(".py"):
            script = Path(module)
            if not script.is_absolute():
                script = path.parent / script
            module = str(script.resolve())
        formats[identifier] = {
            "name": name.strip(),
            "extensions": extensions,
            "loader": f"{module}:{function}",
        }
    return formats


def resolve_registered_loader(spec, file_path, registry_path=None):
    """Resolve ``registered:<id>`` through the registry shared by web, CLI and API.

    Without an explicit path, use ``AIDRIN_REGISTERED_LOADERS_FILE``. Built-in
    readers are never overridden implicitly by extension.
    """
    path = registry_path if registry_path is not None else os.environ.get("AIDRIN_REGISTERED_LOADERS_FILE")
    try:
        formats = read_registered_loaders(path)
        entry = formats.get(spec.removeprefix("registered:"))
        if entry is None:
            raise ValueError(f"Unknown registered format: {spec}. Check AIDRIN_REGISTERED_LOADERS_FILE.")
        if not any(str(file_path).lower().endswith(ext) for ext in entry["extensions"]):
            raise ValueError(f"File extension does not match {spec}: expected {', '.join(entry['extensions'])}")
        return entry["loader"]
    except (OSError, ValueError) as exc:
        raise CustomLoaderError(f"Cannot resolve {spec}: {exc}") from exc
