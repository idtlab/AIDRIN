"""Globus Compute client for headless AIDRIN (CLI and MCP).

Roughly the useful half of ``web/globus.py``, minus the OAuth redirect flow:
``globus_compute_sdk.Client()`` runs its own Native App login and caches tokens
under ``~/.globus_compute/``, shared with the ``globus-compute-endpoint`` CLI,
so AIDRIN owns no credential store of its own.
"""

import logging
import time
from typing import Any, Callable, Dict

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
        if "pending" in text or "waiting" in text:
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
