"""Session-owned files available to the Inspector."""

import json
import logging
import os
import tempfile
import threading
import uuid

from flask import current_app, session
from werkzeug.utils import secure_filename

from aidrin.file_handling.file_parser import READER_MAP, clear_frame_cache
from aidrin.headless.runners import _normalize_file_type
from web.routes.utils import clear_all_user_cache, confine_to_upload_folder


logger = logging.getLogger(__name__)
_inventory_lock = threading.RLock()
_LOCAL_DATASET_KEYS = ("uploaded_file_path", "uploaded_file_name", "uploaded_file_type", "custom_loader_spec", "selected_keys")
_REMOTE_DATASET_KEYS = ("globus_file_path", "globus_file_name", "globus_file_type")


def _manifest_path():
    return confine_to_upload_folder(session.get("collection_manifest"))


def init_workspace():
    """Allocate an inventory identity before the browser can submit an upload."""
    if not _manifest_path():
        session["collection_manifest"] = os.path.join(current_app.config["UPLOAD_FOLDER"], f"collection_{uuid.uuid4().hex}.json")


def workspace_files():
    manifest = _manifest_path()
    if not manifest or not os.path.isfile(manifest):
        return []
    with open(manifest, encoding="utf-8") as handle:
        entries = json.load(handle)
    for entry in entries:
        if entry["source"] == "local":
            path = confine_to_upload_folder(entry["path"])
            if not path:
                raise ValueError("An uploaded file is unavailable. Upload it again.")
            entry["path"] = path
    return entries


def _save_inventory(entries):
    init_workspace()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=current_app.config["UPLOAD_FOLDER"], delete=False) as handle:
            temporary = handle.name
            json.dump(entries, handle)
        os.replace(temporary, _manifest_path())
    finally:
        if temporary:
            _remove(temporary)


def workspace_file_limit():
    return current_app.config.get("AIDRIN_MAX_UPLOAD_FILES", 50)


def save_workspace_upload(upload, file_type):
    identity = uuid.uuid4().hex
    path = confine_to_upload_folder(os.path.join(
        current_app.config["UPLOAD_FOLDER"], f"{identity}_{secure_filename(upload.filename)}",
    ))
    if not path:
        raise ValueError("Unable to save the upload.")
    try:
        upload.save(path)
    except Exception:
        _remove(path)
        raise
    return {"id": identity, "path": path, "name": upload.filename, "file_type": file_type, "source": "local"}


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Unable to remove a workspace upload", exc_info=True)


def _require_capacity(count):
    limit = workspace_file_limit()
    if count > limit:
        raise ValueError(f"Workspace file limit: {limit}.")


def add_workspace_uploads(uploads, selected_type):
    """Store a batch atomically without reading its tables."""
    selected_type = None if selected_type in ("auto", "") else selected_type
    types = [_normalize_file_type(selected_type, upload.filename) for upload in uploads]
    for upload, file_type in zip(uploads, types):
        if file_type not in READER_MAP or file_type == ".zarr":
            raise ValueError(f"Unsupported file type: {upload.filename}.")
        if len(uploads) > 1 and _normalize_file_type(None, upload.filename) != file_type:
            raise ValueError("Choose files matching the selected file type, or select Auto-detect.")
    _require_capacity(len(uploads))

    added = []
    try:
        for upload, file_type in zip(uploads, types):
            added.append(save_workspace_upload(upload, file_type))
        with _inventory_lock:
            entries = workspace_files()
            _require_capacity(len(entries) + len(added))
            _save_inventory(entries + added)
    except Exception:
        for entry in added:
            _remove(entry["path"])
        raise
    return added[0]


def add_globus_files(endpoint_id, files):
    """Store remote references and summaries without opening paths on the server."""
    with _inventory_lock:
        entries = workspace_files()
        known = {(entry.get("endpoint_id"), entry["path"]): entry for entry in entries if entry["source"] == "globus"}
        added = []
        for file in files:
            key = endpoint_id, file["path"]
            if key in known:
                known[key]["summary"] = file["summary"]
            else:
                entry = {**file, "id": uuid.uuid4().hex, "source": "globus", "endpoint_id": endpoint_id}
                known[key] = entry
                added.append(entry)
        _require_capacity(len(entries) + len(added))
        _save_inventory(entries + added)
        return known[endpoint_id, files[0]["path"]]


def available_workspace_file(entry):
    if entry["source"] == "globus":
        return bool(session.get("globus_authenticated"))
    return os.path.isfile(entry["path"])


def reset_workspace_selection():
    clear_all_user_cache()
    for key in (*_LOCAL_DATASET_KEYS, *_REMOTE_DATASET_KEYS, "active_workspace_file_id", "intent", "upload_error", "minimize_preview"):
        session.pop(key, None)


def activate_workspace_file(entry):
    reset_workspace_selection()
    session["active_workspace_file_id"] = entry["id"]
    if entry["source"] == "globus":
        negotiation = session.get("globus_endpoint_negotiation", {})
        session["globus_capabilities"] = negotiation.get("capabilities", []) if negotiation.get("endpoint_id") == entry["endpoint_id"] else []
        session["globus_endpoint_id"] = entry["endpoint_id"]
        session["globus_file_path"] = entry["path"]
        session["globus_file_name"] = entry["name"]
        session["globus_file_type"] = entry["file_type"]
    else:
        session["uploaded_file_path"] = entry["path"]
        session["uploaded_file_name"] = entry["name"]
        session["uploaded_file_type"] = entry["file_type"]


def _discard(entry):
    if entry["source"] == "local":
        clear_frame_cache(entry["path"])
        _remove(entry["path"])
    else:
        cache_key = f"globus_summary:{entry['endpoint_id']}:{entry['path']}"
        current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)


def remove_workspace_file(file_id):
    with _inventory_lock:
        entries = workspace_files()
        entry = next((file for file in entries if file["id"] == file_id), None)
        if entry is None:
            return False
        remaining = [file for file in entries if file["id"] != file_id]
        _save_inventory(remaining)
        if file_id == session.get("active_workspace_file_id"):
            replacement = next((file for file in remaining if available_workspace_file(file)), None)
            if replacement is None:
                reset_workspace_selection()
            else:
                activate_workspace_file(replacement)
        else:
            clear_all_user_cache()
        _discard(entry)
        return True


def clear_workspace_uploads(source=None):
    with _inventory_lock:
        try:
            entries = workspace_files()
        except (OSError, ValueError):
            logger.warning("Unable to read the workspace inventory during clear", exc_info=True)
            entries = []
        if source is None:
            manifest = _manifest_path()
            session.pop("collection_manifest", None)
            if manifest:
                _remove(manifest)
        else:
            remaining = [entry for entry in entries if entry["source"] != source]
            if len(entries) != len(remaining):
                _save_inventory(remaining)
        for entry in entries:
            if source is None or entry["source"] == source:
                _discard(entry)


def workspace_collection_members(form):
    """Resolve ordered IDs against the current session's local inventory."""
    from aidrin.file_handling.collection import CollectionMember

    entries = {entry["id"]: entry for entry in workspace_files() if entry["source"] == "local"}
    if form.get("collection_scope") == "all":
        ids = form.getlist("collection_file_order") or list(entries)
        if len(ids) != len(entries) or set(ids) != set(entries):
            raise ValueError("The uploaded files changed. Reload the Inspector to check all files.")
    else:
        ids = form.getlist("collection_file_id")
        if any(file_id not in entries for file_id in ids):
            raise ValueError("A selected file is not in this workspace.")
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Select one or more distinct files from the workspace.")
    return [CollectionMember(entry["id"], entry["path"], entry["name"], entry["file_type"])
            for entry in (entries[file_id] for file_id in ids)]
