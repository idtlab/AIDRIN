"""File-management endpoints for multi-file batches."""

import os

from flask import Blueprint, jsonify, session

from web.routes.utils import (
    get_uploaded_files, save_uploaded_files, set_active_file, clear_uploaded_files,
)

files_bp = Blueprint("files", __name__)


@files_bp.route("/files", methods=["GET"])
def list_files():
    files = get_uploaded_files()
    public = [{k: f.get(k) for k in ("id", "name", "type", "source")} for f in files]
    return jsonify({"files": public, "active_file_id": session.get("active_file_id")})


@files_bp.route("/files/<file_id>/activate", methods=["POST"])
def activate(file_id):
    if set_active_file(file_id):
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Unknown file"}), 404


@files_bp.route("/files/summary", methods=["GET"])
def summary():
    import aidrin
    files = get_uploaded_files()
    local = [f for f in files if f.get("source") == "local"]
    globus = [f for f in files if f.get("source") == "globus"]

    local_summary = aidrin.summarize_files(
        [(f["path"], f["name"], f["type"]) for f in local]
    )
    rows = []
    for f, row in zip(local, local_summary["files"]):
        rows.append({**row, "id": f["id"], "source": "local"})
    for f in globus:
        rows.append({
            "id": f["id"], "name": f["name"], "type": f["type"], "source": "globus",
            "records": None, "features": None, "size_bytes": None,
            "status": "remote", "error": None,
        })
    totals = dict(local_summary["totals"])
    totals["file_count"] = len(files)
    totals["by_source"] = {"local": len(local), "globus": len(globus)}
    return jsonify({"files": rows, "totals": totals})


@files_bp.route("/files/<file_id>/remove", methods=["POST"])
def remove(file_id):
    files = get_uploaded_files()
    entry = next((f for f in files if f["id"] == file_id), None)
    if entry is None:
        return jsonify({"success": False, "message": "Unknown file"}), 404
    if entry.get("source") == "local":
        try:
            if entry["path"] and os.path.exists(entry["path"]):
                os.remove(entry["path"])
        except OSError:
            pass
    remaining = [f for f in files if f["id"] != file_id]
    save_uploaded_files(remaining)
    if session.get("active_file_id") == file_id:
        if remaining:
            set_active_file(remaining[0]["id"])
        else:
            clear_uploaded_files()
    return jsonify({"success": True})
