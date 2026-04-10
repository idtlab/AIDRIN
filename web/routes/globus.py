"""Flask routes for Globus Compute integration.

All routes are under the ``/globus`` prefix. The blueprint is only
registered when ``globus-compute-sdk`` is installed.
"""

import logging

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
)

logger = logging.getLogger(__name__)

globus_bp = Blueprint("globus", __name__, url_prefix="/globus")


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
        return jsonify({"error": str(e)}), 500


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
        logger.error("Globus Auth callback error: %s", e)
        return jsonify({"error": f"Authentication failed: {str(e)}"}), 500


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
    return jsonify({"success": True})


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

    try:
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
        tokens = session.get("globus_tokens", {})
        client = get_compute_client(tokens)

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

        return jsonify({
            "task_id": task_id,
            "is_async": True,
            "status": "processing",
            "message": f"Task submitted to Globus Compute endpoint {endpoint_id}",
            "backend": "globus",
        })

    except Exception as e:
        logger.error("Globus submit error: %s", e)
        return jsonify({"error": f"Failed to submit task: {str(e)}"}), 500


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

        # Remove from active tasks if done
        if result.get("status") in ("completed", "failed"):
            active = session.get("globus_active_tasks", [])
            if task_id in active:
                active.remove(task_id)
                session["globus_active_tasks"] = active

        return jsonify(result)

    except Exception as e:
        logger.error("Globus check-task error: %s", e)
        return jsonify({"status": "failed", "error": str(e)}), 500
