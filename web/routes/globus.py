"""Flask routes for Globus Compute integration.

All routes are under the ``/globus`` prefix. The blueprint is only
registered when ``globus-compute-sdk`` is installed.
"""

import logging
import uuid

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
    submit_list_files,
    check_task,
)
from web.routes.utils import get_uploaded_files, save_uploaded_files, set_active_file

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

        # Add the selected Globus file to the shared multi-file list and make it
        # active.  set_active_file() repopulates the globus_* session keys so
        # any downstream code that still reads those keys continues to work.
        entries = get_uploaded_files()
        # Avoid duplicate entries for the same endpoint + path combination.
        existing = next(
            (e for e in entries
             if e.get("source") == "globus"
             and e.get("endpoint_id") == endpoint_id
             and e.get("path") == file_path),
            None,
        )
        if existing is None:
            entry = {
                "id": uuid.uuid4().hex,
                "name": file_name,
                "type": file_type,
                "path": file_path,
                "source": "globus",
                "endpoint_id": endpoint_id,
            }
            entries.append(entry)
            save_uploaded_files(entries)
        else:
            entry = existing
        set_active_file(entry["id"])  # also repopulates globus_* session keys

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
        logger.error("Globus submit error: %s", e, exc_info=True)
        return jsonify({"error": "Failed to submit task"}), 500


@globus_bp.route("/add-files", methods=["POST"])
def add_files():
    """Add a remote file OR every supported file in a remote directory.

    Body: ``{"endpoint_id": "...", "path": "/remote/file-or-dir"}``.

    Ships a listing function to the endpoint (blocking with a timeout), then
    infers each file's type server-side (so it doesn't depend on the endpoint's
    aidrin version), adds the supported ones to the shared batch as
    ``source:"globus"`` entries, and activates the first new one. Unsupported
    files are reported as ``skipped``.
    """
    import time
    from aidrin.file_handling.file_parser import infer_file_type

    if not session.get("globus_authenticated"):
        return jsonify({"error": "Not authenticated with Globus"}), 401

    data = request.get_json() or {}
    endpoint_id = data.get("endpoint_id")
    path = data.get("path")
    if not endpoint_id or not path:
        return jsonify({"error": "Missing required fields: endpoint_id, path"}), 400

    try:
        client = get_compute_client(session.get("globus_tokens", {}))
        task_id = submit_list_files(client, endpoint_id, path)

        # Block for the listing result (it's quick on the endpoint).
        deadline = time.time() + 60
        result = None
        while time.time() < deadline:
            status = check_task(client, task_id)
            if status.get("status") == "completed":
                result = status.get("result")
                break
            if status.get("status") == "failed":
                return jsonify({"error": status.get("error", "Remote listing failed")}), 502
            time.sleep(1)
        if result is None:
            return jsonify({"error": "Timed out listing remote files"}), 504
        if isinstance(result, dict) and result.get("error"):
            return jsonify({"error": result["error"]}), 400

        files = result.get("files", []) if isinstance(result, dict) else []
        if not files:
            return jsonify({"error": "No files found at that path"}), 400

        max_files = current_app.config.get("AIDRIN_MAX_UPLOAD_FILES", 50)
        entries = get_uploaded_files()
        added, skipped = [], []
        first_id = None
        for p in files:
            name = p.rstrip("/").split("/")[-1]
            ftype = infer_file_type(name)
            if not ftype:
                skipped.append(name)
                continue
            if len(entries) >= max_files:
                skipped.append(name)
                continue
            existing = next(
                (e for e in entries
                 if e.get("source") == "globus"
                 and e.get("endpoint_id") == endpoint_id
                 and e.get("path") == p),
                None,
            )
            if existing is not None:
                if first_id is None:
                    first_id = existing["id"]
                continue
            entry = {
                "id": uuid.uuid4().hex,
                "name": name,
                "type": ftype,
                "path": p,
                "source": "globus",
                "endpoint_id": endpoint_id,
            }
            entries.append(entry)
            added.append(name)
            if first_id is None:
                first_id = entry["id"]

        save_uploaded_files(entries)
        if first_id:
            set_active_file(first_id)  # repopulates globus_* session keys

        if not added and not first_id:
            return jsonify({
                "error": "No supported files found. Supported: CSV, Excel, "
                         "JSON, NumPy (.npz), HDF5."
            }), 400

        return jsonify({
            "added": added,
            "skipped": skipped,
            "active_file_id": first_id,
        })

    except Exception as e:
        logger.error("Globus add-files error: %s", e, exc_info=True)
        return jsonify({"error": "Failed to add remote files"}), 500


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
        logger.error("Globus check-task error: %s", e, exc_info=True)
        return jsonify({"status": "failed", "error": "An internal error occurred"}), 500
