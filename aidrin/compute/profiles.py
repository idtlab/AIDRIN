"""Named Globus Compute endpoint profiles for headless AIDRIN.

Storage only. This module imports no Globus code, so it works with the SDK
absent and can be unit-tested without credentials.

Two files participate:

* user     ``~/.aidrin/config.json``  (override the directory with AIDRIN_CONFIG_DIR)
* project  ``./.aidrin.json``         (written by ``configure --local``)

Project profiles shadow user profiles of the same name, and a project default
wins over a user default.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

ENV_ENDPOINT = "AIDRIN_GLOBUS_ENDPOINT"
ENV_CONFIG_DIR = "AIDRIN_CONFIG_DIR"
PROJECT_FILENAME = ".aidrin.json"


class ProfileError(Exception):
    """Raised when an endpoint cannot be resolved or a profile is unknown."""


@dataclass
class RemoteTarget:
    """A resolved endpoint and where it came from."""

    endpoint: str
    profile: Optional[str]
    source: str  # "flag" | "profile" | "env" | "project" | "user"
    aidrin_version: Optional[str] = None


def user_config_path() -> Path:
    base = os.environ.get(ENV_CONFIG_DIR)
    return (Path(base) if base else Path.home() / ".aidrin") / "config.json"


def project_config_path() -> Path:
    return Path.cwd() / PROJECT_FILENAME


def _load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"default": None, "profiles": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProfileError(f"Could not read {path}: {exc}") from exc
    data.setdefault("default", None)
    data.setdefault("profiles", {})
    return data


def _write(path: Path, data: Dict[str, Any]) -> None:
    """Write ``data`` to ``path`` at mode 0600, with no window where the
    content is on disk at a wider mode.

    A plain ``write_text`` followed by ``chmod`` creates the file (or
    truncates an existing one) at the process umask first, so the full
    content is briefly readable at whatever mode the file already had.
    Instead, write to a sibling temp file created at 0600 and atomically
    rename it into place; the destination inherits the temp file's mode.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        os.chmod(tmp_name, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_profile(
    name: str,
    endpoint: str,
    *,
    default: bool = False,
    local: bool = False,
    aidrin_version: Optional[str] = None,
) -> Path:
    """Store an endpoint under ``name``. Returns the file written."""
    path = project_config_path() if local else user_config_path()
    data = _load(path)
    data["profiles"][name] = {
        "endpoint": endpoint,
        "aidrin_version": aidrin_version,
    }
    if default or data.get("default") is None:
        data["default"] = name
    _write(path, data)
    return path


def remove_profile(name: str, *, local: bool = False) -> bool:
    """Delete a profile. Returns False if it was not there."""
    path = project_config_path() if local else user_config_path()
    data = _load(path)
    if name not in data["profiles"]:
        return False
    del data["profiles"][name]
    if data.get("default") == name:
        data["default"] = None
    _write(path, data)
    return True


def list_profiles() -> Dict[str, Any]:
    """Merged view of both files. Project entries shadow user entries."""
    user = _load(user_config_path())
    project = _load(project_config_path())
    profiles: Dict[str, Any] = dict(user["profiles"])
    profiles.update(project["profiles"])
    return {
        "default": project.get("default") or user.get("default"),
        "profiles": profiles,
    }


def resolve(
    endpoint: Optional[str] = None, profile: Optional[str] = None
) -> RemoteTarget:
    """Resolve an endpoint UUID, first hit wins.

    flag > named profile > AIDRIN_GLOBUS_ENDPOINT > stored default.
    """
    if endpoint:
        return RemoteTarget(endpoint=endpoint, profile=profile, source="flag")

    merged = list_profiles()

    if profile:
        entry = merged["profiles"].get(profile)
        if entry is None:
            known = ", ".join(sorted(merged["profiles"])) or "none configured"
            raise ProfileError(
                f"Unknown profile: {profile}. Known profiles: {known}"
            )
        return RemoteTarget(
            endpoint=entry["endpoint"],
            profile=profile,
            source="profile",
            aidrin_version=entry.get("aidrin_version"),
        )

    env_endpoint = os.environ.get(ENV_ENDPOINT)
    if env_endpoint:
        return RemoteTarget(endpoint=env_endpoint, profile=None, source="env")

    # Project and user defaults are independent fallback candidates. A
    # dangling default (e.g. from hand-editing one file to name a profile
    # that isn't defined anywhere) falls through to the next candidate
    # rather than aborting resolution.
    project_default = _load(project_config_path()).get("default")
    user_default = _load(user_config_path()).get("default")
    for default_name, source in (
        (project_default, "project"),
        (user_default, "user"),
    ):
        if not default_name:
            continue
        entry = merged["profiles"].get(default_name)
        if entry is None:
            continue
        return RemoteTarget(
            endpoint=entry["endpoint"],
            profile=default_name,
            source=source,
            aidrin_version=entry.get("aidrin_version"),
        )

    raise ProfileError(
        "No Globus Compute endpoint configured. Provide one of, in order of "
        "precedence: --endpoint <uuid>, --profile <name>, the "
        f"{ENV_ENDPOINT} environment variable, or a stored default from "
        "'aidrin remote configure --name <name> --endpoint <uuid>'."
    )
