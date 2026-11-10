"""Session-owned local files available to the Inspector."""

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
_inventory_lock = threading.Lock()


def workspace_files():
    """Read the on-disk inventory, including inventories from the pilot."""
    manifest = confine_to_upload_folder(session.get("collection_manifest"))
    if not manifest or not os.path.isfile(manifest):
        return []
    with open(manifest, encoding="utf-8") as handle:
        entries = json.load(handle)
    for entry in entries:
        path = confine_to_upload_folder(entry["path"])
        if not path:
            raise ValueError("An uploaded file is unavailable. Upload it again.")
        entry["path"] = path
    return entries


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
    return {"id": identity, "path": path, "name": upload.filename, "file_type": file_type}


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Unable to remove a workspace upload", exc_info=True)


def add_workspace_uploads(uploads, selected_type):
    """Store a batch atomically without reading its tables."""
    types = [_normalize_file_type(selected_type or None, upload.filename) for upload in uploads]
    if any(file_type not in READER_MAP or file_type == ".zarr" for file_type in types):
        raise ValueError("Select a supported file type.")
    if len(uploads) > 1 and any(_normalize_file_type(None, upload.filename) != file_type
                                for upload, file_type in zip(uploads, types)):
        raise ValueError("Choose files matching the selected file type.")

    limit = current_app.config.get("AIDRIN_MAX_UPLOAD_FILES", 50)
    if len(uploads) > limit:
        raise ValueError(f"Workspace file limit: {limit}.")
    added = []
    temporary = None
    try:
        for upload, file_type in zip(uploads, types):
            added.append(save_workspace_upload(upload, file_type))
        with _inventory_lock:
            entries = workspace_files()
            active = confine_to_upload_folder(session.get("uploaded_file_path"))
            active_type = session.get("uploaded_file_type")
            if (active and os.path.isfile(active) and active_type in READER_MAP
                    and not session.get("custom_loader_spec") and all(entry["path"] != active for entry in entries)):
                entries.append({"id": uuid.uuid4().hex, "path": active, "name": session.get("uploaded_file_name"),
                                "file_type": active_type})

            if len(entries) + len(uploads) > limit:
                raise ValueError(f"Workspace file limit: {limit}.")
            if not entries and len(added) == 1:
                # The existing single-file workflow tracks ownership in the
                # session. Start the inventory when the workspace has a batch.
                session["owned_files"] = session.get("owned_files", []) + [added[0]["path"]]
                return added[0]

            manifest = confine_to_upload_folder(session.get("collection_manifest"))
            if not manifest:
                manifest = os.path.join(current_app.config["UPLOAD_FOLDER"], f"collection_{uuid.uuid4().hex}.json")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=current_app.config["UPLOAD_FOLDER"], delete=False) as handle:
                temporary = handle.name
                json.dump(entries + added, handle)
            os.replace(temporary, manifest)
            session["collection_manifest"] = manifest
    except Exception:
        for entry in added:
            _remove(entry["path"])
        if temporary:
            _remove(temporary)
        raise
    return added[0]


def activate_workspace_file(entry):
    clear_all_user_cache()
    session["uploaded_file_path"] = entry["path"]
    session["uploaded_file_name"] = entry["name"]
    session["uploaded_file_type"] = entry["file_type"]
    for key in ("selected_keys", "intent", "custom_loader_spec", "upload_error", "minimize_preview", "globus_file_path"):
        session.pop(key, None)


def clear_workspace_uploads():
    try:
        entries = workspace_files()
    except (OSError, ValueError):
        logger.warning("Unable to read the workspace inventory during clear", exc_info=True)
        entries = []
    for entry in entries:
        clear_frame_cache(entry["path"])
        _remove(entry["path"])
        old_cache_path = confine_to_upload_folder(entry.get("cache_path"))
        if old_cache_path:
            _remove(old_cache_path)
    manifest = confine_to_upload_folder(session.pop("collection_manifest", None))
    if manifest:
        _remove(manifest)
