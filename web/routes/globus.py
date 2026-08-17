"""Flask routes for Globus Compute integration.

All routes are under the ``/globus`` prefix. The blueprint is only
registered when ``globus-compute-sdk`` is installed.
"""

import logging
import os
import time

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from web.globus import (
    is_globus_available,
    get_auth_url,
    exchange_code_for_tokens,
    get_compute_client,
    submit_metric,
    check_task,
    check_endpoint_compatibility,
)

logger = logging.getLogger(__name__)

globus_bp = Blueprint("globus", __name__, url_prefix="/globus")

NEGOTIATION_TTL_SECONDS = 300
DEFAULT_ENDPOINT_PROBE_TIMEOUT = 30.0
FILE_REFERENCE_CAPABILITY = "file_reference_validation_v1"
FILE_REFERENCE_UPGRADE_MESSAGE = (
    "File-reference validation is unavailable on this endpoint. Upgrade AIDRIN "
    "in every Globus Compute worker environment and restart the endpoint."
)


def _negotiation_fingerprint(record):
    return "|".join([
        str(record.get("remote_aidrin_version", "unknown")),
        str(record.get("capability_schema_version", "")),
        ",".join(record.get("capabilities", [])),
        str(record.get("checked_at", "")),
    ])


def _store_negotiation(endpoint_id, report, checked_at=None):
    remote = report.get("remote", {})
    record = {
        "endpoint_id": endpoint_id,
        "remote_aidrin_version": remote.get("aidrin", "unknown"),
        "capability_schema_version": remote.get("capability_schema_version"),
        "capabilities": sorted(remote.get("capabilities", [])),
        "checked_at": time.time() if checked_at is None else checked_at,
    }
    record["fingerprint"] = _negotiation_fingerprint(record)
    session["globus_endpoint_negotiation"] = record
    return record


def _clear_negotiation():
    session.pop("globus_endpoint_negotiation", None)


def _endpoint_probe_timeout():
    """Return the administrator-configured endpoint probe timeout."""
    value = current_app.config.get(
        "GLOBUS_ENDPOINT_PROBE_TIMEOUT",
        os.environ.get(
            "AIDRIN_GLOBUS_ENDPOINT_PROBE_TIMEOUT",
            DEFAULT_ENDPOINT_PROBE_TIMEOUT,
        ),
    )
    try:
        timeout = float(value)
        if timeout <= 0:
            raise ValueError
    except (TypeError, ValueError):
        logger.warning(
            "Invalid GLOBUS_ENDPOINT_PROBE_TIMEOUT %r; using %.0fs",
            value,
            DEFAULT_ENDPOINT_PROBE_TIMEOUT,
        )
        return DEFAULT_ENDPOINT_PROBE_TIMEOUT
    return timeout


def _fresh_negotiation(client, endpoint_id, force=False):
    record = session.get("globus_endpoint_negotiation", {})
    fresh = (
        not force
        and record.get("endpoint_id") == endpoint_id
        and time.time() - record.get("checked_at", 0) < NEGOTIATION_TTL_SECONDS
    )
    if fresh:
        return record, None

    report = check_endpoint_compatibility(
        client,
        endpoint_id,
        _endpoint_probe_timeout(),
    )
    if not report["compatible"]:
        _clear_negotiation()
        return None, report
    return _store_negotiation(endpoint_id, report), report


def _requires_file_reference_capability(metric_name, params):
    return metric_name == "file_reference_validation" or (
        metric_name == "data_structure"
        and "file_reference_validation" in params.get("selected", [])
    )


def _valid_file_reference_discovery(value):
    if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
        return False
    if not isinstance(value.get("roots"), list):
        return False
    if not isinstance(value.get("scan_limit"), int) or value["scan_limit"] <= 0:
        return False
    return all(
        isinstance(root, dict)
        and isinstance(root.get("id"), str)
        and isinstance(root.get("label"), str)
        for root in value["roots"]
    )


def _remove_file_reference_capability(context):
    record = session.get("globus_endpoint_negotiation", {})
    if (
        record.get("endpoint_id") != context.get("endpoint_id")
        or record.get("fingerprint") != context.get("negotiation_fingerprint")
    ):
        return False
    capabilities = list(record.get("capabilities", []))
    if FILE_REFERENCE_CAPABILITY not in capabilities:
        return False
    capabilities.remove(FILE_REFERENCE_CAPABILITY)
    record["capabilities"] = capabilities
    record["fingerprint"] = _negotiation_fingerprint(record)
    session["globus_endpoint_negotiation"] = record
    return True


def _remove_task_tracking(task_id):
    active = session.get("globus_active_tasks", [])
    if task_id in active:
        active.remove(task_id)
        session["globus_active_tasks"] = active
    contexts = session.get("globus_task_contexts", {})
    if task_id in contexts:
        contexts.pop(task_id)
        session["globus_task_contexts"] = contexts


def _cancel_active_globus_tasks():
    """Cancel any active Globus Compute tasks tracked in the session."""
    active = session.get("globus_active_tasks", [])
    if not active:
        return
    try:
        tokens = session.get("globus_tokens", {})
        client = get_compute_client(tokens)
        for task_id in active:
            try:
                client.stop(task_id)
                logger.info("Cancelled Globus task: %s", task_id)
            except Exception as e:
                logger.warning("Failed to cancel Globus task %s: %s", task_id, e)
    except Exception as e:
        logger.warning("Could not create Globus client for task cancellation: %s", e)
    finally:
        session.pop("globus_active_tasks", None)
        session.pop("globus_task_contexts", None)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@globus_bp.route("/auth")
def auth():
    """Redirect user to Globus Auth login page."""
    if not is_globus_available():
        return jsonify({"error": "Globus SDK not installed"}), 400

    import os
    redirect_uri = os.environ.get(
        "GLOBUS_REDIRECT_URI",
        url_for("globus.callback", _external=True),
    )

    try:
        auth_url, state_key = get_auth_url(redirect_uri)
        # Store state key to retrieve auth client in callback
        session["globus_auth_state"] = {
            "redirect_uri": redirect_uri,
            "state_key": state_key,
        }
        return redirect(auth_url)
    except ValueError as e:
        logger.error("Globus auth URL error: %s", e, exc_info=True)
        return jsonify({"error": "An internal error occurred"}), 500


@globus_bp.route("/callback")
def callback():
    """Handle OAuth2 callback from Globus Auth."""
    auth_code = request.args.get("code")
    if not auth_code:
        return jsonify({"error": "No authorization code received"}), 400

    auth_state = session.pop("globus_auth_state", {})
    state_key = auth_state.get("state_key")

    if not state_key:
        return jsonify({"error": "Auth session expired. Please try again."}), 400

    try:
        tokens = exchange_code_for_tokens(auth_code, state_key)
        session["globus_tokens"] = {
            rs: {
                "access_token": t["access_token"],
                "expires_at_seconds": t.get("expires_at_seconds", 0),
            }
            for rs, t in tokens.items()
        }
        session["globus_authenticated"] = True

        logger.info("Globus Auth: user authenticated successfully")
        return redirect(url_for("core.inspector"))

    except Exception as e:
        logger.error("Globus Auth callback error: %s", e, exc_info=True)
        return jsonify({"error": "Authentication failed"}), 500


# ---------------------------------------------------------------------------
# Status / disconnect
# ---------------------------------------------------------------------------


@globus_bp.route("/status")
def status():
    """Check if the user is authenticated with Globus."""
    return jsonify({
        "authenticated": session.get("globus_authenticated", False),
        "globus_available": is_globus_available(),
    })


@globus_bp.route("/disconnect", methods=["POST"])
def disconnect():
    """Cancel active tasks and clear Globus tokens/cache from session."""
    _cancel_active_globus_tasks()
    # Clear cached summary
    endpoint_id = session.get("globus_endpoint_id", "")
    file_path = session.get("globus_file_path", "")
    if endpoint_id and file_path:
        cache_key = f"globus_summary:{endpoint_id}:{file_path}"
        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
    session.pop("globus_tokens", None)
    session.pop("globus_authenticated", None)
    session.pop("globus_endpoint_id", None)
    session.pop("globus_file_path", None)
    session.pop("globus_file_name", None)
    session.pop("globus_file_type", None)
    session.pop("globus_active_tasks", None)
    session.pop("globus_task_contexts", None)
    _clear_negotiation()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Endpoint compatibility
# ---------------------------------------------------------------------------


@globus_bp.route("/check-endpoint", methods=["POST"])
def check_endpoint():
    """Verify a Globus Compute endpoint is compatible before submitting work.

    Call this when the user connects/selects an endpoint. Runs a tiny probe on
    the endpoint and compares its ``aidrin``/Python versions against this
    server. Returns 200 with a report when compatible, 409 when not.

    Expects JSON body: ``{"endpoint_id": "uuid"}``.
    """
    if not session.get("globus_authenticated"):
        return jsonify({"error": "Not authenticated with Globus"}), 401

    data = request.get_json() or {}
    endpoint_id = data.get("endpoint_id")
    if not endpoint_id:
        return jsonify({"error": "Missing required field: endpoint_id"}), 400

    try:
        tokens = session.get("globus_tokens", {})
        client = get_compute_client(tokens)
        _, report = _fresh_negotiation(client, endpoint_id, force=True)
        return jsonify(report), (200 if report["compatible"] else 409)
    except Exception as e:
        logger.error("Globus check-endpoint error: %s", e, exc_info=True)
        return jsonify({"error": "Failed to check endpoint compatibility"}), 500


# ---------------------------------------------------------------------------
# Task submission + polling
# ---------------------------------------------------------------------------


@globus_bp.route("/submit", methods=["POST"])
def submit():
    """Submit a metric computation task to a remote Globus Compute endpoint.

    Expects JSON body:
    {
        "endpoint_id": "uuid",
        "file_path": "/path/on/remote/endpoint/data.csv",
        "file_name": "data.csv",
        "file_type": ".csv",
        "metric_name": "completeness",
        "params": { ... optional metric-specific parameters ... }
    }
    """
    if not session.get("globus_authenticated"):
        return jsonify({"error": "Not authenticated with Globus"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    endpoint_id = data.get("endpoint_id")
    file_path = data.get("file_path")
    file_name = data.get("file_name", file_path.split("/")[-1] if file_path else "")
    file_type = data.get("file_type")
    metric_name = data.get("metric_name")
    params = data.get("params", {})

    if not all([endpoint_id, file_path, file_type, metric_name]):
        return jsonify({"error": "Missing required fields: endpoint_id, file_path, file_type, metric_name"}), 400
    if not isinstance(params, dict):
        return jsonify({"error": "params must be a JSON object"}), 400

    task_id = None
    try:
        tokens = session.get("globus_tokens", {})
        client = get_compute_client(tokens)
        negotiation, report = _fresh_negotiation(client, endpoint_id)
        if negotiation is None:
            return jsonify({
                "error": "The Globus Compute endpoint is incompatible with this AIDRIN server.",
                "compatibility": report,
            }), 409

        requires_file_reference = _requires_file_reference_capability(metric_name, params)
        if requires_file_reference and FILE_REFERENCE_CAPABILITY not in negotiation["capabilities"]:
            return jsonify({"error": FILE_REFERENCE_UPGRADE_MESSAGE}), 409
        if requires_file_reference and any(key in params for key in ("allowed_roots", "scan_limit")):
            return jsonify({"error": "Filesystem roots and scan limits are controlled by the Compute worker."}), 400

        # Check cache for summary_statistics (avoid redundant remote calls on page reload)
        if metric_name == "summary_statistics":
            cache_key = f"globus_summary:{endpoint_id}:{file_path}"
            cached = current_app.TEMP_RESULTS_CACHE.get(cache_key)
            if cached and cached.get("data"):
                logger.info("Globus summary cache hit: %s", cache_key)
                return jsonify({
                    "status": "completed",
                    "result": cached["data"],
                    "cached": True,
                })
        # Store endpoint info in session for subsequent metric submissions
        session["globus_endpoint_id"] = endpoint_id
        session["globus_file_path"] = file_path
        session["globus_file_name"] = file_name
        session["globus_file_type"] = file_type

        task_id = submit_metric(
            client, endpoint_id, metric_name,
            file_path, file_name, file_type,
            **params,
        )

        # Track active task for cancellation on clear/disconnect
        active = session.get("globus_active_tasks", [])
        active.append(task_id)
        session["globus_active_tasks"] = active

        operation = "target_discovery" if metric_name == "custom_outlier_targets" else "metric_execution"
        expected_capability = (
            FILE_REFERENCE_CAPABILITY
            if operation == "target_discovery" and FILE_REFERENCE_CAPABILITY in negotiation["capabilities"]
            else None
        )
        contexts = session.get("globus_task_contexts", {})
        contexts[task_id] = {
            "endpoint_id": endpoint_id,
            "metric_name": metric_name,
            "operation": operation,
            "expected_capability": expected_capability,
            "negotiation_fingerprint": negotiation["fingerprint"],
        }
        session["globus_task_contexts"] = contexts

        response = {
            "task_id": task_id,
            "is_async": True,
            "status": "processing",
            "message": f"Task submitted to Globus Compute endpoint {endpoint_id}",
            "backend": "globus",
        }
        if operation == "target_discovery":
            response["negotiation_expires_at"] = negotiation["checked_at"] + NEGOTIATION_TTL_SECONDS
        return jsonify(response)

    except Exception as e:
        if task_id is not None:
            try:
                client.stop(task_id)
            except Exception as cancel_error:
                logger.warning("Failed to cancel rolled-back Globus task %s: %s", task_id, cancel_error)
            _remove_task_tracking(task_id)
        logger.error("Globus submit error: %s", e, exc_info=True)
        return jsonify({"error": "Failed to submit task"}), 500


@globus_bp.route("/cache-summary", methods=["POST"])
def cache_summary():
    """Cache the Globus summary statistics result to avoid re-fetching on page reload."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    endpoint_id = session.get("globus_endpoint_id", "")
    file_path = session.get("globus_file_path", "")
    if not endpoint_id or not file_path:
        return jsonify({"error": "No Globus file in session"}), 400

    cache_key = f"globus_summary:{endpoint_id}:{file_path}"
    current_app.TEMP_RESULTS_CACHE[cache_key] = {
        "data": data,
        "timestamp": __import__("time").time(),
    }
    logger.info("Cached Globus summary: %s", cache_key)
    return jsonify({"success": True})


@globus_bp.route("/check-task/<task_id>")
def check_task_status(task_id):
    """Poll a Globus Compute task status.

    Returns the same format as ``/check-and-update-task``:
    ``{"status": "processing|completed|failed", "result": ..., "progress": ...}``
    """
    if not session.get("globus_authenticated"):
        return jsonify({"error": "Not authenticated with Globus"}), 401

    try:
        tokens = session.get("globus_tokens", {})
        client = get_compute_client(tokens)
        result = check_task(client, task_id)
        context = session.get("globus_task_contexts", {}).get(task_id, {})

        if (
            result.get("status") == "completed"
            and context.get("operation") == "target_discovery"
            and context.get("expected_capability") == FILE_REFERENCE_CAPABILITY
            and isinstance(result.get("result"), dict)
            and result["result"].get("success") is True
            and not _valid_file_reference_discovery(result["result"].get("file_reference"))
        ):
            invalidated = _remove_file_reference_capability(context)
            result["result"]["file_reference"] = {
                "enabled": False,
                "roots": [],
                "scan_limit": 10000,
                "message": FILE_REFERENCE_UPGRADE_MESSAGE,
            }
            result["capability_invalidated"] = invalidated

        # Remove from active tasks if done
        if result.get("status") in ("completed", "failed"):
            _remove_task_tracking(task_id)

        return jsonify(result)

    except Exception as e:
        logger.error("Globus check-task error: %s", e, exc_info=True)
        return jsonify({"status": "failed", "error": "An internal error occurred"}), 500
