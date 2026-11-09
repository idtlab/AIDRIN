"""Thin upload/selection adapter for the shared file-collection pilot."""

import json
import logging
import os
from pathlib import Path
import tempfile
import uuid

from flask import Blueprint, current_app, jsonify, render_template, request, session
from werkzeug.utils import secure_filename

from aidrin.file_handling.collection import CollectionMember
from aidrin.file_handling.file_parser import READER_MAP, _frame_cache_path
from aidrin.headless.collection import collection_metrics, run_collection_metrics
from aidrin.headless.runners import _normalize_file_type
from web.routes.utils import confine_to_upload_folder, ensure_json_serializable


collections_bp = Blueprint("collections", __name__, url_prefix="/collections")
logger = logging.getLogger(__name__)


def _files():
    path = confine_to_upload_folder(session.get("collection_manifest"))
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as handle:
        files = json.load(handle)
    for entry in files:
        path = confine_to_upload_folder(entry["path"])
        if not path:
            raise ValueError("Collection input is no longer available; upload the files again")
        entry["path"] = path
        if entry.get("cache_path"):
            entry["cache_path"] = confine_to_upload_folder(entry["cache_path"])
    return files


def _public_files(files):
    return [{key: entry[key] for key in ("id", "name", "columns")} for entry in files]


@collections_bp.route("")
def page():
    return render_template("collections.html", metrics=collection_metrics())


@collections_bp.route("/files", methods=["GET", "POST"])
def files():
    created = []
    try:
        entries = _files()
        if request.method == "GET":
            return jsonify({"files": _public_files(entries)})
        uploads = [upload for upload in request.files.getlist("file") if upload and upload.filename]
        if not uploads:
            raise ValueError("Select at least one file to upload")
        limit = current_app.config.get("AIDRIN_MAX_UPLOAD_FILES", 50)
        if len(entries) + len(uploads) > limit:
            raise ValueError(f"A collection can contain at most {limit} files")
        additions = []
        for upload in uploads:
            file_type = _normalize_file_type(None, upload.filename)
            if file_type not in READER_MAP or file_type == ".zarr":
                raise ValueError(f"Unsupported collection upload format: {Path(upload.filename).suffix}")
            identity = uuid.uuid4().hex
            path = confine_to_upload_folder(os.path.join(
                current_app.config["UPLOAD_FOLDER"], f"{identity}_{secure_filename(upload.filename)}",
            ))
            if not path:
                raise ValueError("Unable to save collection upload")
            created.append(path)
            upload.save(path)
            member = CollectionMember(identity, path, upload.filename, file_type)
            try:
                frame = member.load()
            finally:
                cache_path = _frame_cache_path(path)
                if os.path.isfile(cache_path):
                    created.append(cache_path)
            additions.append({"id": identity, "path": path, "name": upload.filename,
                              "file_type": file_type, "columns": list(frame.columns),
                              "cache_path": cache_path if os.path.isfile(cache_path) else None})
        path = confine_to_upload_folder(session.get("collection_manifest"))
        if not path:
            path = os.path.join(current_app.config["UPLOAD_FOLDER"], f"collection_{uuid.uuid4().hex}.json")
        # Replace the inventory only after every new member is validated. A
        # failed upload leaves the previous collection and selection intact.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=current_app.config["UPLOAD_FOLDER"], delete=False) as handle:
            temporary = handle.name
            created.append(temporary)
            json.dump(entries + additions, handle)
        os.replace(temporary, path)
        session["collection_manifest"] = path
        return jsonify({"files": _public_files(entries + additions)})
    except ValueError as exc:
        message = str(exc)
    except Exception:
        logger.exception("Collection upload failed")
        message = "Unable to load the collection. Check the files and upload them again."
    for path in created:
        if os.path.isfile(path):
            os.remove(path)
    return jsonify({"error": message}), 400


def clear_collection_uploads():
    """Remove this inventory's upload copies without storing paths in cookies."""
    paths = []
    for entry in _files():
        paths.append(entry["path"])
        if entry.get("cache_path"):
            paths.append(entry["cache_path"])
    manifest = confine_to_upload_folder(session.get("collection_manifest"))
    if manifest:
        paths.append(manifest)
    for path in paths:
        if os.path.isfile(path):
            os.remove(path)
    session.pop("collection_manifest", None)


@collections_bp.route("/clear", methods=["POST"])
def clear():
    clear_collection_uploads()
    return jsonify({"files": []})


@collections_bp.route("/run", methods=["POST"])
def run():
    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) - {"file_ids", "metrics", "mode"}:
            raise ValueError("Provide file_ids, metrics and mode")
        ids = payload.get("file_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(identity, str) for identity in ids) or len(set(ids)) != len(ids):
            raise ValueError("Select a non-empty ordered list of distinct file IDs")
        entries = {entry["id"]: entry for entry in _files()}
        if any(identity not in entries for identity in ids):
            raise ValueError("A selected file is not in this session's collection")
        members = [CollectionMember(**{key: entries[identity][key] for key in ("id", "path", "name", "file_type")}) for identity in ids]
        result = run_collection_metrics(members, payload.get("metrics"), mode=payload.get("mode", "independent"))
        return jsonify(ensure_json_serializable(result))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("Collection assessment failed")
        return jsonify({"error": "Collection assessment failed. Check the selected inputs and settings."}), 400
