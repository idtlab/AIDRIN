"""Optional Globus Compute integration for AIDRIN.

When ``globus-compute-sdk`` is installed (``pip install aidrin[globus]``),
this module provides remote metric execution via Globus Compute endpoints.
When the packages are **not** installed, ``is_globus_available()`` returns
False and all other functions raise ImportError — the inspector hides the
Globus UI entirely.
"""

import logging
import os
import sys

from aidrin import __version__ as AIDRIN_VERSION

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

_globus_available = False

try:
    from globus_compute_sdk import Client as ComputeClient
    from globus_sdk import (
        ConfidentialAppAuthClient,
        NativeAppAuthClient,
        AccessTokenAuthorizer,
    )
    _globus_available = True
except ImportError:
    pass


def is_globus_available():
    """Return True if the Globus Compute SDK is installed."""
    return _globus_available


# ---------------------------------------------------------------------------
# The function that runs on the remote endpoint
# ---------------------------------------------------------------------------
#
# ``remote_metric_runner`` now lives in ``aidrin.compute.remote`` so that the
# Globus Compute worker (which has ``aidrin`` installed but not this ``web``
# app) can import it during deserialisation. It is re-exported here for
# backward compatibility with existing imports/tests. ``remote_env_probe`` is
# used by ``check_endpoint_compatibility`` below.
from aidrin.compute.remote import remote_metric_runner, remote_env_probe  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

GLOBUS_COMPUTE_SCOPE = (
    "https://auth.globus.org/scopes/facd7ccc-c5f4-42aa-916b-a0e270e2c2a9/all"
)
GLOBUS_AUTH_SCOPE = "openid profile email"


def _get_client_id():
    client_id = os.environ.get("GLOBUS_CLIENT_ID")
    if not client_id:
        raise ValueError(
            "GLOBUS_CLIENT_ID environment variable is required. "
            "Register an app at https://developers.globus.org/"
        )
    return client_id


def _get_client_secret():
    return os.environ.get("GLOBUS_CLIENT_SECRET")


GLOBUS_SCOPES = [GLOBUS_COMPUTE_SCOPE, GLOBUS_AUTH_SCOPE]

# Store auth client in memory between redirect and callback.
# Keyed by a random state string stored in the user's session.
_pending_auth_clients = {}


def get_auth_url(redirect_uri):
    """Generate the Globus Auth login URL for the OAuth2 redirect flow.

    Returns (auth_url, state_key) — the URL to redirect the user to,
    and a state key to retrieve the auth client in the callback.
    """
    if not _globus_available:
        raise ImportError("globus-sdk is not installed")

    import uuid
    client_id = _get_client_id()
    client_secret = _get_client_secret()

    # Use ConfidentialAppAuthClient if secret is provided (web app),
    # otherwise fall back to NativeAppAuthClient (console/dev)
    if client_secret:
        auth_client = ConfidentialAppAuthClient(
            client_id=client_id, client_secret=client_secret
        )
    else:
        auth_client = NativeAppAuthClient(client_id=client_id)

    auth_client.oauth2_start_flow(
        redirect_uri=redirect_uri,
        requested_scopes=GLOBUS_SCOPES,
    )
    auth_url = auth_client.oauth2_get_authorize_url()

    # Keep the auth client alive in server memory for the callback
    state_key = uuid.uuid4().hex
    _pending_auth_clients[state_key] = auth_client

    return auth_url, state_key


def exchange_code_for_tokens(auth_code, state_key):
    """Exchange the OAuth2 authorization code for access tokens.

    Uses the same auth client instance that generated the original auth URL
    (preserves the PKCE verifier).

    Returns a dict of tokens keyed by resource server.
    """
    auth_client = _pending_auth_clients.pop(state_key, None)
    if auth_client is None:
        raise ValueError("Auth session expired or invalid. Please try again.")

    logger.info(
        "Token exchange: client_type=%s, client_id=%s, has_secret=%s",
        type(auth_client).__name__,
        auth_client.client_id,
        bool(_get_client_secret()),
    )

    try:
        token_response = auth_client.oauth2_exchange_code_for_tokens(auth_code)
    except Exception as e:
        logger.error("Token exchange failed: %s", e, exc_info=True)
        raise

    return token_response.by_resource_server


# ---------------------------------------------------------------------------
# Globus Compute client
# ---------------------------------------------------------------------------

_function_uuid_cache = {}  # Cleared on every server restart → always re-registers latest code


def get_compute_client(tokens):
    """Create a Globus Compute client from stored tokens.

    Parameters
    ----------
    tokens : dict
        Token dict from ``exchange_code_for_tokens()``, stored in Flask session.
    """
    if not _globus_available:
        raise ImportError("globus-compute-sdk is not installed")

    # Token resource server key varies by SDK version
    compute_tokens = None
    for key in ("funcx_service", "compute.api.globus.org", "groups.api.globus.org"):
        if key in tokens and "access_token" in tokens[key]:
            compute_tokens = tokens[key]
            break

    if compute_tokens is None:
        # Try all keys and find one with an access_token
        for key, val in tokens.items():
            if isinstance(val, dict) and "access_token" in val:
                compute_tokens = val
                logger.info("Using token from resource server: %s", key)
                break

    if compute_tokens is None:
        available_keys = list(tokens.keys())
        raise ValueError(f"No Globus Compute access token found. Available: {available_keys}")

    access_token = compute_tokens["access_token"]

    try:
        return ComputeClient(
            authorizer=AccessTokenAuthorizer(access_token),
        )
    except TypeError:
        # Newer SDK versions may use different constructor
        return ComputeClient()


def register_function(client, force=False):
    """Register the remote_metric_runner function with Globus Compute.

    Returns the function UUID. Re-registers on every server restart
    to ensure the latest code is used.
    """
    cache_key = "remote_metric_runner"
    if not force and cache_key in _function_uuid_cache:
        return _function_uuid_cache[cache_key]

    func_uuid = client.register_function(remote_metric_runner)
    _function_uuid_cache[cache_key] = func_uuid
    logger.info("Registered remote_metric_runner with Globus Compute: %s", func_uuid)
    return func_uuid


# ---------------------------------------------------------------------------
# Endpoint compatibility check
# ---------------------------------------------------------------------------


def _minor(version):
    """Return the ``major.minor`` prefix of a version ("2026.07.1" -> "2026.07")."""
    return ".".join(str(version).split(".")[:2])


def _run_probe_sync(client, endpoint_id, timeout=30, interval=2):
    """Register + run ``remote_env_probe`` on the endpoint and wait for its result.

    Blocks up to ``timeout`` seconds. Raises TimeoutError if the endpoint does
    not respond in time (e.g. a cold or busy HPC scheduler).
    """
    import time

    func_uuid = client.register_function(remote_env_probe)
    task_id = client.run(endpoint_id=endpoint_id, function_id=func_uuid)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return client.get_result(task_id)
        except Exception as e:
            msg = str(e).lower()
            if any(s in msg for s in ("pending", "waiting", "running")):
                time.sleep(interval)
                continue
            raise
    raise TimeoutError(
        f"Endpoint {endpoint_id} did not respond to the environment probe "
        f"within {timeout}s"
    )


def check_endpoint_compatibility(client, endpoint_id, timeout=30):
    """Verify the remote endpoint's environment is compatible with this server.

    Runs ``remote_env_probe`` on ``endpoint_id`` and compares the endpoint's
    ``aidrin`` and Python versions against the local ones. This doubles as a
    reachability / import check: a successful probe proves the worker can
    import ``aidrin`` at all — turning "No module named ...", wrong-env, and
    version-drift failures into a clear message at connect time rather than a
    dill traceback after a real job runs.

    Returns a report dict::

        {
            "compatible": bool,          # False on aidrin major.minor mismatch
            "local":  {"aidrin": ..., "python": ...},
            "remote": {"aidrin": ..., "python": ...},
            "warnings": [str, ...],      # non-fatal (e.g. Python minor drift)
        }

    Policy: an ``aidrin`` major.minor mismatch is **incompatible** (reference
    serialisation means the worker would run different metric code). A Python
    major.minor difference is a **warning** — dill can often cross minor
    versions but it is the classic cause of deserialisation errors.
    """
    local_aidrin = AIDRIN_VERSION
    local_python = ".".join(map(str, sys.version_info[:3]))

    try:
        remote = _run_probe_sync(client, endpoint_id, timeout=timeout)
    except Exception as e:
        # If the endpoint's aidrin predates this change it has no
        # ``aidrin.compute.remote`` module / ``remote_env_probe`` to
        # reconstruct, so the probe fails to deserialise there. Treat that as a
        # clear incompatibility (upgrade the endpoint) rather than a 500 — but
        # let genuine infra errors (timeout, offline, auth) propagate.
        detail = str(e)
        lowered = detail.lower()
        probe_missing = any(
            s in lowered
            for s in (
                "no module named",
                "modulenotfound",
                "cannot import",
                "importerror",
                "attributeerror",
                "remote_env_probe",
                "aidrin.compute",
            )
        )
        if not probe_missing:
            raise
        report = {
            "compatible": False,
            "local": {"aidrin": local_aidrin, "python": local_python},
            "remote": {"aidrin": "unknown", "python": "unknown"},
            "warnings": [
                "The endpoint's aidrin version is incompatible with this "
                f"server. Install aidrin {local_aidrin} on the endpoint."
            ],
        }
        # Full remote traceback goes to the server log only — never the UI.
        logger.warning("Endpoint %s probe failed (old aidrin?): %s", endpoint_id, detail)
        return report

    remote_aidrin = remote.get("aidrin_version", "unknown")
    remote_python = remote.get("python_version", "unknown")

    warnings = []
    compatible = True

    if _minor(remote_aidrin) != _minor(local_aidrin):
        compatible = False
        warnings.append(
            f"aidrin version mismatch: web server has {local_aidrin}, "
            f"endpoint has {remote_aidrin}. Reinstall aidrin on the endpoint "
            f"so the major.minor versions match."
        )

    if _minor(remote_python) != _minor(local_python):
        warnings.append(
            f"Python version differs: web server {local_python}, "
            f"endpoint {remote_python}. This can cause serialisation errors."
        )

    report = {
        "compatible": compatible,
        "local": {"aidrin": local_aidrin, "python": local_python},
        "remote": {"aidrin": remote_aidrin, "python": remote_python},
        "warnings": warnings,
    }
    logger.info("Endpoint %s compatibility: %s", endpoint_id, report)
    return report


# ---------------------------------------------------------------------------
# Task submission and status
# ---------------------------------------------------------------------------


def submit_metric(client, endpoint_id, metric_name, file_path, file_name, file_type, **params):
    """Submit a metric computation task to a remote Globus Compute endpoint.

    Returns the task UUID string for polling.
    """
    func_uuid = register_function(client)

    # Pass all arguments as positional args to avoid kwarg conflicts
    # with endpoint_id/function_id. The remote_metric_runner signature is:
    # remote_metric_runner(metric_name, file_path, file_name, file_type, **params)
    task_id = client.run(
        metric_name, file_path, file_name, file_type,
        endpoint_id=endpoint_id,
        function_id=func_uuid,
        # Pass params as a single keyword arg that remote_metric_runner unpacks
        **{k: v for k, v in params.items() if k not in ('endpoint_id', 'function_id')},
    )

    logger.info(
        "Submitted Globus Compute task %s: metric=%s endpoint=%s file=%s func=%s params=%s",
        task_id, metric_name, endpoint_id, file_path, func_uuid, params,
    )
    return str(task_id)


def check_task(client, task_id):
    """Check the status of a Globus Compute task.

    Returns a dict matching the format used by the inspector's pollAsyncMetric:
    ``{"status": "processing|completed|failed", "result": ..., "error": ...}``
    """
    try:
        result = client.get_result(task_id)
        # get_result returns the result directly if complete,
        # raises Exception if pending or failed
        return {"status": "completed", "result": result}
    except Exception as e:
        error_str = str(e)
        if "pending" in error_str.lower() or "waiting" in error_str.lower():
            return {"status": "processing", "progress": {"status": "Running on remote endpoint..."}}
        return {"status": "failed", "error": error_str}
