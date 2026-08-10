# Globus Remote Execution for the CLI, MCP, and Skill: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `aidrin remote summarize /scratch/data.csv` run an AIDRIN metric on a configured Globus Compute endpoint and print the same JSON a local run would, with the endpoint remembered between invocations.

**Architecture:** A new remote entry point (`remote_headless_runner`) is added to `aidrin/compute/remote.py`; it imports `aidrin.headless.api` on the endpoint and dispatches to the same four functions the local CLI calls, so local and remote share one metric registry. The CLI grows an `aidrin remote` prefix that strips its own flags from `argv` and re-uses the existing parser untouched, then swaps the local `api` module for a duck-typed `RemoteExecutor` exposing the same four function names.

**Tech Stack:** Python 3.12, argparse, `globus-compute-sdk>=2.3.0`, `globus-sdk>=3.20.0` (already declared as the `globus` extra in `pyproject.toml`), pytest running `unittest`-style test classes.

**Spec:** `docs/superpowers/specs/2026-07-30-globus-remote-cli-design.md`

## Global Constraints

- Base branch is `develop`. Work on `feature/globus-remote-cli`.
- Never add Claude or AI co-authorship trailers to commits.
- `aidrin remote` must **never** silently fall back to a local run. If the endpoint cannot be resolved or reached, fail with a non-zero exit.
- Progress and warnings go to **stderr**. Only result JSON goes to **stdout**, so stdout is byte-identical to a local run.
- A remote run never writes files on the endpoint: submissions always send `save_images=False`. Images are written on the client by the existing `_maybe_save_images`.
- Globus Compute caps a task result at roughly 10 MB. Remote submissions default to `strip_visualizations=True`.
- Default remote timeout: `600` seconds. Default poll interval: `2.0` seconds.
- Config files are written with mode `0600`.
- All new modules must import cleanly when `globus-compute-sdk` is **not** installed. Guard SDK imports inside functions or behind a try/except, following the existing pattern in `web/globus.py:19-30`.
- Error results from the remote worker use the `{"Error": ..., "ErrorType": ...}` convention already used by the local CLI and MCP server.
- Out of scope, and must fail with exit code 2 under `aidrin remote`: `run custom`, `agentic`, `add-custom-module`.

---

## File Structure

| File | Responsibility |
|---|---|
| `aidrin/compute/remote.py` (modify) | Code that executes **on** the endpoint. Add `remote_headless_runner`; extend `remote_env_probe`. |
| `aidrin/compute/profiles.py` (create) | Named-profile storage and endpoint resolution. No Globus imports at all. |
| `aidrin/compute/client.py` (create) | Globus Compute client: availability, login, register, probe, submit, poll, cancel. |
| `aidrin/compute/executor.py` (create) | `RemoteExecutor`, duck-typed against `aidrin.headless.api`. Bridges CLI/MCP to `client.py`. |
| `aidrin/headless/cli.py` (modify) | `aidrin remote` argv pre-parse, management subcommands, executor swap. |
| `aidrin/mcp/server.py` (modify) | Optional `endpoint`/`profile` on the run tools; `list_remote_profiles`. |
| `.claude/skills/aidrin/SKILL.md` (modify) | Teach the skill the remote path. |
| `docs/source/remote.rst` (create) | User-facing setup and usage. |

---

### Task 1: Remote entry point on the endpoint

**Files:**
- Modify: `aidrin/compute/remote.py` (append `remote_headless_runner`; extend `remote_env_probe`)
- Modify: `aidrin/compute/__init__.py`
- Test: `tests/unit/test_compute_remote_runner.py` (create)

**Interfaces:**
- Consumes: `aidrin.headless.api.{run_metric, summarize_dataset, run_data_quality, run_batch_metrics}` (existing).
- Produces: `remote_headless_runner(command: str, kwargs: dict) -> dict`, where `command` is one of `"run_metric"`, `"summarize"`, `"data_quality"`, `"batch"`. Returns the API result, or `{"Error": str, "ErrorType": str}`. `remote_env_probe() -> dict` gains a `"headless_import"` key (`True`, or the error string).

This function runs on the Globus Compute worker. Globus serialises a *reference* (module plus qualname) and the worker re-imports it, which is why it must live in the `aidrin` package rather than in `web`. Keep imports inside the body, matching `remote_metric_runner`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compute_remote_runner.py`:

```python
"""Unit tests for the headless remote entry point (aidrin.compute.remote).

These call remote_headless_runner directly. No Globus SDK and no endpoint are
involved: the point is to prove the remote path dispatches into the same
aidrin.headless.api functions the local CLI uses.
"""

import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from aidrin.compute.remote import remote_env_probe, remote_headless_runner


def _sample_csv() -> str:
    rng = np.random.default_rng(7)
    df = pd.DataFrame(
        {
            "age": rng.integers(20, 70, size=40),
            "income": rng.integers(20_000, 90_000, size=40),
            "sex": rng.choice(["M", "F"], size=40),
        }
    )
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return tmp.name


class TestRemoteHeadlessRunner(unittest.TestCase):

    def setUp(self):
        self.path = _sample_csv()

    def tearDown(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def test_summarize_dispatches_to_api(self):
        result = remote_headless_runner("summarize", {"file_path": self.path})
        self.assertEqual(result["columns"], ["age", "income", "sex"])
        self.assertEqual(result["shape"]["rows"], 40)

    def test_run_metric_dispatches_to_api(self):
        result = remote_headless_runner(
            "run_metric",
            {"metric_name": "completeness", "file_path": self.path, "save_images": False},
        )
        self.assertIn("Completeness scores", result)

    def test_data_quality_dispatches_to_api(self):
        result = remote_headless_runner("data_quality", {"file_path": self.path})
        self.assertIn("completeness", result)

    def test_batch_dispatches_to_api(self):
        result = remote_headless_runner(
            "batch",
            {"config": {"file_path": self.path, "metrics": ["completeness"], "save_images": False}},
        )
        self.assertIn("completeness", result)

    def test_unknown_command_returns_error_dict(self):
        result = remote_headless_runner("nope", {})
        self.assertEqual(result["ErrorType"], "UnknownCommand")
        self.assertIn("nope", result["Error"])

    def test_exception_is_returned_not_raised(self):
        result = remote_headless_runner(
            "summarize", {"file_path": "/definitely/missing/file.csv"}
        )
        self.assertIn("Error", result)
        self.assertIn("ErrorType", result)


class TestRemoteEnvProbe(unittest.TestCase):

    def test_probe_reports_headless_import(self):
        result = remote_env_probe()
        self.assertIn("aidrin_version", result)
        self.assertIn("python_version", result)
        self.assertIs(result["headless_import"], True)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. pytest tests/unit/test_compute_remote_runner.py -v`
Expected: FAIL with `ImportError: cannot import name 'remote_headless_runner'`.

- [ ] **Step 3: Append the implementation to `aidrin/compute/remote.py`**

```python
def remote_headless_runner(command, kwargs):
    """Execute an ``aidrin.headless.api`` call on the remote endpoint.

    Runs ON the Globus Compute endpoint. ``remote_metric_runner`` speaks the
    web app's metric vocabulary; this one speaks the headless API's, so the CLI
    and MCP server need no name translation and there stays exactly one metric
    registry governing both local and remote runs.

    Parameters
    ----------
    command : str
        One of ``run_metric``, ``summarize``, ``data_quality``, ``batch``.
    kwargs : dict
        Keyword arguments forwarded verbatim to the matching API function.

    Returns
    -------
    dict
        The API result, or ``{"Error": ..., "ErrorType": ...}``. Errors are
        returned rather than raised, matching the convention the local CLI and
        MCP server already use.
    """
    import matplotlib

    matplotlib.use("Agg")

    from aidrin.headless import api

    dispatch = {
        "run_metric": api.run_metric,
        "summarize": api.summarize_dataset,
        "data_quality": api.run_data_quality,
        "batch": api.run_batch_metrics,
    }

    fn = dispatch.get(command)
    if fn is None:
        return {
            "Error": f"Unknown remote command: {command}",
            "ErrorType": "UnknownCommand",
        }

    try:
        return fn(**(kwargs or {}))
    except Exception as exc:
        return {"Error": str(exc), "ErrorType": type(exc).__name__}
```

- [ ] **Step 4: Extend `remote_env_probe` in the same file**

Replace the `return` block of `remote_env_probe` with:

```python
    try:
        import aidrin.headless.api  # noqa: F401

        headless_import = True
    except Exception as exc:
        headless_import = f"{type(exc).__name__}: {exc}"

    return {
        "aidrin_version": aidrin.__version__,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "headless_import": headless_import,
    }
```

`remote_headless_runner` is resolved on the worker by importing `aidrin.headless.api`, so the probe must prove that exact import works, not just that `aidrin` imports.

- [ ] **Step 5: Export it from `aidrin/compute/__init__.py`**

```python
from aidrin.compute.remote import (
    remote_env_probe,
    remote_headless_runner,
    remote_metric_runner,
)

__all__ = ["remote_metric_runner", "remote_env_probe", "remote_headless_runner"]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/test_compute_remote_runner.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 7: Verify nothing in the web path regressed**

Run: `PYTHONPATH=. pytest tests/integration/test_globus.py -v`
Expected: PASS (or skips where the SDK is absent). `remote_metric_runner` is untouched.

- [ ] **Step 8: Commit**

```bash
git add aidrin/compute/remote.py aidrin/compute/__init__.py tests/unit/test_compute_remote_runner.py
git commit -m "feat(compute): add headless remote entry point for Globus Compute"
```

---

### Task 2: Named endpoint profiles

**Files:**
- Create: `aidrin/compute/profiles.py`
- Test: `tests/unit/test_compute_profiles.py` (create)

**Interfaces:**
- Consumes: nothing. This module imports no Globus code and must work with the SDK absent.
- Produces:
  - `class ProfileError(Exception)`
  - `@dataclass RemoteTarget: endpoint: str; profile: str | None; source: str; aidrin_version: str | None = None`
  - `user_config_path() -> pathlib.Path`
  - `project_config_path() -> pathlib.Path`
  - `save_profile(name, endpoint, *, default=False, local=False, aidrin_version=None) -> pathlib.Path`
  - `remove_profile(name, *, local=False) -> bool`
  - `list_profiles() -> dict` with keys `default`, `profiles`
  - `resolve(endpoint=None, profile=None) -> RemoteTarget` (raises `ProfileError`)

Resolution order, first hit wins: `endpoint` argument, `profile` argument, `AIDRIN_GLOBUS_ENDPOINT`, project file default, user file default.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compute_profiles.py`:

```python
"""Unit tests for endpoint profile storage and resolution."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aidrin.compute import profiles


class _ProfileTestCase(unittest.TestCase):
    """Redirects both config locations into temp dirs for every test."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.project = tempfile.mkdtemp()
        self._env = patch.dict(
            os.environ, {"AIDRIN_CONFIG_DIR": self.home}, clear=False
        )
        self._env.start()
        os.environ.pop("AIDRIN_GLOBUS_ENDPOINT", None)
        self._cwd = patch.object(Path, "cwd", staticmethod(lambda: Path(self.project)))
        self._cwd.start()

    def tearDown(self):
        self._cwd.stop()
        self._env.stop()


class TestSaveAndList(_ProfileTestCase):

    def test_save_creates_user_config(self):
        path = profiles.save_profile("nersc", "uuid-1", default=True, aidrin_version="0.9.2")
        self.assertEqual(path, Path(self.home) / "config.json")
        data = json.loads(path.read_text())
        self.assertEqual(data["default"], "nersc")
        self.assertEqual(data["profiles"]["nersc"]["endpoint"], "uuid-1")
        self.assertEqual(data["profiles"]["nersc"]["aidrin_version"], "0.9.2")

    def test_config_file_is_owner_only(self):
        path = profiles.save_profile("nersc", "uuid-1")
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_first_profile_becomes_default_without_flag(self):
        profiles.save_profile("nersc", "uuid-1")
        self.assertEqual(profiles.list_profiles()["default"], "nersc")

    def test_second_profile_does_not_steal_default(self):
        profiles.save_profile("nersc", "uuid-1")
        profiles.save_profile("alcf", "uuid-2")
        self.assertEqual(profiles.list_profiles()["default"], "nersc")

    def test_local_writes_project_file(self):
        path = profiles.save_profile("lab", "uuid-3", local=True)
        self.assertEqual(path, Path(self.project) / ".aidrin.json")

    def test_list_merges_project_over_user(self):
        profiles.save_profile("nersc", "user-uuid")
        profiles.save_profile("nersc", "project-uuid", local=True)
        merged = profiles.list_profiles()
        self.assertEqual(merged["profiles"]["nersc"]["endpoint"], "project-uuid")


class TestRemove(_ProfileTestCase):

    def test_remove_returns_true_and_deletes(self):
        profiles.save_profile("nersc", "uuid-1")
        self.assertTrue(profiles.remove_profile("nersc"))
        self.assertNotIn("nersc", profiles.list_profiles()["profiles"])

    def test_remove_missing_returns_false(self):
        self.assertFalse(profiles.remove_profile("ghost"))

    def test_removing_default_clears_default(self):
        profiles.save_profile("nersc", "uuid-1", default=True)
        profiles.remove_profile("nersc")
        self.assertIsNone(profiles.list_profiles()["default"])


class TestResolve(_ProfileTestCase):

    def test_explicit_endpoint_wins(self):
        profiles.save_profile("nersc", "uuid-1", default=True)
        os.environ["AIDRIN_GLOBUS_ENDPOINT"] = "env-uuid"
        target = profiles.resolve(endpoint="flag-uuid", profile="nersc")
        self.assertEqual(target.endpoint, "flag-uuid")
        self.assertEqual(target.source, "flag")

    def test_named_profile_beats_env(self):
        profiles.save_profile("nersc", "uuid-1")
        os.environ["AIDRIN_GLOBUS_ENDPOINT"] = "env-uuid"
        target = profiles.resolve(profile="nersc")
        self.assertEqual(target.endpoint, "uuid-1")
        self.assertEqual(target.source, "profile")

    def test_env_beats_stored_default(self):
        profiles.save_profile("nersc", "uuid-1", default=True)
        os.environ["AIDRIN_GLOBUS_ENDPOINT"] = "env-uuid"
        target = profiles.resolve()
        self.assertEqual(target.endpoint, "env-uuid")
        self.assertEqual(target.source, "env")

    def test_falls_back_to_default_profile(self):
        profiles.save_profile("nersc", "uuid-1", default=True, aidrin_version="0.9.1")
        target = profiles.resolve()
        self.assertEqual(target.endpoint, "uuid-1")
        self.assertEqual(target.profile, "nersc")
        self.assertEqual(target.aidrin_version, "0.9.1")

    def test_unknown_profile_raises(self):
        with self.assertRaises(profiles.ProfileError) as ctx:
            profiles.resolve(profile="ghost")
        self.assertIn("ghost", str(ctx.exception))

    def test_nothing_configured_raises_with_guidance(self):
        with self.assertRaises(profiles.ProfileError) as ctx:
            profiles.resolve()
        message = str(ctx.exception)
        self.assertIn("aidrin remote configure", message)
        self.assertIn("AIDRIN_GLOBUS_ENDPOINT", message)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. pytest tests/unit/test_compute_profiles.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidrin.compute.profiles'`.

- [ ] **Step 3: Write the implementation**

Create `aidrin/compute/profiles.py`:

```python
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


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

    default_name = merged.get("default")
    if default_name and default_name in merged["profiles"]:
        entry = merged["profiles"][default_name]
        return RemoteTarget(
            endpoint=entry["endpoint"],
            profile=default_name,
            source="user",
            aidrin_version=entry.get("aidrin_version"),
        )

    raise ProfileError(
        "No Globus Compute endpoint configured. Provide one of, in order of "
        "precedence: --endpoint <uuid>, --profile <name>, the "
        f"{ENV_ENDPOINT} environment variable, or a stored default from "
        "'aidrin remote configure --name <name> --endpoint <uuid>'."
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/test_compute_profiles.py -v`
Expected: PASS, 16 tests.

- [ ] **Step 5: Commit**

```bash
git add aidrin/compute/profiles.py tests/unit/test_compute_profiles.py
git commit -m "feat(compute): add named endpoint profiles for headless remote runs"
```

---

### Task 3: Globus Compute client

**Files:**
- Create: `aidrin/compute/client.py`
- Test: `tests/unit/test_compute_client.py` (create)

**Interfaces:**
- Consumes: `aidrin.compute.remote.{remote_headless_runner, remote_env_probe}` from Task 1.
- Produces:
  - `class RemoteError(Exception)`
  - `class GlobusUnavailable(RemoteError)`
  - `class RemoteTimeout(RemoteError)` with attributes `task_id: str`, `timeout: float`
  - `is_available() -> bool`
  - `get_client()`
  - `register(client, force=False) -> str`
  - `check(client, task_id) -> dict` with keys `status` in `{"completed", "processing", "failed"}`, plus `result` or `error`
  - `poll(client, task_id, timeout=600.0, interval=2.0, sleep=time.sleep, now=time.monotonic) -> Any`
  - `submit(client, endpoint_id, command, kwargs) -> str`
  - `probe(client, endpoint_id, timeout=60.0) -> dict`
  - `cancel(client, task_id) -> None`

`poll` takes injectable `sleep` and `now` so tests never wait in real time.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compute_client.py`:

```python
"""Unit tests for the headless Globus Compute client.

A stub client stands in for globus_compute_sdk.Client, so no SDK, no
credentials, and no endpoint are needed.
"""

import unittest
from unittest.mock import patch

from aidrin.compute import client as compute_client


class _StubTaskPending(Exception):
    """Mimics the SDK's pending-task exception (message-matched, as in web/globus.py)."""


class _StubClient:
    """Minimal stand-in for globus_compute_sdk.Client."""

    def __init__(self, results=None, run_error=None):
        # results: list of (kind, value); kind in {"pending", "result", "error"}
        self._results = list(results or [])
        self._run_error = run_error
        self.registered = []
        self.runs = []
        self.cancelled = []

    def register_function(self, fn):
        self.registered.append(fn)
        return f"func-{fn.__name__}"

    def run(self, *args, endpoint_id=None, function_id=None, **kwargs):
        if self._run_error:
            raise self._run_error
        self.runs.append({"args": args, "endpoint_id": endpoint_id, "function_id": function_id})
        return "task-abc"

    def get_result(self, task_id):
        kind, value = self._results.pop(0)
        if kind == "pending":
            raise _StubTaskPending("Task pending")
        if kind == "error":
            raise RuntimeError(value)
        return value

    def cancel_task(self, task_id):
        self.cancelled.append(task_id)


class TestAvailability(unittest.TestCase):

    def test_is_available_returns_bool(self):
        self.assertIsInstance(compute_client.is_available(), bool)

    def test_get_client_raises_when_sdk_missing(self):
        with patch.object(compute_client, "_sdk_available", False):
            with self.assertRaises(compute_client.GlobusUnavailable) as ctx:
                compute_client.get_client()
            self.assertIn("aidrin[globus]", str(ctx.exception))


class TestRegister(unittest.TestCase):

    def setUp(self):
        compute_client.clear_function_cache()

    def test_registers_headless_runner_once(self):
        stub = _StubClient()
        first = compute_client.register(stub)
        second = compute_client.register(stub)
        self.assertEqual(first, second)
        self.assertEqual(len(stub.registered), 1)
        self.assertEqual(stub.registered[0].__name__, "remote_headless_runner")

    def test_force_reregisters(self):
        stub = _StubClient()
        compute_client.register(stub)
        compute_client.register(stub, force=True)
        self.assertEqual(len(stub.registered), 2)


class TestSubmit(unittest.TestCase):

    def setUp(self):
        compute_client.clear_function_cache()

    def test_submit_passes_command_and_kwargs_positionally(self):
        stub = _StubClient()
        task_id = compute_client.submit(stub, "endpoint-1", "summarize", {"file_path": "/x.csv"})
        self.assertEqual(task_id, "task-abc")
        run = stub.runs[0]
        self.assertEqual(run["args"], ("summarize", {"file_path": "/x.csv"}))
        self.assertEqual(run["endpoint_id"], "endpoint-1")


class TestCheckAndPoll(unittest.TestCase):

    def setUp(self):
        compute_client.clear_function_cache()

    def test_check_completed(self):
        stub = _StubClient(results=[("result", {"ok": True})])
        status = compute_client.check(stub, "task-abc")
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["result"], {"ok": True})

    def test_check_pending(self):
        stub = _StubClient(results=[("pending", None)])
        status = compute_client.check(stub, "task-abc")
        self.assertEqual(status["status"], "processing")

    def test_check_failed(self):
        stub = _StubClient(results=[("error", "worker exploded")])
        status = compute_client.check(stub, "task-abc")
        self.assertEqual(status["status"], "failed")
        self.assertIn("worker exploded", status["error"])

    def test_poll_returns_result_after_pending_rounds(self):
        stub = _StubClient(results=[("pending", None), ("pending", None), ("result", {"ok": 1})])
        slept = []
        result = compute_client.poll(
            stub, "task-abc", timeout=100, interval=2, sleep=slept.append, now=lambda: 0.0
        )
        self.assertEqual(result, {"ok": 1})
        self.assertEqual(slept, [2, 2])

    def test_poll_raises_remote_error_on_failure(self):
        stub = _StubClient(results=[("error", "boom")])
        with self.assertRaises(compute_client.RemoteError):
            compute_client.poll(stub, "task-abc", sleep=lambda _s: None, now=lambda: 0.0)

    def test_poll_times_out_with_task_id(self):
        stub = _StubClient(results=[("pending", None)] * 10)
        clock = iter([0.0, 5.0, 999.0, 999.0])
        with self.assertRaises(compute_client.RemoteTimeout) as ctx:
            compute_client.poll(
                stub, "task-abc", timeout=10, interval=1,
                sleep=lambda _s: None, now=lambda: next(clock),
            )
        self.assertEqual(ctx.exception.task_id, "task-abc")

    def test_poll_reports_result_size_limit_clearly(self):
        stub = _StubClient(results=[("error", "Result size 12000000 exceeds the maximum")])
        with self.assertRaises(compute_client.RemoteError) as ctx:
            compute_client.poll(stub, "task-abc", sleep=lambda _s: None, now=lambda: 0.0)
        self.assertIn("--save-images", str(ctx.exception))


class TestProbe(unittest.TestCase):

    def setUp(self):
        compute_client.clear_function_cache()

    def test_probe_returns_env_dict(self):
        payload = {"aidrin_version": "0.9.2", "python_version": "3.12.4", "headless_import": True}
        stub = _StubClient(results=[("result", payload)])
        self.assertEqual(compute_client.probe(stub, "endpoint-1"), payload)

    def test_probe_rejects_broken_headless_import(self):
        payload = {
            "aidrin_version": "0.9.2",
            "python_version": "3.12.4",
            "headless_import": "ImportError: no module named aidrin.headless",
        }
        stub = _StubClient(results=[("result", payload)])
        with self.assertRaises(compute_client.RemoteError) as ctx:
            compute_client.probe(stub, "endpoint-1")
        self.assertIn("aidrin.headless", str(ctx.exception))


class TestCancel(unittest.TestCase):

    def test_cancel_calls_through(self):
        stub = _StubClient()
        compute_client.cancel(stub, "task-abc")
        self.assertEqual(stub.cancelled, ["task-abc"])

    def test_cancel_swallows_backend_errors(self):
        class _Boom:
            def cancel_task(self, task_id):
                raise RuntimeError("no such task")

        compute_client.cancel(_Boom(), "task-abc")  # must not raise
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. pytest tests/unit/test_compute_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidrin.compute.client'`.

- [ ] **Step 3: Write the implementation**

Create `aidrin/compute/client.py`:

```python
"""Globus Compute client for headless AIDRIN (CLI and MCP).

Roughly the useful half of ``web/globus.py``, minus the OAuth redirect flow:
``globus_compute_sdk.Client()`` runs its own Native App login and caches tokens
under ``~/.globus_compute/``, shared with the ``globus-compute-endpoint`` CLI,
so AIDRIN owns no credential store of its own.
"""

import logging
import time
from typing import Any, Callable, Dict, Optional

from aidrin.compute.remote import remote_env_probe, remote_headless_runner

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 600.0
DEFAULT_INTERVAL = 2.0
PROBE_TIMEOUT = 60.0

_sdk_available = False
try:  # pragma: no cover - depends on the optional extra being installed
    from globus_compute_sdk import Client as ComputeClient

    _sdk_available = True
except ImportError:  # pragma: no cover
    ComputeClient = None


class RemoteError(Exception):
    """Any failure in the remote execution path."""


class GlobusUnavailable(RemoteError):
    """The Globus Compute SDK is not installed."""


class RemoteTimeout(RemoteError):
    """A task did not finish within the allotted time."""

    def __init__(self, task_id: str, timeout: float):
        self.task_id = task_id
        self.timeout = timeout
        super().__init__(
            f"Remote task {task_id} did not finish within {timeout:.0f}s. "
            f"Recover the result later with: aidrin remote task {task_id} --wait"
        )


_function_cache: Dict[str, str] = {}


def clear_function_cache() -> None:
    """Drop cached function UUIDs. Used by tests and by ``register(force=True)``."""
    _function_cache.clear()


def is_available() -> bool:
    """True when ``globus-compute-sdk`` is importable."""
    return _sdk_available


def get_client():
    """Build a Globus Compute client, triggering the SDK's own login if needed."""
    if not _sdk_available:
        raise GlobusUnavailable(
            "Globus support is not installed. Install it with: "
            "pip install 'aidrin[globus]'"
        )
    return ComputeClient()


def register(client, force: bool = False) -> str:
    """Register ``remote_headless_runner`` and return its function UUID."""
    key = "remote_headless_runner"
    if not force and key in _function_cache:
        return _function_cache[key]
    func_uuid = client.register_function(remote_headless_runner)
    _function_cache[key] = func_uuid
    logger.info("Registered remote_headless_runner: %s", func_uuid)
    return func_uuid


def submit(client, endpoint_id: str, command: str, kwargs: Dict[str, Any]) -> str:
    """Submit one headless command to ``endpoint_id``. Returns the task id."""
    func_uuid = register(client)
    task_id = client.run(
        command,
        kwargs,
        endpoint_id=endpoint_id,
        function_id=func_uuid,
    )
    logger.info(
        "Submitted %s to endpoint %s as task %s", command, endpoint_id, task_id
    )
    return str(task_id)


def check(client, task_id: str) -> Dict[str, Any]:
    """Poll a task once. Mirrors ``web.globus.check_task``."""
    try:
        result = client.get_result(task_id)
        return {"status": "completed", "result": result}
    except Exception as exc:
        text = str(exc).lower()
        if "pending" in text or "waiting" in text or "running" in text:
            return {"status": "processing"}
        return {"status": "failed", "error": str(exc)}


def poll(
    client,
    task_id: str,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
    sleep: Callable[[float], Any] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> Any:
    """Block until the task finishes. ``sleep``/``now`` are injectable for tests."""
    deadline = now() + timeout
    while True:
        status = check(client, task_id)
        if status["status"] == "completed":
            return status["result"]
        if status["status"] == "failed":
            error = status["error"]
            if "size" in error.lower() and "exceed" in error.lower():
                raise RemoteError(
                    f"{error}. The result was too large to return; rerun without "
                    "--save-images, which keeps visualization payloads on the endpoint."
                )
            raise RemoteError(error)
        if now() >= deadline:
            raise RemoteTimeout(task_id, timeout)
        sleep(interval)


def probe(client, endpoint_id: str, timeout: float = PROBE_TIMEOUT) -> Dict[str, Any]:
    """Report the endpoint's environment, proving ``aidrin.headless`` imports there."""
    func_uuid = client.register_function(remote_env_probe)
    task_id = str(client.run(endpoint_id=endpoint_id, function_id=func_uuid))
    result = poll(client, task_id, timeout=timeout)
    headless = result.get("headless_import") if isinstance(result, dict) else None
    if headless is not True:
        raise RemoteError(
            "The endpoint can import aidrin but not aidrin.headless.api "
            f"({headless}). Update aidrin on the endpoint: pip install -U aidrin"
        )
    return result


def cancel(client, task_id: str) -> None:
    """Best-effort cancellation. Never raises: the caller is already exiting."""
    try:
        client.cancel_task(task_id)
    except Exception as exc:  # pragma: no cover - backend dependent
        logger.debug("Could not cancel task %s: %s", task_id, exc)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/test_compute_client.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 5: Commit**

```bash
git add aidrin/compute/client.py tests/unit/test_compute_client.py
git commit -m "feat(compute): add headless Globus Compute client"
```

---

### Task 4: RemoteExecutor

**Files:**
- Create: `aidrin/compute/executor.py`
- Test: `tests/unit/test_compute_executor.py` (create)

**Interfaces:**
- Consumes: `aidrin.compute.client` (Task 3), `aidrin.compute.profiles.RemoteTarget` (Task 2), `aidrin.headless.api._maybe_save_images` (existing).
- Produces:
  - `class AsyncSubmitted(Exception)` with attribute `task_id: str`
  - `class RemoteExecutor` with `run_metric`, `summarize_dataset`, `run_data_quality`, `run_batch_metrics`, matching `aidrin.headless.api`'s names and signatures so the CLI can substitute one for the other.

`RemoteExecutor` is duck-typed against the `api` **module**. That substitutability is the whole design: the CLI's dispatch body does not branch on local versus remote.

Image rule: submissions always send `save_images=False`, so the endpoint writes nothing. If the caller asked for images, the executor sends `strip_visualizations=False` so payloads come back, then calls the existing local `_maybe_save_images` to write PNGs on the client.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compute_executor.py`:

```python
"""Unit tests for RemoteExecutor.

A fake client module records what would have been submitted, so these tests
cover argument shaping and local post-processing without any Globus SDK.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from aidrin.compute.executor import AsyncSubmitted, RemoteExecutor
from aidrin.compute.profiles import RemoteTarget


class _Recorder:
    """Stands in for aidrin.compute.client."""

    def __init__(self, result=None):
        self.result = result if result is not None else {"ok": True}
        self.submitted = []
        self.polled = []

    def get_client(self):
        return "stub-client"

    def submit(self, client, endpoint_id, command, kwargs):
        self.submitted.append((endpoint_id, command, kwargs))
        return "task-xyz"

    def poll(self, client, task_id, timeout=600.0, interval=2.0):
        self.polled.append((task_id, timeout))
        return self.result


def _executor(recorder, **kwargs):
    target = RemoteTarget(endpoint="endpoint-1", profile="nersc", source="profile")
    with patch("aidrin.compute.executor.client", recorder):
        return RemoteExecutor(target, **kwargs)


class TestCommandShaping(unittest.TestCase):

    def test_summarize_sends_summarize_command(self):
        rec = _Recorder(result={"columns": ["a"]})
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            result = ex.summarize_dataset("/scratch/data.csv", max_features=5)
        endpoint, command, kwargs = rec.submitted[0]
        self.assertEqual(endpoint, "endpoint-1")
        self.assertEqual(command, "summarize")
        self.assertEqual(kwargs["file_path"], "/scratch/data.csv")
        self.assertEqual(kwargs["max_features"], 5)
        self.assertEqual(result, {"columns": ["a"]})

    def test_run_metric_sends_metric_name(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            ex.run_metric("completeness", "/scratch/data.csv", columns=["a", "b"])
        _endpoint, command, kwargs = rec.submitted[0]
        self.assertEqual(command, "run_metric")
        self.assertEqual(kwargs["metric_name"], "completeness")
        self.assertEqual(kwargs["columns"], ["a", "b"])

    def test_data_quality_command(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_data_quality("/scratch/data.csv")
        self.assertEqual(rec.submitted[0][1], "data_quality")

    def test_batch_sends_config_as_dict(self):
        from aidrin.headless.config import HeadlessConfig

        rec = _Recorder()
        config = HeadlessConfig.from_dict(
            {"file_path": "/scratch/data.csv", "metrics": ["completeness"]}
        )
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_batch_metrics(config)
        _endpoint, command, kwargs = rec.submitted[0]
        self.assertEqual(command, "batch")
        self.assertIsInstance(kwargs["config"], dict)
        self.assertEqual(kwargs["config"]["file_path"], "/scratch/data.csv")


class TestImagePolicy(unittest.TestCase):

    def test_endpoint_never_writes_images(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_metric("completeness", "/x.csv", save_images=True)
        _endpoint, _command, kwargs = rec.submitted[0]
        self.assertFalse(kwargs["save_images"])

    def test_requesting_images_keeps_viz_payload(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_metric("completeness", "/x.csv", save_images=True)
        _endpoint, _command, kwargs = rec.submitted[0]
        self.assertFalse(kwargs["strip_visualizations"])

    def test_default_strips_viz_payload(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec).run_metric("completeness", "/x.csv")
        _endpoint, _command, kwargs = rec.submitted[0]
        self.assertTrue(kwargs["strip_visualizations"])
        self.assertFalse(kwargs["save_images"])

    def test_images_are_written_locally(self):
        import base64

        png = base64.b64encode(b"not-a-real-png").decode()
        rec = _Recorder(result={"Visualization": png})
        target_dir = tempfile.mkdtemp()
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec)
            result = ex.run_metric(
                "completeness", "/x.csv", save_images=True, image_dir=target_dir
            )
        self.assertTrue(result["Visualization"].startswith(target_dir))
        self.assertTrue(os.path.exists(result["Visualization"]))


class TestDetach(unittest.TestCase):

    def test_async_raises_with_task_id(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            ex = _executor(rec, detach=True)
            with self.assertRaises(AsyncSubmitted) as ctx:
                ex.summarize_dataset("/x.csv")
        self.assertEqual(ctx.exception.task_id, "task-xyz")
        self.assertEqual(rec.polled, [])

    def test_blocking_passes_timeout_through(self):
        rec = _Recorder()
        with patch("aidrin.compute.executor.client", rec):
            _executor(rec, timeout=42).summarize_dataset("/x.csv")
        self.assertEqual(rec.polled[0][1], 42)


class TestDuckTyping(unittest.TestCase):

    def test_executor_covers_every_api_function_the_cli_calls(self):
        """If this fails, the CLI's executor swap will break at runtime."""
        for name in ("run_metric", "summarize_dataset", "run_data_quality", "run_batch_metrics"):
            self.assertTrue(hasattr(RemoteExecutor, name), name)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. pytest tests/unit/test_compute_executor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidrin.compute.executor'`.

- [ ] **Step 3: Write the implementation**

Create `aidrin/compute/executor.py`:

```python
"""Executes headless AIDRIN calls on a remote Globus Compute endpoint.

``RemoteExecutor`` is duck-typed against the ``aidrin.headless.api`` *module*:
it exposes the same four function names with the same signatures, so callers
substitute one for the other and never branch on local versus remote.
"""

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional

from aidrin.compute import client
from aidrin.compute.profiles import RemoteTarget
from aidrin.headless.api import _maybe_save_images


class AsyncSubmitted(Exception):
    """Raised in detached mode instead of returning a result.

    Control flow, not failure: the caller catches this, prints the task id, and
    exits 0. Using an exception keeps every call site free of a detach branch.
    """

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(task_id)


class RemoteExecutor:
    """Runs headless commands on ``target.endpoint``."""

    def __init__(
        self,
        target: RemoteTarget,
        *,
        timeout: float = client.DEFAULT_TIMEOUT,
        detach: bool = False,
        compute_client: Any = None,
    ):
        self.target = target
        self.timeout = timeout
        self.detach = detach
        self._client = compute_client

    # -- internals ---------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            self._client = client.get_client()
        return self._client

    def _call(self, command: str, kwargs: Dict[str, Any]) -> Any:
        conn = self._get_client()
        task_id = client.submit(conn, self.target.endpoint, command, kwargs)
        if self.detach:
            raise AsyncSubmitted(task_id)
        return client.poll(conn, task_id, timeout=self.timeout)

    @staticmethod
    def _image_policy(kwargs: Dict[str, Any]) -> tuple:
        """Split image handling into what the endpoint does and what we do.

        The endpoint never writes files. When the caller wants images we ask for
        the visualization payloads to survive the trip, then write them here.
        """
        save_images = bool(kwargs.pop("save_images", False))
        image_dir = kwargs.pop("image_dir", None)
        kwargs["save_images"] = False
        if save_images:
            kwargs["strip_visualizations"] = False
        else:
            kwargs.setdefault("strip_visualizations", True)
        return save_images, image_dir

    # -- api-compatible surface -------------------------------------------

    def run_metric(
        self,
        metric_name: str,
        file_path: str,
        file_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        save_images, image_dir = self._image_policy(kwargs)
        payload = {"metric_name": metric_name, "file_path": file_path, "file_type": file_type}
        payload.update(kwargs)
        result = self._call("run_metric", payload)
        return _maybe_save_images(metric_name, result, save_images, image_dir)

    def summarize_dataset(
        self,
        file_path: str,
        file_type: Optional[str] = None,
        max_features: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._call(
            "summarize",
            {"file_path": file_path, "file_type": file_type, "max_features": max_features},
        )

    def run_data_quality(
        self,
        file_path: str,
        file_type: Optional[str] = None,
        file_name: Optional[str] = None,
        verbose: bool = False,
        strip_visualizations: bool = True,
    ) -> Dict[str, Any]:
        return self._call(
            "data_quality",
            {
                "file_path": file_path,
                "file_type": file_type,
                "file_name": file_name,
                "verbose": verbose,
                "strip_visualizations": strip_visualizations,
            },
        )

    def run_batch_metrics(
        self,
        config: Any,
        verbose: bool = False,
        strip_visualizations: bool = False,
    ) -> Dict[str, Any]:
        # run_batch_metrics accepts a dict, so the endpoint never needs the
        # config file itself. Paths inside it must be endpoint-visible.
        payload = asdict(config) if is_dataclass(config) else dict(config)
        return self._call(
            "batch",
            {
                "config": payload,
                "verbose": verbose,
                "strip_visualizations": strip_visualizations,
            },
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/test_compute_executor.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add aidrin/compute/executor.py tests/unit/test_compute_executor.py
git commit -m "feat(compute): add RemoteExecutor duck-typed against the headless api"
```

---

### Task 5: The `aidrin remote` CLI

**Files:**
- Modify: `aidrin/headless/cli.py`
- Test: `tests/unit/test_remote_cli.py` (create)

**Interfaces:**
- Consumes: `aidrin.compute.{profiles, client, executor}` (Tasks 2 to 4), the existing `main()` parser.
- Produces: the `aidrin remote ...` command surface. No new public Python API.

**Approach.** Rather than registering every subparser twice, `main()` recognises a leading `remote` token, pulls the remote-only flags out of `argv` with a `parse_known_args` pre-parser, and hands the remainder to the **existing, untouched** parser. `aidrin remote summarize` therefore accepts byte-for-byte the same arguments as `aidrin summarize`, permanently and with no second command table. Execution then swaps the `api` module for a `RemoteExecutor`.

`aidrin remote list` means "list profiles", not "list metrics"; management subcommands are matched before the parser sees anything. Use `aidrin remote check` to interrogate the endpoint.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_remote_cli.py`:

```python
"""Unit tests for the `aidrin remote` CLI surface."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aidrin.compute.executor import AsyncSubmitted


def _run_cli(*argv: str) -> tuple[str, str, int]:
    """Invoke main() with the given argv, returning (stdout, stderr, exit_code)."""
    from aidrin.headless.cli import main

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    exit_code = 0
    with patch("sys.argv", ["aidrin", *argv]), \
         patch("sys.stdout", out_buf), \
         patch("sys.stderr", err_buf):
        try:
            main()
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
    return out_buf.getvalue(), err_buf.getvalue(), exit_code


class _RemoteCliTestCase(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.project = tempfile.mkdtemp()
        self._env = patch.dict(os.environ, {"AIDRIN_CONFIG_DIR": self.home}, clear=False)
        self._env.start()
        os.environ.pop("AIDRIN_GLOBUS_ENDPOINT", None)
        self._cwd = patch.object(Path, "cwd", staticmethod(lambda: Path(self.project)))
        self._cwd.start()

    def tearDown(self):
        self._cwd.stop()
        self._env.stop()


class TestManagementCommands(_RemoteCliTestCase):

    def test_configure_probes_before_saving(self):
        probe_result = {"aidrin_version": "0.9.2", "python_version": "3.12.4", "headless_import": True}
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.probe", return_value=probe_result) as probe:
            out, err, code = _run_cli("remote", "configure", "--name", "nersc", "--endpoint", "uuid-1")
        self.assertEqual(code, 0)
        probe.assert_called_once()
        from aidrin.compute import profiles
        self.assertEqual(profiles.list_profiles()["profiles"]["nersc"]["endpoint"], "uuid-1")
        self.assertEqual(profiles.list_profiles()["profiles"]["nersc"]["aidrin_version"], "0.9.2")

    def test_configure_does_not_save_when_probe_fails(self):
        from aidrin.compute.client import RemoteError

        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.probe", side_effect=RemoteError("endpoint offline")):
            _out, err, code = _run_cli("remote", "configure", "--name", "nersc", "--endpoint", "uuid-1")
        self.assertEqual(code, 1)
        self.assertIn("endpoint offline", err)
        from aidrin.compute import profiles
        self.assertEqual(profiles.list_profiles()["profiles"], {})

    def test_list_prints_profiles_as_json(self):
        from aidrin.compute import profiles

        profiles.save_profile("nersc", "uuid-1", default=True)
        out, _err, code = _run_cli("remote", "list")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["default"], "nersc")

    def test_remove_reports_unknown_profile(self):
        _out, err, code = _run_cli("remote", "remove", "ghost")
        self.assertEqual(code, 1)
        self.assertIn("ghost", err)


class TestExecution(_RemoteCliTestCase):

    def setUp(self):
        super().setUp()
        from aidrin.compute import profiles

        profiles.save_profile("nersc", "uuid-1", default=True)

    def test_summarize_routes_to_remote_executor(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={"shape": {"rows": 10, "columns": 2}}):
            out, _err, code = _run_cli("remote", "summarize", "/scratch/data.csv")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["shape"]["rows"], 10)
        _conn, endpoint, command, _kwargs = submit.call_args[0]
        self.assertEqual(endpoint, "uuid-1")
        self.assertEqual(command, "summarize")

    def test_run_metric_routes_to_remote_executor(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={"Completeness scores": {}}):
            _out, _err, code = _run_cli("remote", "run", "completeness", "/scratch/data.csv")
        self.assertEqual(code, 0)
        self.assertEqual(submit.call_args[0][2], "run_metric")

    def test_endpoint_flag_overrides_profile(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={}):
            _run_cli("remote", "--endpoint", "uuid-override", "summarize", "/x.csv")
        self.assertEqual(submit.call_args[0][1], "uuid-override")

    def test_async_prints_task_id_only(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-77"), \
             patch("aidrin.compute.client.poll") as poll:
            out, _err, code = _run_cli("remote", "--async", "summarize", "/x.csv")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["task_id"], "task-77")
        poll.assert_not_called()

    def test_progress_goes_to_stderr_not_stdout(self):
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1"), \
             patch("aidrin.compute.client.poll", return_value={"shape": {"rows": 3, "columns": 1}}):
            out, err, _code = _run_cli("remote", "summarize", "/x.csv")
        self.assertIn("task-1", err)
        self.assertEqual(json.loads(out), {"shape": {"rows": 3, "columns": 1}})

    def test_version_skew_warns_on_stderr(self):
        from aidrin.compute import profiles

        profiles.save_profile("old", "uuid-old", default=True, aidrin_version="0.1.0")
        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1"), \
             patch("aidrin.compute.client.poll", return_value={}):
            _out, err, _code = _run_cli("remote", "summarize", "/x.csv")
        self.assertIn("version", err.lower())


class TestGuards(_RemoteCliTestCase):

    def setUp(self):
        super().setUp()
        from aidrin.compute import profiles

        profiles.save_profile("nersc", "uuid-1", default=True)

    def test_no_endpoint_configured_exits_2(self):
        from aidrin.compute import profiles

        profiles.remove_profile("nersc")
        _out, err, code = _run_cli("remote", "summarize", "/x.csv")
        self.assertEqual(code, 2)
        self.assertIn("aidrin remote configure", err)

    def test_custom_metric_is_rejected(self):
        _out, err, code = _run_cli("remote", "run", "custom", "/my_audit.py", "/x.csv")
        self.assertEqual(code, 2)
        self.assertIn("local", err.lower())

    def test_agentic_is_rejected(self):
        _out, err, code = _run_cli("remote", "agentic", "run", "-c", "cfg.yaml")
        self.assertEqual(code, 2)
        self.assertIn("local", err.lower())

    def test_bare_remote_exits_2(self):
        _out, err, code = _run_cli("remote")
        self.assertEqual(code, 2)
        self.assertIn("subcommand", err)


class TestLocalCliUnaffected(unittest.TestCase):

    def test_local_summarize_still_works(self):
        import numpy as np
        import pandas as pd

        df = pd.DataFrame({"a": np.arange(10), "b": list("abcdefghij")})
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
        df.to_csv(tmp.name, index=False)
        tmp.close()
        try:
            out, _err, code = _run_cli("summarize", tmp.name)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["shape"]["rows"], 10)
        finally:
            os.unlink(tmp.name)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. pytest tests/unit/test_remote_cli.py -v`
Expected: FAIL. `aidrin remote ...` is parsed as an unknown command, so argparse exits 2 with "invalid choice: 'remote'" and the management tests fail on their assertions.

- [ ] **Step 3: Add the remote helpers to `aidrin/headless/cli.py`**

Add these imports near the existing ones at the top of the file:

```python
from aidrin.headless import api as _local_api
```

Then add this block immediately above `def main() -> None:`:

```python
# ---------------------------------------------------------------------------
# Remote execution (aidrin remote ...)
# ---------------------------------------------------------------------------

REMOTE_MANAGEMENT = {
    "configure", "list", "remove", "check", "login", "logout", "status", "task",
}

# Commands that cannot run on an endpoint: they need files or credentials that
# live on the client machine.
REMOTE_FORBIDDEN = {"add-custom-module", "agentic"}


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
        parser.add_argument("--endpoint", required=True, help="Globus Compute endpoint UUID")
        parser.add_argument("--default", action="store_true", help="Make this the default profile")
        parser.add_argument("--local", action="store_true", help="Write ./.aidrin.json instead of ~/.aidrin/config.json")
        args = parser.parse_args(rest)
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


def _make_remote_executor(opts):
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
    )
```

- [ ] **Step 4: Wire the remote branch into `main()`**

At the very top of `main()`, before `parser = argparse.ArgumentParser(prog="aidrin")`, insert:

```python
    argv = sys.argv[1:]
    executor = _local_api
    remote_opts = None

    if argv and argv[0] == "remote":
        remote_opts, argv = _split_remote_argv(argv[1:])
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
```

Then, further down, replace the existing line `argv = sys.argv[1:]` (immediately above the `aidrin <metric>` shortcut comment) with:

```python
    # argv was computed at the top of main() so the `remote` prefix could be
    # stripped before the local parser ever sees it.
```

Directly after `args = parser.parse_args(argv)`, insert the remaining remote setup:

```python
    if remote_opts is not None:
        if args.command == "run" and getattr(args, "metric", None) == "custom":
            sys.stderr.write(
                "Error: custom metrics and remedies are local-only. The custom "
                "module lives on this machine and the endpoint cannot import it.\n"
            )
            sys.exit(2)
        try:
            executor = _make_remote_executor(remote_opts)
        except Exception as exc:
            sys.stderr.write(f"Error: {exc}\n")
            sys.exit(2)
```

- [ ] **Step 5: Route the four dispatch call sites through `executor`**

Inside `main()`'s `try:` block, change these calls and nothing else:

| Location | Before | After |
|---|---|---|
| `run` built-in metric branch | `result = run_metric(` | `result = executor.run_metric(` |
| `run custom` metric branch | `result = run_metric(` | `result = executor.run_metric(` |
| top-level metric shortcut branch | `result = run_metric(` | `result = executor.run_metric(` |
| `batch` branch | `result = run_batch_metrics(` | `result = executor.run_batch_metrics(` |
| `summarize` branch | `result = summarize_dataset(` | `result = executor.summarize_dataset(` |
| `data-quality` branch | `result = run_data_quality(` | `result = executor.run_data_quality(` |

`executor` defaults to the `aidrin.headless.api` module, which exposes exactly these four names, so local behaviour is unchanged.

- [ ] **Step 6: Catch the detached-submission signal**

In `main()`, add a clause **before** the existing `except Exception as exc:`:

```python
    except AsyncSubmitted as submitted:
        _dump_result({"task_id": submitted.task_id})
        return
```

and add the import at the top of the file:

```python
from aidrin.compute.executor import AsyncSubmitted
```

Note: `aidrin/compute/executor.py` imports `aidrin.headless.api`, and `cli.py` already imports from `.api`, so this does not create a cycle. If a cycle does appear, move the import inside `main()`.

- [ ] **Step 7: Handle Ctrl-C during a blocking wait**

In `RemoteExecutor._call` in `aidrin/compute/executor.py`, wrap the poll:

```python
        try:
            return client.poll(conn, task_id, timeout=self.timeout)
        except KeyboardInterrupt:
            client.cancel(conn, task_id)
            raise
```

and in `cli.py`, add a clause before the generic `except Exception`:

```python
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted; remote task cancelled.\n")
        sys.exit(130)
```

- [ ] **Step 8: Run the new tests**

Run: `PYTHONPATH=. pytest tests/unit/test_remote_cli.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 9: Run the existing CLI tests to prove the local path is untouched**

Run: `PYTHONPATH=. pytest tests/unit/test_cli.py -v`
Expected: PASS, same count as before this task.

- [ ] **Step 10: Smoke-test the help output by hand**

Run: `PYTHONPATH=. python -m aidrin.headless.cli remote summarize --help`
Expected: the same help text as `aidrin summarize --help`, since the same parser produced it.

- [ ] **Step 11: Commit**

```bash
git add aidrin/headless/cli.py aidrin/compute/executor.py tests/unit/test_remote_cli.py
git commit -m "feat(cli): add 'aidrin remote' for Globus Compute execution"
```

---

### Task 6: MCP remote parameters

**Files:**
- Modify: `aidrin/mcp/server.py`
- Test: `tests/unit/test_mcp_server.py` (extend)

**Interfaces:**
- Consumes: `aidrin.compute.{profiles, executor}` (Tasks 2 and 4).
- Produces: `endpoint` and `profile` optional parameters on `summarize_dataset`, `run_data_quality_check`, `run_aidrin_metric`, `run_batch`; plus a new `list_remote_profiles()` tool.

MCP is blocking only: a tool call has nowhere to hand back a task id.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_mcp_server.py`:

```python
class TestMcpRemoteRouting(unittest.TestCase):
    """endpoint/profile route through RemoteExecutor; absence stays local."""

    def test_summarize_local_by_default(self):
        from aidrin.mcp import server

        with patch("aidrin.headless.api.summarize_dataset", return_value={"ok": 1}) as local:
            server.summarize_dataset(file_path="/x.csv")
        local.assert_called_once()

    def test_summarize_routes_to_endpoint(self):
        from aidrin.mcp import server

        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={"shape": {"rows": 4, "columns": 1}}):
            out = server.summarize_dataset(file_path="/scratch/x.csv", endpoint="uuid-9")
        self.assertEqual(json.loads(out)["shape"]["rows"], 4)
        self.assertEqual(submit.call_args[0][1], "uuid-9")

    def test_metric_routes_to_endpoint(self):
        from aidrin.mcp import server

        with patch("aidrin.compute.client.get_client", return_value="stub"), \
             patch("aidrin.compute.client.submit", return_value="task-1") as submit, \
             patch("aidrin.compute.client.poll", return_value={"Completeness scores": {}}):
            server.run_aidrin_metric(file_path="/x.csv", metric="completeness", endpoint="uuid-9")
        self.assertEqual(submit.call_args[0][2], "run_metric")

    def test_list_remote_profiles_returns_json(self):
        from aidrin.mcp import server

        out = server.list_remote_profiles()
        self.assertIn("profiles", json.loads(out))
```

Add `from unittest.mock import patch` and `import json` to that file's imports if they are not already present.

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. pytest tests/unit/test_mcp_server.py -k Remote -v`
Expected: FAIL with `TypeError: summarize_dataset() got an unexpected keyword argument 'endpoint'`.

- [ ] **Step 3: Add the executor resolver to `aidrin/mcp/server.py`**

Add below `_dumps`:

```python
def _executor(endpoint: str | None, profile: str | None):
    """Return the remote executor when asked for one, else the local api module."""
    if not endpoint and not profile:
        from aidrin.headless import api

        return api
    from aidrin.compute.executor import RemoteExecutor
    from aidrin.compute.profiles import resolve

    return RemoteExecutor(resolve(endpoint=endpoint, profile=profile))
```

- [ ] **Step 4: Thread the parameters through the four tools**

For `summarize_dataset`, add `endpoint: str | None = None, profile: str | None = None` to the signature, document them, and replace the body's call:

```python
    return _dumps(
        _executor(endpoint, profile).summarize_dataset(
            file_path, file_type=file_type, max_features=max_features
        )
    )
```

This makes the `summarize_dataset as _summarize_dataset` alias in the module's
import block unused. Delete that line from the `from aidrin.headless.api import (...)`
block, since `_executor()` imports the module itself.

Apply the same two parameters and the same substitution to `run_data_quality_check` (`.run_data_quality(...)`), `run_aidrin_metric` (`.run_metric(...)`), and `run_batch` (`.run_batch_metrics(...)`). Use this docstring text for all four:

```
        endpoint: Optional Globus Compute endpoint UUID. When set, the metric runs
                  on that endpoint and file_path must be a path visible there.
        profile: Optional configured endpoint profile name (see list_remote_profiles).
```

- [ ] **Step 5: Add the discovery tool**

```python
@mcp_server.tool()
def list_remote_profiles() -> str:
    """
    List configured Globus Compute endpoint profiles for remote execution.
    Use before asking the user for an endpoint UUID: if a profile exists, pass
    its name as the `profile` argument to the run tools instead.
    """
    from aidrin.compute.profiles import list_profiles

    return _dumps(list_profiles())
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/test_mcp_server.py -v`
Expected: PASS, including the four new tests.

- [ ] **Step 7: Commit**

```bash
git add aidrin/mcp/server.py tests/unit/test_mcp_server.py
git commit -m "feat(mcp): accept endpoint/profile for remote execution"
```

---

### Task 7: Skill and user documentation

**Files:**
- Modify: `.claude/skills/aidrin/SKILL.md`
- Create: `docs/source/remote.rst`
- Modify: `docs/source/index.rst` (add `remote` to the toctree)

**Interfaces:**
- Consumes: the CLI and MCP surfaces from Tasks 5 and 6. No code.

- [ ] **Step 1: Add the remote column to the SKILL.md tool table**

In the "Tool path: MCP vs CLI" table, add a third column. Example rows:

```markdown
| Action | MCP tool | CLI equivalent | Remote |
|---|---|---|---|
| Preflight | `list_metrics()` | `aidrin list` | `aidrin remote check` |
| List endpoints | `list_remote_profiles()` | `aidrin remote list` | n/a |
| Summarize dataset | `summarize_dataset(file_path)` | `aidrin summarize <file>` | add `profile=` / `aidrin remote summarize` |
| Quality baseline | `run_data_quality_check(file_path)` | `aidrin data-quality <file>` | add `profile=` / `aidrin remote data-quality` |
| Single metric | `run_aidrin_metric(file_path, metric, ...)` | `aidrin run <metric> <file> <args...>` | add `profile=` / `aidrin remote run <metric>` |
| Batch | `run_batch(config_path)` | `aidrin batch <config>` | add `profile=` / `aidrin remote batch` |
```

- [ ] **Step 2: Extend step 1 of the workflow checklist**

Change the preflight bullet to:

```markdown
- [ ] 1. Preflight: confirm AIDRIN is available; read which metrics exist; check for remote endpoints
```

and append to the "### 1. Preflight" section:

```markdown
**Remote endpoints:** also call `list_remote_profiles()` (MCP) or run
`aidrin remote list` (CLI). If any profile is configured, ask once whether this
dataset is local or on that endpoint, then keep that answer for the session.
```

- [ ] **Step 3: Add a "Remote datasets" section before "## Gotchas"**

```markdown
## Remote datasets (Globus Compute)

When the dataset lives on a remote machine (HPC scratch, a lab server) that runs
a Globus Compute endpoint, AIDRIN can execute the metrics there and return only
the results. The data never moves.

**MCP:** pass `profile="<name>"` (or `endpoint="<uuid>"`) to `summarize_dataset`,
`run_data_quality_check`, `run_aidrin_metric`, or `run_batch`.

**CLI:** prefix the command with `remote`, for example
`aidrin remote summarize /scratch/proj/data.csv`. The arguments and the JSON are
identical to a local run, so steps 3 through 8 of the workflow are unchanged.

What differs:

- **Paths are remote.** `file_path` is a path on the endpoint's filesystem. You
  cannot list it, so ask the user for the full path. A wrong path comes back as
  a metric error, not as a local file-not-found.
- **Local-only:** custom metrics, remedies, and the agentic pipeline. They need
  files or credentials on this machine. Say so plainly rather than retrying.
- **Setup:** if no profile is configured, the user runs
  `aidrin remote configure --name <name> --endpoint <uuid>` once. Do not run
  this for them: it needs an endpoint UUID only they have.
- **Version skew:** the endpoint may run an older AIDRIN. If a metric that
  `list_metrics()` reports fails remotely with an unknown-metric error, that is
  the likely cause; report it rather than working around it.
```

- [ ] **Step 4: Add two remote gotchas**

Under "## Gotchas", in the "Both paths" list:

```markdown
- Remote runs never write files on the endpoint. Visualizations come back in the
  result and are written on your machine.
- A remote result is capped near 10 MB. If a run fails on result size, rerun
  without image output.
```

- [ ] **Step 5: Write `docs/source/remote.rst`**

```rst
Remote datasets with Globus Compute
===================================

AIDRIN can run its metrics on a machine you do not have to copy data off of, by
submitting the work to a `Globus Compute <https://www.globus.org/compute>`_
endpoint. Only the results travel back.

Requirements
------------

* ``pip install 'aidrin[globus]'`` on your machine.
* A running Globus Compute endpoint on the remote machine, with ``aidrin``
  installed in the endpoint's Python environment.
* The dataset already on a filesystem that endpoint can read. AIDRIN does not
  transfer data.

One-time setup
--------------

.. code-block:: bash

   aidrin remote configure --name nersc --endpoint <endpoint-uuid>

This logs in through Globus if needed (tokens are cached by
``globus-compute-sdk``), probes the endpoint, and refuses to save if the
endpoint cannot import ``aidrin.headless``. Add ``--local`` to write
``./.aidrin.json`` for the current project instead of ``~/.aidrin/config.json``.

Running metrics
---------------

.. code-block:: bash

   aidrin remote summarize /scratch/proj/data.csv
   aidrin remote data-quality /scratch/proj/data.csv
   aidrin remote run k-anonymity /scratch/proj/data.csv "zip,age"
   aidrin remote batch config.yaml

Every command takes the same arguments as its local counterpart and prints the
same JSON. Paths refer to the endpoint's filesystem.

Long-running jobs
-----------------

.. code-block:: bash

   aidrin remote run k-anonymity /scratch/data.csv "zip,age" --async
   # prints {"task_id": "..."}
   aidrin remote task <task-id>          # status
   aidrin remote task <task-id> --wait   # block for the result

Choosing an endpoint
--------------------

Precedence, first match wins:

1. ``--endpoint <uuid>``
2. ``--profile <name>``
3. ``AIDRIN_GLOBUS_ENDPOINT``
4. the default profile in ``./.aidrin.json``
5. the default profile in ``~/.aidrin/config.json``

``aidrin remote`` never falls back to running locally. If no endpoint resolves,
it exits with an error.

Limitations
-----------

* Custom metrics, remedies, and the agentic pipeline are local-only.
* Results are capped near 10 MB, so visualization payloads are stripped unless
  you ask for images.
* Images are written on your machine, never on the endpoint.
```

- [ ] **Step 6: Add `remote` to the docs toctree**

Insert `remote` into the toctree in `docs/source/index.rst`, after the usage or CLI entry.

- [ ] **Step 7: Build the docs**

Run: `cd docs && PYTHONPATH=.. ../.venv/bin/python -m sphinx -b html source _build/html`
Expected: build succeeds with no warnings about `remote.rst` being missing from a toctree.

- [ ] **Step 8: Commit**

```bash
git add .claude/skills/aidrin/SKILL.md docs/source/remote.rst docs/source/index.rst
git commit -m "docs: document remote execution for the CLI, MCP, and skill"
```

---

### Task 8: End-to-end verification against a real endpoint

**Files:**
- Modify: `tests/integration/test_globus.py`

**Interfaces:**
- Consumes: everything above. Produces no new API.

This is the acceptance test for the feature. It needs a real endpoint, so it skips without one.

- [ ] **Step 1: Add the skip-guarded integration test**

Append to `tests/integration/test_globus.py`:

```python
# -------------------------------------------------
# Headless remote path (needs a real endpoint)
# -------------------------------------------------

AIDRIN_TEST_ENDPOINT = os.environ.get("AIDRIN_TEST_ENDPOINT")
AIDRIN_TEST_REMOTE_FILE = os.environ.get("AIDRIN_TEST_REMOTE_FILE")


@pytest.mark.skipif(
    not (AIDRIN_TEST_ENDPOINT and AIDRIN_TEST_REMOTE_FILE),
    reason="Set AIDRIN_TEST_ENDPOINT and AIDRIN_TEST_REMOTE_FILE to run",
)
def test_remote_summarize_matches_local():
    """The same file summarized locally and remotely must agree.

    AIDRIN_TEST_REMOTE_FILE must name a file present at the same path on both
    this machine and the endpoint.
    """
    from aidrin.compute.executor import RemoteExecutor
    from aidrin.compute.profiles import RemoteTarget
    from aidrin.headless.api import summarize_dataset

    local = summarize_dataset(AIDRIN_TEST_REMOTE_FILE)
    target = RemoteTarget(endpoint=AIDRIN_TEST_ENDPOINT, profile=None, source="flag")
    remote = RemoteExecutor(target).summarize_dataset(AIDRIN_TEST_REMOTE_FILE)

    assert remote["shape"] == local["shape"]
    assert remote["columns"] == local["columns"]
    assert remote["numerical"].keys() == local["numerical"].keys()


@pytest.mark.skipif(
    not (AIDRIN_TEST_ENDPOINT and AIDRIN_TEST_REMOTE_FILE),
    reason="Set AIDRIN_TEST_ENDPOINT and AIDRIN_TEST_REMOTE_FILE to run",
)
def test_remote_probe_reports_headless_import():
    from aidrin.compute import client as compute_client

    env = compute_client.probe(compute_client.get_client(), AIDRIN_TEST_ENDPOINT)
    assert env["headless_import"] is True
    assert env["aidrin_version"]
```

Add `import pytest` to the file's imports if it is not already there.

- [ ] **Step 2: Run the suite without credentials**

Run: `PYTHONPATH=. pytest tests/integration/test_globus.py -v`
Expected: the two new tests SKIP; everything else passes.

- [ ] **Step 3: Run the full unit suite**

Run: `PYTHONPATH=. pytest tests/unit -q`
Expected: PASS, no regressions.

- [ ] **Step 4: Run against a real endpoint by hand**

```bash
export AIDRIN_TEST_ENDPOINT=<uuid>
export AIDRIN_TEST_REMOTE_FILE=/path/present/on/both
PYTHONPATH=. pytest tests/integration/test_globus.py -v -k remote
```

Expected: PASS. If `test_remote_probe_reports_headless_import` fails, `aidrin` on the endpoint is too old or is a different install; upgrade it there before continuing.

- [ ] **Step 5: Walk the user-facing path once**

```bash
aidrin remote configure --name test --endpoint $AIDRIN_TEST_ENDPOINT
aidrin remote list
aidrin remote check
aidrin remote summarize $AIDRIN_TEST_REMOTE_FILE
aidrin remote data-quality $AIDRIN_TEST_REMOTE_FILE
aidrin remote summarize $AIDRIN_TEST_REMOTE_FILE --async
aidrin remote task <printed-task-id> --wait
```

Expected: configure reports the endpoint's version; `summarize` prints JSON matching a local run; `--async` prints only a task id; `task --wait` returns the result.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_globus.py
git commit -m "test: add end-to-end checks for headless remote execution"
```

---

## Self-Review Notes

Spec coverage checked section by section:

- Seam and `remote_headless_runner`: Task 1.
- `profiles.py`, precedence, project override, file mode: Task 2.
- `client.py`, auth via the SDK, probe, submit, poll, cancel: Task 3.
- Blocking default, `--async`, `--timeout`, Ctrl-C, image policy, payload cap: Tasks 4 and 5.
- CLI surface, management commands, forbidden commands, version-skew warning: Task 5.
- MCP parameters and `list_remote_profiles`: Task 6.
- SKILL.md and docs: Task 7.
- Local-versus-remote JSON equality acceptance test: Task 8.

One deliberate deviation from the spec as first written: it proposed extracting
`_add_metric_subcommands` and registering the subparsers twice. This plan strips
the `remote` prefix from `argv` and reuses the existing parser instead. Same
guarantee (identical arguments, one command table) with no restructuring of
`main()`'s parser assembly, so the local CLI carries no regression risk. The
spec's section 3 has been updated to match.

Two assertions were corrected during self-review after checking the real return
shape of `summarize_dataset`: it returns `shape.rows`, not `records_count`. One
MCP test was patching `server._summarize_dataset`, which the implementation step
removes; it now patches `aidrin.headless.api.summarize_dataset`.
