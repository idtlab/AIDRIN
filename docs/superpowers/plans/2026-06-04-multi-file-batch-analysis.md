# Multi-File Batch Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let AIDRIN analyze many independent files at once — an active-file switcher plus a "Batch Overview" landing summary — fed by both local multi-upload and Globus.

**Architecture:** Two layers. (1) A session-free **core** primitive in `aidrin` (`summarize_files`, `infer_file_type`). (2) A **web** active-file shim: a server-side `uploaded_files` list + `active_file_id`; `set_active_file` mirrors the active file's identity into the existing `uploaded_file_*` (and, for Globus, `globus_file_*`) session keys so every existing route keeps working unchanged. Execution stays dispatched by source (local routes vs. remote `remote_metric_runner`).

**Tech Stack:** Python 3.10+, Flask, pandas, pytest (unit + integration via `tests/integration/conftest.py`), vanilla JS + Tailwind.

**Spec:** `docs/superpowers/specs/2026-06-04-multi-file-batch-analysis-design.md`

---

## Prerequisites & Cross-Branch Notes

- This branch (`multi-file-analysis`) is off `develop`. It does **not** have
  `MAX_CONTENT_LENGTH` (on `upload-size-limit`) or `load_dataframe` (on
  `parquet-support`). This plan adds the small pieces it needs directly
  (Milestone 4 adds the size cap + 413; `summarize_files` handles `read_file`'s
  tri-state itself), so it is self-contained.
- Run tests with the project venv: `.venv/bin/python -m pytest`.
- Follow TDD: write the failing test, watch it fail, implement minimally, watch it pass, commit.

## File Structure

**Create**
- `aidrin/batch.py` — `summarize_files(file_infos)` (session-free, no Celery).
- `tests/unit/test_infer_file_type.py`
- `tests/unit/test_summarize_files.py`
- `web/routes/files.py` — file-management blueprint (`/files`, activate, remove, summary).
- `web/templates/_components/file_switcher.html` — sidebar file list.
- `web/templates/_panels/_batch_overview.html` — batch overview panel.
- `tests/integration/test_files_routes.py`
- `tests/integration/test_multi_upload.py`

**Modify**
- `aidrin/file_handling/file_parser.py` — add `EXTENSION_MAP` + `infer_file_type`.
- `aidrin/__init__.py` — export `summarize_files`.
- `web/routes/utils.py` — file-list store + `set_active_file`; cache key → file_id.
- `web/routes/core.py` — multi-file `/inspector`; Globus-aware stale check; land on overview.
- `web/routes/__init__.py` — register the `files` blueprint.
- `web/routes/globus.py` — append selections into the shared list; fold `globus_file_*`.
- `web/__init__.py` — `MAX_CONTENT_LENGTH`, `AIDRIN_MAX_UPLOAD_FILES`, 413 handler.
- `web/templates/inspector.html` — include switcher + batch overview; default panel.
- `web/templates/_components/upload_panel.html` — `multiple`; remove type `<select>`.
- `web/static/js/main.js` — AJAX multi-file upload.
- `web/static/js/inspector.js` — switcher, batch overview render, async Globus counts.

---

## Milestone 1 — Core batch layer (session-free)

Independently testable; gives the library/CLI batch capability immediately.

### Task 1: `infer_file_type` (extension → reader key)

**Files:**
- Modify: `aidrin/file_handling/file_parser.py`
- Test: `tests/unit/test_infer_file_type.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_infer_file_type.py
import pytest
from aidrin.file_handling.file_parser import infer_file_type, READER_MAP


@pytest.mark.parametrize("filename,expected", [
    ("data.csv", ".csv"),
    ("DATA.CSV", ".csv"),                 # case-insensitive
    ("set.json", ".json"),
    ("a.npz", ".npz"),
    ("b.h5", ".h5"),
    ("c.parquet", ".parquet"),            # present only if parquet branch merged
    ("sheet.xlsx", ".xls, .xlsb, .xlsx, .xlsm"),
    ("sheet.xls", ".xls, .xlsb, .xlsx, .xlsm"),
])
def test_infer_known_extensions(filename, expected):
    if expected not in READER_MAP:
        pytest.skip(f"{expected} reader not registered on this branch")
    assert infer_file_type(filename) == expected


def test_infer_unknown_extension_returns_none():
    assert infer_file_type("notes.txt") is None
    assert infer_file_type("noext") is None


def test_infer_real_extension_helper():
    # The raw extension (for use as a real filename suffix) is exposed separately.
    from aidrin.file_handling.file_parser import file_extension
    assert file_extension("Sheet.XLSX") == ".xlsx"
    assert file_extension("a.csv") == ".csv"
    assert file_extension("noext") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_infer_file_type.py -v`
Expected: FAIL — `ImportError: cannot import name 'infer_file_type'`.

- [ ] **Step 3: Write minimal implementation**

Add to `aidrin/file_handling/file_parser.py` (after `SUPPORTED_FILE_TYPES`):

```python
import os

# Map a real file extension to the READER_MAP key that handles it.
# Excel uses a single combined reader key, so all its extensions point at it.
_EXCEL_KEY = ".xls, .xlsb, .xlsx, .xlsm"
EXTENSION_MAP = {
    ".csv": ".csv",
    ".json": ".json",
    ".npz": ".npz",
    ".h5": ".h5",
    ".parquet": ".parquet",
    ".xls": _EXCEL_KEY,
    ".xlsb": _EXCEL_KEY,
    ".xlsx": _EXCEL_KEY,
    ".xlsm": _EXCEL_KEY,
}


def file_extension(filename):
    """Return the lowercased real extension (e.g. ``.csv``), or ``""``."""
    return os.path.splitext(filename or "")[1].lower()


def infer_file_type(filename):
    """Return the READER_MAP key for a filename's extension, or None.

    Only returns a key that is actually registered in READER_MAP on this
    install (e.g. ``.parquet`` resolves only if the parquet reader exists).
    """
    key = EXTENSION_MAP.get(file_extension(filename))
    return key if key in READER_MAP else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_infer_file_type.py -v`
Expected: PASS (parquet case may `skip` if not merged).

- [ ] **Step 5: Commit**

```bash
git add aidrin/file_handling/file_parser.py tests/unit/test_infer_file_type.py
git commit -m "feat(core): infer reader type from file extension"
```

### Task 2: `summarize_files` (per-file structure + totals, no metrics)

**Files:**
- Create: `aidrin/batch.py`
- Modify: `aidrin/__init__.py`
- Test: `tests/unit/test_summarize_files.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_summarize_files.py
import os
import tempfile

import pandas as pd

from aidrin.batch import summarize_files


def _csv(rows="a,b\n1,2\n3,4\n"):
    f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    f.write(rows)
    f.close()
    return f.name


def test_ok_file_reports_structure_no_metrics():
    path = _csv()
    try:
        out = summarize_files([(path, "data.csv", ".csv")])
    finally:
        os.unlink(path)
    row = out["files"][0]
    assert row["status"] == "ok"
    assert row["records"] == 2
    assert row["features"] == 2
    assert row["size_bytes"] > 0
    assert row["error"] is None
    # No metric fields leak in:
    assert set(row.keys()) == {"name", "type", "records", "features",
                               "size_bytes", "status", "error"}


def test_unsupported_type_is_error_not_crash():
    out = summarize_files([("/nope/x.txt", "x.txt", ".txt")])
    row = out["files"][0]
    assert row["status"] == "error"
    assert row["records"] is None and row["features"] is None
    assert row["error"]


def test_missing_file_is_error():
    out = summarize_files([("/nope/missing.csv", "missing.csv", ".csv")])
    assert out["files"][0]["status"] == "error"


def test_one_bad_file_does_not_abort_batch():
    good = _csv()
    try:
        out = summarize_files([
            (good, "good.csv", ".csv"),
            ("/nope/bad.csv", "bad.csv", ".csv"),
        ])
    finally:
        os.unlink(good)
    statuses = [f["status"] for f in out["files"]]
    assert statuses == ["ok", "error"]


def test_totals():
    a = _csv("a,b\n1,2\n3,4\n5,6\n")   # 3 rows
    b = _csv("x\n1\n")                  # 1 row
    try:
        out = summarize_files([
            (a, "a.csv", ".csv"),
            (b, "b.csv", ".csv"),
            ("/nope/c.csv", "c.csv", ".csv"),
        ])
    finally:
        os.unlink(a); os.unlink(b)
    t = out["totals"]
    assert t["file_count"] == 3
    assert t["ok_count"] == 2
    assert t["error_count"] == 1
    assert t["total_records"] == 4
    assert t["by_type"] == {".csv": 3}


def test_empty_input():
    out = summarize_files([])
    assert out["files"] == []
    assert out["totals"]["file_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_summarize_files.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aidrin.batch'`.

- [ ] **Step 3: Write minimal implementation**

```python
# aidrin/batch.py
"""Session-free batch helpers shared by the web UI, CLI, and library users."""

import os

import pandas as pd

from aidrin.file_handling.file_parser import read_file


def _summarize_one(file_info):
    path, name, ftype = file_info
    size = None
    try:
        if path and os.path.exists(path):
            size = os.path.getsize(path)
    except OSError:
        size = None

    result = read_file(file_info)  # DataFrame | None | str
    if isinstance(result, pd.DataFrame):
        return {
            "name": name, "type": ftype,
            "records": int(len(result)),
            "features": int(len(result.columns)),
            "size_bytes": size, "status": "ok", "error": None,
        }

    message = result if isinstance(result, str) else (
        "Could not read the file. The format may be unsupported or the file "
        "may be corrupted."
    )
    return {
        "name": name, "type": ftype,
        "records": None, "features": None,
        "size_bytes": size, "status": "error", "error": message,
    }


def summarize_files(file_infos):
    """Return {"files": [per_file, ...], "totals": {...}} for a list of files.

    Computes structural facts only (records, features, size, load status) — no
    metrics. A file that fails to load becomes a status:"error" row and never
    aborts the batch. ``file_infos`` is a list of (path, name, type) tuples.
    """
    files = [_summarize_one(fi) for fi in file_infos]
    by_type = {}
    for f in files:
        by_type[f["type"]] = by_type.get(f["type"], 0) + 1
    totals = {
        "file_count": len(files),
        "ok_count": sum(1 for f in files if f["status"] == "ok"),
        "error_count": sum(1 for f in files if f["status"] == "error"),
        "total_records": sum(f["records"] or 0 for f in files),
        "by_type": by_type,
    }
    return {"files": files, "totals": totals}
```

- [ ] **Step 4: Export from the package**

Add to `aidrin/__init__.py` (near the other public functions):

```python
def summarize_files(file_infos):
    """Per-file structural overview + totals for a batch of files (no metrics)."""
    from aidrin.batch import summarize_files as _fn
    return _fn(file_infos)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_summarize_files.py -v`
Expected: PASS (all 6).

- [ ] **Step 6: Commit**

```bash
git add aidrin/batch.py aidrin/__init__.py tests/unit/test_summarize_files.py
git commit -m "feat(core): summarize_files batch structural overview"
```

---

## Milestone 2 — Web file-list store + active-file shim

Server-side `uploaded_files` (avoids the cookie-size limit) and the compatibility shim.

### Task 3: File-list store + `set_active_file`

**Files:**
- Modify: `web/routes/utils.py`
- Test: `tests/integration/test_files_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_files_routes.py
def test_set_active_file_mirrors_legacy_keys(app):
    from web.routes.utils import (
        save_uploaded_files, set_active_file, get_uploaded_files,
    )
    with app.test_request_context("/"):
        from flask import session
        save_uploaded_files([
            {"id": "f1", "name": "a.csv", "type": ".csv",
             "path": "/tmp/a.csv", "source": "local"},
            {"id": "f2", "name": "b.csv", "type": ".csv",
             "path": "/tmp/b.csv", "source": "local"},
        ])
        ok = set_active_file("f2")
        assert ok is True
        assert session["active_file_id"] == "f2"
        # Legacy keys mirror the active file so existing routes keep working:
        assert session["uploaded_file_path"] == "/tmp/b.csv"
        assert session["uploaded_file_name"] == "b.csv"
        assert session["uploaded_file_type"] == ".csv"
        assert len(get_uploaded_files()) == 2


def test_set_active_globus_mirrors_globus_keys(app):
    from web.routes.utils import save_uploaded_files, set_active_file
    with app.test_request_context("/"):
        from flask import session
        save_uploaded_files([
            {"id": "g1", "name": "r.csv", "type": ".csv",
             "path": "/remote/r.csv", "source": "globus",
             "endpoint_id": "ep-123"},
        ])
        set_active_file("g1")
        assert session["uploaded_file_path"] == "/remote/r.csv"
        assert session["globus_file_path"] == "/remote/r.csv"
        assert session["globus_file_name"] == "r.csv"
        assert session["globus_file_type"] == ".csv"
        assert session["globus_endpoint_id"] == "ep-123"


def test_set_active_unknown_id_returns_false(app):
    from web.routes.utils import save_uploaded_files, set_active_file
    with app.test_request_context("/"):
        save_uploaded_files([])
        assert set_active_file("nope") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_files_routes.py -v`
Expected: FAIL — `ImportError: cannot import name 'save_uploaded_files'`.

- [ ] **Step 3: Write minimal implementation**

Add to `web/routes/utils.py` (after `get_current_user_id`):

```python
def _files_cache_key():
    return f"uploaded_files:{get_current_user_id()}"


def get_uploaded_files():
    """Return the server-side list of uploaded files for the current user."""
    return current_app.TEMP_RESULTS_CACHE.get(_files_cache_key(), [])


def save_uploaded_files(files):
    """Persist the file list server-side (kept out of the session cookie)."""
    current_app.TEMP_RESULTS_CACHE[_files_cache_key()] = files


def get_active_file():
    """Return the active file entry dict, or None."""
    active_id = session.get("active_file_id")
    for f in get_uploaded_files():
        if f["id"] == active_id:
            return f
    return None


def set_active_file(file_id):
    """Make file_id active and mirror its identity into the legacy session keys.

    Returns True if the file exists, else False. For a Globus entry, also
    repopulates the globus_* keys that the remote path + cache still read.
    """
    entry = next((f for f in get_uploaded_files() if f["id"] == file_id), None)
    if entry is None:
        return False
    session["active_file_id"] = file_id
    session["uploaded_file_path"] = entry["path"]
    session["uploaded_file_name"] = entry["name"]
    session["uploaded_file_type"] = entry["type"]
    if entry.get("source") == "globus":
        session["globus_file_path"] = entry["path"]
        session["globus_file_name"] = entry["name"]
        session["globus_file_type"] = entry["type"]
        session["globus_endpoint_id"] = entry.get("endpoint_id")
    else:
        for k in ("globus_file_path", "globus_file_name",
                  "globus_file_type", "globus_endpoint_id"):
            session.pop(k, None)
    return True


def clear_uploaded_files():
    """Remove the file list and all active/legacy file pointers."""
    current_app.TEMP_RESULTS_CACHE.pop(_files_cache_key(), None)
    for k in ("active_file_id", "uploaded_file_path", "uploaded_file_name",
              "uploaded_file_type", "globus_file_path", "globus_file_name",
              "globus_file_type", "globus_endpoint_id"):
        session.pop(k, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_files_routes.py -v`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add web/routes/utils.py tests/integration/test_files_routes.py
git commit -m "feat(web): server-side file list + active-file shim"
```

### Task 4: Re-key the metric cache to file_id

**Files:**
- Modify: `web/routes/utils.py` (`generate_metric_cache_key`, `store_result`), `web/routes/core.py` (`cached_result` lookup)
- Test: `tests/integration/test_files_routes.py`

- [ ] **Step 1: Write the failing test**

```python
def test_cache_key_uses_active_file_id_not_display_name(app):
    from web.routes.utils import save_uploaded_files, set_active_file, generate_metric_cache_key
    with app.test_request_context("/"):
        save_uploaded_files([
            {"id": "f1", "name": "dup.csv", "type": ".csv", "path": "/a/dup.csv", "source": "local"},
            {"id": "f2", "name": "dup.csv", "type": ".csv", "path": "/b/dup.csv", "source": "local"},
        ])
        set_active_file("f1")
        k1 = generate_metric_cache_key("dup.csv", "classimbalance", classes="y")
        set_active_file("f2")
        k2 = generate_metric_cache_key("dup.csv", "classimbalance", classes="y")
        assert k1 != k2  # same display name, different files → different keys
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_files_routes.py::test_cache_key_uses_active_file_id_not_display_name -v`
Expected: FAIL — keys are equal (keyed on display name).

- [ ] **Step 3: Write minimal implementation**

In `web/routes/utils.py`, change `generate_metric_cache_key`'s file part to prefer the active file id:

```python
def generate_metric_cache_key(file_name, metric_type, **params):
    """Generate a user-specific cache key for metrics."""
    user_id = get_current_user_id()
    file_token = session.get("active_file_id") or file_name
    cache_parts = [f"user:{user_id}", f"file:{file_token}"]
    # ... (rest unchanged)
```

And in `store_result`, key the user-scoped copy by the same token:

```python
    file_token = session.get("active_file_id") or (
        session.get("uploaded_file_name") or session.get("globus_file_name") or "unknown"
    )
    user_key = f"user:{user_id}:file:{file_token}:{metric_short}"
```

In `web/routes/core.py` `cached_result`, build the lookup key from `active_file_id` the same way (locate the `f"user:{user_id}:file:{file_name}:..."` construction and replace `file_name` with `session.get("active_file_id") or file_name`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_files_routes.py -v`
Expected: PASS. Also run the existing cache tests:
Run: `.venv/bin/python -m pytest tests/integration -k cache -v`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add web/routes/utils.py web/routes/core.py
git commit -m "fix(web): key metric cache by active file id"
```

---

## Milestone 3 — File-management endpoints + multi-file upload

### Task 5: `files` blueprint — list, activate, remove, summary

**Files:**
- Create: `web/routes/files.py`
- Modify: `web/routes/__init__.py`
- Test: `tests/integration/test_files_routes.py`

- [ ] **Step 1: Write the failing test**

```python
def _seed(app, client, entries):
    from web.routes.utils import save_uploaded_files
    with client.session_transaction() as sess:
        sess["user_id"] = "u-test"
    with app.test_request_context("/"):
        from flask import session
        session["user_id"] = "u-test"
        save_uploaded_files(entries)


def test_files_list_and_activate(app, client):
    _seed(app, client, [
        {"id": "f1", "name": "a.csv", "type": ".csv", "path": "/a.csv", "source": "local"},
        {"id": "f2", "name": "b.csv", "type": ".csv", "path": "/b.csv", "source": "local"},
    ])
    r = client.get("/files")
    data = r.get_json()
    assert {f["id"] for f in data["files"]} == {"f1", "f2"}
    r = client.post("/files/f2/activate")
    assert r.get_json()["success"] is True
    with client.session_transaction() as sess:
        assert sess["active_file_id"] == "f2"


def test_files_remove_active_activates_next(app, client, tmp_path):
    p = tmp_path / "a.csv"; p.write_text("x\n1\n")
    _seed(app, client, [
        {"id": "f1", "name": "a.csv", "type": ".csv", "path": str(p), "source": "local"},
        {"id": "f2", "name": "b.csv", "type": ".csv", "path": "/b.csv", "source": "local"},
    ])
    client.post("/files/f1/activate")
    r = client.post("/files/f1/remove")
    assert r.get_json()["success"] is True
    with client.session_transaction() as sess:
        assert sess["active_file_id"] == "f2"   # next file became active
    assert not p.exists()                       # local file deleted from disk
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_files_routes.py -k "files_list or remove_active" -v`
Expected: FAIL — 404 (routes not registered).

- [ ] **Step 3: Write minimal implementation**

```python
# web/routes/files.py
"""File-management endpoints for multi-file batches."""

import os

from flask import Blueprint, jsonify

from web.routes.utils import (
    get_uploaded_files, save_uploaded_files, set_active_file, get_active_file,
)

files_bp = Blueprint("files", __name__)


@files_bp.route("/files", methods=["GET"])
def list_files():
    from flask import session
    files = get_uploaded_files()
    public = [{k: f.get(k) for k in ("id", "name", "type", "source")} for f in files]
    return jsonify({"files": public, "active_file_id": session.get("active_file_id")})


@files_bp.route("/files/<file_id>/activate", methods=["POST"])
def activate(file_id):
    if set_active_file(file_id):
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Unknown file"}), 404


@files_bp.route("/files/<file_id>/remove", methods=["POST"])
def remove(file_id):
    from flask import session
    files = get_uploaded_files()
    entry = next((f for f in files if f["id"] == file_id), None)
    if entry is None:
        return jsonify({"success": False, "message": "Unknown file"}), 404
    # Delete the local file from disk (not remote Globus files).
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
            from web.routes.utils import clear_uploaded_files
            clear_uploaded_files()
    return jsonify({"success": True})
```

Register it in `web/routes/__init__.py` (follow the existing `register_blueprints` pattern — import `files_bp` and add `app.register_blueprint(files_bp)`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_files_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/routes/files.py web/routes/__init__.py tests/integration/test_files_routes.py
git commit -m "feat(web): files blueprint (list/activate/remove)"
```

### Task 6: `/files/summary` endpoint

**Files:**
- Modify: `web/routes/files.py`
- Test: `tests/integration/test_files_routes.py`

- [ ] **Step 1: Write the failing test**

```python
def test_files_summary_local(app, client, tmp_path):
    a = tmp_path / "a.csv"; a.write_text("x,y\n1,2\n3,4\n")
    _seed(app, client, [
        {"id": "f1", "name": "a.csv", "type": ".csv", "path": str(a), "source": "local"},
    ])
    r = client.get("/files/summary")
    data = r.get_json()
    assert data["totals"]["file_count"] == 1
    row = data["files"][0]
    assert row["records"] == 2 and row["features"] == 2
    assert row["source"] == "local"
    assert "completeness" not in row          # no metrics in phase 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_files_routes.py::test_files_summary_local -v`
Expected: FAIL — 404.

- [ ] **Step 3: Write minimal implementation**

Add to `web/routes/files.py`:

```python
@files_bp.route("/files/summary", methods=["GET"])
def summary():
    import aidrin
    files = get_uploaded_files()
    local = [f for f in files if f.get("source") == "local"]
    globus = [f for f in files if f.get("source") == "globus"]

    local_summary = aidrin.summarize_files(
        [(f["path"], f["name"], f["type"]) for f in local]
    )
    # decorate local rows with source + id (sorted by name later in JS)
    rows = []
    for f, row in zip(local, local_summary["files"]):
        rows.append({**row, "id": f["id"], "source": "local"})
    # Globus rows: metadata now; records/features fetched async by the client.
    for f in globus:
        rows.append({
            "id": f["id"], "name": f["name"], "type": f["type"], "source": "globus",
            "records": None, "features": None, "size_bytes": None,
            "status": "remote", "error": None,
        })
    totals = dict(local_summary["totals"])
    totals["file_count"] = len(files)
    totals["by_source"] = {
        "local": len(local), "globus": len(globus),
    }
    return jsonify({"files": rows, "totals": totals})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_files_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/routes/files.py tests/integration/test_files_routes.py
git commit -m "feat(web): /files/summary batch overview endpoint"
```

### Task 7: Multi-file upload in `/inspector`

**Files:**
- Modify: `web/routes/core.py`
- Test: `tests/integration/test_multi_upload.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_multi_upload.py
import io


def _upload(client, names):
    data = {}
    files = [(io.BytesIO(b"a,b\n1,2\n3,4\n"), n) for n in names]
    data["file"] = files
    return client.post("/inspector", data=data,
                       content_type="multipart/form-data", follow_redirects=False)


def test_multi_upload_builds_list_and_activates_first(client):
    r = _upload(client, ["one.csv", "two.csv"])
    assert r.status_code == 302
    files = client.get("/files").get_json()
    assert {f["name"] for f in files["files"]} == {"one.csv", "two.csv"}
    # first (by name) is active
    assert files["active_file_id"] is not None


def test_upload_infers_type_from_extension(client):
    _upload(client, ["data.csv"])
    f = client.get("/files").get_json()["files"][0]
    assert f["type"] == ".csv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_multi_upload.py -v`
Expected: FAIL — only one file stored / no `/files` list populated.

- [ ] **Step 3: Write minimal implementation**

In `web/routes/core.py`, replace the single-file save block in `inspector()` POST with multi-file handling:

```python
    if request.method == "POST":
        from web.routes.utils import (
            save_uploaded_files, get_uploaded_files, set_active_file,
        )
        from aidrin.file_handling.file_parser import infer_file_type
        uploads = request.files.getlist("file")
        uploads = [u for u in uploads if u and u.filename]
        if uploads:
            clear_all_user_cache()
            entries = get_uploaded_files()  # append to any existing batch
            existing_ids = {e["id"] for e in entries}
            new_entries = []
            for up in uploads:
                display_name = up.filename
                stored = f"{uuid.uuid4().hex}_{secure_filename(up.filename)}"
                path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
                up.save(path)
                entry = {
                    "id": uuid.uuid4().hex,
                    "name": display_name,
                    "type": infer_file_type(display_name) or "",
                    "path": path,
                    "source": "local",
                }
                entries.append(entry)
                new_entries.append(entry)
            save_uploaded_files(entries)
            # activate the first NEW file (by name) so the user lands meaningfully
            first = sorted(new_entries, key=lambda e: e["name"].lower())[0]
            set_active_file(first["id"])
            return redirect(url_for("core.inspector"))
```

(Keep the existing GET rendering; later tasks make it land on the overview.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_multi_upload.py -v`
Expected: PASS. Also run existing inspector tests:
Run: `.venv/bin/python -m pytest tests/integration/test_inspector.py tests/integration/test_inspector_upload.py -v`
Expected: PASS (single-file upload still works — one-item list).

- [ ] **Step 5: Commit**

```bash
git add web/routes/core.py tests/integration/test_multi_upload.py
git commit -m "feat(web): accept multiple files on upload, infer types"
```

### Task 8: Globus-aware stale-session check

**Files:**
- Modify: `web/routes/core.py`
- Test: `tests/integration/test_multi_upload.py`

- [ ] **Step 1: Write the failing test**

```python
def test_globus_active_file_not_wiped_by_local_existence_check(app, client):
    from web.routes.utils import save_uploaded_files, set_active_file
    with client.session_transaction() as sess:
        sess["user_id"] = "u-g"
    with app.test_request_context("/"):
        from flask import session
        session["user_id"] = "u-g"
        save_uploaded_files([{
            "id": "g1", "name": "r.csv", "type": ".csv",
            "path": "/remote/only/r.csv", "source": "globus", "endpoint_id": "ep",
        }])
        set_active_file("g1")
    # GET inspector must NOT clear the session just because the remote path
    # doesn't exist locally.
    r = client.get("/inspector")
    assert r.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("active_file_id") == "g1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_multi_upload.py::test_globus_active_file_not_wiped_by_local_existence_check -v`
Expected: FAIL — session cleared (active_file_id gone) because `os.path.exists` is False.

- [ ] **Step 3: Write minimal implementation**

In `web/routes/core.py` `inspector()`, guard the stale-session validation so Globus files bypass the local existence check:

```python
    from web.routes.utils import get_active_file
    active = get_active_file()
    is_globus = bool(active and active.get("source") == "globus")
    if uploaded_file_path and not is_globus and (
        not os.path.exists(uploaded_file_path) or not file_type
    ):
        # ... existing stale-session clearing ...
```

(Apply the same `is_globus` bypass to the other `os.path.exists(uploaded_file_path)` guards used for rendering in this route.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_multi_upload.py tests/integration/test_inspector.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/routes/core.py
git commit -m "fix(web): don't wipe active Globus file on local existence check"
```

---

## Milestone 4 — Limits (size cap + file count)

### Task 9: `MAX_CONTENT_LENGTH`, `AIDRIN_MAX_UPLOAD_FILES`, 413 handler

**Files:**
- Modify: `web/__init__.py`, `web/routes/core.py`
- Test: `tests/integration/test_multi_upload.py`

- [ ] **Step 1: Write the failing test**

```python
def test_too_many_files_rejected(client, app):
    app.config["AIDRIN_MAX_UPLOAD_FILES"] = 2
    r = _upload(client, ["a.csv", "b.csv", "c.csv"])
    data = r.get_json() if r.is_json else None
    assert r.status_code == 400
    assert data and data["success"] is False
    assert "50" in data["message"] or "many" in data["message"].lower() or "2" in data["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_multi_upload.py::test_too_many_files_rejected -v`
Expected: FAIL — 3 files accepted (302), not rejected.

- [ ] **Step 3: Write minimal implementation**

In `web/__init__.py` `create_app()`, after `app.config.from_prefixed_env()`:

```python
    try:
        max_upload_mb = int(os.environ.get("AIDRIN_MAX_UPLOAD_MB", 1024))
    except ValueError:
        max_upload_mb = 1024
    app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024
    try:
        app.config["AIDRIN_MAX_UPLOAD_FILES"] = int(
            os.environ.get("AIDRIN_MAX_UPLOAD_FILES", 50)
        )
    except ValueError:
        app.config["AIDRIN_MAX_UPLOAD_FILES"] = 50

    @app.errorhandler(413)
    def _too_large(error):
        from flask import jsonify, request
        msg = "Upload too large for the server limit."
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"success": False, "message": msg}), 413
        return msg, 413
```

In `core.py` `inspector()` POST, after collecting `uploads` and before saving:

```python
            max_files = current_app.config.get("AIDRIN_MAX_UPLOAD_FILES", 50)
            if len(get_uploaded_files()) + len(uploads) > max_files:
                return jsonify({
                    "success": False,
                    "message": f"Too many files. The maximum is {max_files} per batch.",
                }), 400
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_multi_upload.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/__init__.py web/routes/core.py
git commit -m "feat(web): upload size cap + AIDRIN_MAX_UPLOAD_FILES=50 + 413"
```

---

## Milestone 5 — Globus unification

### Task 10: Globus selection appends to the shared list

**Files:**
- Modify: `web/routes/globus.py`
- Test: `tests/integration/test_globus.py`

- [ ] **Step 1: Write the failing test** (mock transfer; assert the selected file lands in `/files`)

```python
def test_globus_selection_appends_to_shared_list(app, client, monkeypatch):
    # The route that records a chosen Globus file should append an entry to the
    # shared uploaded_files list with source="globus" and endpoint_id.
    from web.routes.utils import get_uploaded_files
    with client.session_transaction() as sess:
        sess["user_id"] = "u-gx"
        sess["globus_authenticated"] = True
    # POST the existing "select file" route with endpoint + path + name + type
    r = client.post("/globus/select-file", json={
        "endpoint_id": "ep-9", "file_path": "/remote/x.csv",
        "file_name": "x.csv", "file_type": ".csv",
    })
    assert r.status_code in (200, 302)
    with app.test_request_context("/"):
        from flask import session
        session["user_id"] = "u-gx"
        names = [f["name"] for f in get_uploaded_files()]
    assert "x.csv" in names
```

> Note: adjust the route path/payload to match the actual Globus select endpoint in `web/routes/globus.py` (around line 198 where `globus_file_*` are set). The test asserts the **new** behavior: in addition to (or instead of) setting `globus_file_*` directly, it appends to the shared list and calls `set_active_file`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_globus.py::test_globus_selection_appends_to_shared_list -v`
Expected: FAIL — name not in the shared list.

- [ ] **Step 3: Write minimal implementation**

In `web/routes/globus.py`, where a selected Globus file currently sets
`session["globus_file_path"/name/type"]` and `globus_endpoint_id` (~line 198),
replace that with an append to the shared list + activate:

```python
    from web.routes.utils import get_uploaded_files, save_uploaded_files, set_active_file
    import uuid
    entries = get_uploaded_files()
    entry = {
        "id": uuid.uuid4().hex,
        "name": file_name, "type": file_type, "path": file_path,
        "source": "globus", "endpoint_id": endpoint_id,
    }
    entries.append(entry)
    save_uploaded_files(entries)
    set_active_file(entry["id"])   # repopulates globus_* keys via the shim
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_globus.py -v`
Expected: PASS (existing Globus tests still pass — the shim sets the same `globus_*` keys they rely on).

- [ ] **Step 5: Commit**

```bash
git add web/routes/globus.py tests/integration/test_globus.py
git commit -m "feat(web): Globus selections feed the shared file list"
```

---

## Milestone 6 — Frontend (AJAX upload, switcher, batch overview)

> These tasks touch templates/JS that aren't unit-tested in this repo. Verify each
> with the running app (`flask --app 'web:create_app()' run --debug`) and keep
> prettier clean: `npx prettier --check web/static/js web/static/css`.

### Task 11: Multi-file dropzone + remove the type `<select>`

**Files:**
- Modify: `web/templates/_components/upload_panel.html`, `web/static/js/main.js`

- [ ] **Step 1: Edit the template** — add `multiple` and drop the select.

In `web/templates/_components/upload_panel.html`: delete the `<label for="fileTypeSelector">` + `<select id="fileTypeSelector">…</select>` block, and change the file input to:

```html
<input id="file" name="file" type="file" multiple class="hidden"
       required onchange="uploadForm();" />
```

- [ ] **Step 2: Rewrite `uploadForm()` for AJAX multi-file** in `web/static/js/main.js`:

```javascript
function uploadForm() {
  const form = document.getElementById("uploadForm");
  const fileInput = document.getElementById("file");
  if (!fileInput.files || fileInput.files.length === 0) {
    if (typeof showToast === "function")
      showToast("Please select at least one file", "error");
    return;
  }
  const data = new FormData();
  for (const f of fileInput.files) data.append("file", f);
  fetch(form.action, { method: "POST", body: data })
    .then((r) => {
      if (r.redirected) {
        window.location.href = r.url;
        return null;
      }
      return r.json();
    })
    .then((body) => {
      if (body && body.success === false && typeof showToast === "function")
        showToast(body.message || "Upload failed", "error");
    })
    .catch((err) => {
      if (typeof showToast === "function")
        showToast("Upload failed: " + err.message, "error");
    });
}
```

- [ ] **Step 3: Verify in the app** — upload 2–3 files; confirm the page lands on the inspector and `/files` lists them. Check prettier.

Run: `npx prettier --check web/static/js`
Expected: "All matched files use Prettier code style!"

- [ ] **Step 4: Commit**

```bash
git add web/templates/_components/upload_panel.html web/static/js/main.js
git commit -m "feat(ui): multi-file AJAX upload; drop manual type dropdown"
```

### Task 12: File switcher component

**Files:**
- Create: `web/templates/_components/file_switcher.html`
- Modify: `web/templates/inspector.html` (include it), `web/static/js/inspector.js`

- [ ] **Step 1: Create the switcher markup** — a container the JS fills:

```html
<!-- web/templates/_components/file_switcher.html -->
<div id="file-switcher" class="px-3 py-2 border-b border-gray-200 dark:border-gray-700">
  <div class="text-xs font-semibold uppercase text-gray-500 mb-2">Files</div>
  <ul id="file-switcher-list" class="space-y-1"></ul>
</div>
```

- [ ] **Step 2: Include it** in `web/templates/inspector.html` inside the sidebar
(near the top, only when `uploaded_file_path`): `{% include '_components/file_switcher.html' %}`.

- [ ] **Step 3: Render + wire it** in `web/static/js/inspector.js` (call from `initWorkspace()`):

```javascript
function loadFileSwitcher() {
  fetch("/files")
    .then((r) => r.json())
    .then((data) => {
      const ul = document.getElementById("file-switcher-list");
      if (!ul) return;
      const files = [...data.files].sort((a, b) =>
        a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
      );
      ul.innerHTML = "";
      files.forEach((f) => {
        const li = document.createElement("li");
        const active = f.id === data.active_file_id;
        li.className =
          "flex items-center gap-2 px-2 py-1 rounded cursor-pointer text-sm " +
          (active
            ? "bg-blue-50 text-blue-700 dark:bg-blue-900/30"
            : "hover:bg-gray-100 dark:hover:bg-gray-700");
        li.innerHTML =
          `<span class="truncate flex-1">${f.name}</span>` +
          `<span class="text-xs text-gray-400">${f.type || "?"}</span>`;
        li.addEventListener("click", () => activateFile(f.id));
        ul.appendChild(li);
      });
    });
}

function activateFile(fileId) {
  fetch(`/files/${fileId}/activate`, { method: "POST" })
    .then((r) => r.json())
    .then((b) => {
      if (b.success) window.location.reload();
    });
}
```

- [ ] **Step 4: Verify in the app** — upload several files; confirm the list shows sorted, the active one highlighted, and clicking switches the active file (page reloads on the new file). Check prettier.

- [ ] **Step 5: Commit**

```bash
git add web/templates/_components/file_switcher.html web/templates/inspector.html web/static/js/inspector.js
git commit -m "feat(ui): file switcher sidebar"
```

### Task 13: Batch Overview panel (default landing) + async Globus counts

**Files:**
- Create: `web/templates/_panels/_batch_overview.html`
- Modify: `web/templates/inspector.html` (include panel + default to it), `web/static/js/inspector.js`

- [ ] **Step 1: Create the panel markup**:

```html
<!-- web/templates/_panels/_batch_overview.html -->
<div id="panel-batch-overview" class="metric-panel">
  <h2 class="text-lg font-semibold mb-3">Batch Overview</h2>
  <div id="batch-totals" class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4"></div>
  <div class="overflow-x-auto rounded-lg shadow-sm">
    <table class="w-full text-sm text-left">
      <thead class="text-xs uppercase bg-gray-50 dark:bg-gray-700">
        <tr>
          <th class="px-3 py-2">File</th><th class="px-3 py-2">Type</th>
          <th class="px-3 py-2">Source</th><th class="px-3 py-2 text-right">Records</th>
          <th class="px-3 py-2 text-right">Features</th><th class="px-3 py-2 text-right">Size</th>
          <th class="px-3 py-2">Status</th>
        </tr>
      </thead>
      <tbody id="batch-rows"></tbody>
    </table>
  </div>
</div>
```

- [ ] **Step 2: Include + default to it** in `web/templates/inspector.html`:
add `{% include '_panels/_batch_overview.html' %}` to `#panels-container`, and in
the `DOMContentLoaded` script call `showPanel('batch-overview')` (instead of a
metric panel) when `uploaded_file_path` and not `globus_mode`, then
`loadBatchOverview()` and `loadFileSwitcher()`.

- [ ] **Step 3: Render the overview** in `web/static/js/inspector.js`:

```javascript
function fmtBytes(n) {
  if (!n && n !== 0) return "—";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}

function loadBatchOverview() {
  fetch("/files/summary")
    .then((r) => r.json())
    .then((data) => {
      const t = data.totals;
      const totals = document.getElementById("batch-totals");
      if (totals)
        totals.innerHTML = [
          ["Files", t.file_count],
          ["Loaded OK", t.ok_count ?? "—"],
          ["Failed", t.error_count ?? "—"],
          ["Total records", (t.total_records ?? 0).toLocaleString()],
        ]
          .map(
            ([k, v]) =>
              `<div class="p-3 bg-gray-50 dark:bg-gray-700/50 rounded text-center">
                 <div class="text-2xl font-bold">${v}</div>
                 <div class="text-xs uppercase text-gray-500">${k}</div>
               </div>`,
          )
          .join("");

      const rows = [...data.files].sort((a, b) =>
        a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
      );
      const tbody = document.getElementById("batch-rows");
      tbody.innerHTML = "";
      rows.forEach((f) => {
        const tr = document.createElement("tr");
        tr.className = "border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer";
        const isGlobus = f.source === "globus";
        const recCell = isGlobus
          ? `<span class="globus-count" data-id="${f.id}">loading…</span>`
          : f.records ?? "—";
        const featCell = isGlobus
          ? `<span class="globus-feat" data-id="${f.id}">…</span>`
          : f.features ?? "—";
        const status =
          f.status === "ok"
            ? "✅"
            : f.status === "remote"
              ? "🌐 remote"
              : `⚠️ ${f.error || "error"}`;
        tr.innerHTML =
          `<td class="px-3 py-2">${f.name}</td><td class="px-3 py-2">${f.type || "?"}</td>` +
          `<td class="px-3 py-2">${f.source}</td>` +
          `<td class="px-3 py-2 text-right">${recCell}</td>` +
          `<td class="px-3 py-2 text-right">${featCell}</td>` +
          `<td class="px-3 py-2 text-right">${fmtBytes(f.size_bytes)}</td>` +
          `<td class="px-3 py-2">${status}</td>`;
        tr.addEventListener("click", () => activateFile(f.id));
        tbody.appendChild(tr);
        if (isGlobus) fetchGlobusCount(f);
      });
    });
}

// Reuse the existing remote summary to fill a Globus row's counts.
function fetchGlobusCount(f) {
  fetchGlobusSummaryFor(f.id, f).then((summary) => {
    if (!summary) return;
    const rec = document.querySelector(`.globus-count[data-id="${f.id}"]`);
    const feat = document.querySelector(`.globus-feat[data-id="${f.id}"]`);
    if (rec) rec.textContent = (summary.records_count ?? "—").toLocaleString();
    if (feat) feat.textContent = summary.features_count ?? "—";
  });
}
```

> `fetchGlobusSummaryFor(id, entry)` wraps the existing remote-summary call
> (the same Globus Compute submit/poll used by `fetchGlobusSummary()`),
> activating the entry's endpoint/path and returning the cached/awaited
> `{records_count, features_count}`. Factor it from the current
> `fetchGlobusSummary()` so both share the cache (`globus_summary:...`).

- [ ] **Step 4: Verify in the app** — upload a mixed batch; confirm the overview is the landing view, totals + table render sorted by name, failed files show inline errors, and (with Globus configured) remote rows fill in their counts. Check prettier.

- [ ] **Step 5: Commit**

```bash
git add web/templates/_panels/_batch_overview.html web/templates/inspector.html web/static/js/inspector.js
git commit -m "feat(ui): batch overview landing view with async Globus counts"
```

---

## Final Verification

- [ ] Run the whole suite: `.venv/bin/python -m pytest tests/ -q` — all pass.
- [ ] Prettier: `npx prettier --check web/static/js web/static/css` — clean.
- [ ] Manual smoke: upload 1 file (single-file UX unchanged); upload 5 files (overview + switcher); remove the active file (next activates); a corrupt file shows an inline error; (if Globus configured) a remote file streams its counts.

## Self-Review notes (for the implementer)

- The `parquet-support` `load_dataframe` friendly-error mapping is **not** required here: `summarize_files` handles `read_file`'s tri-state itself, and the active-file detail routes are unchanged on this branch. If `parquet-support` merges first, no conflict — both only add helpers.
- `infer_file_type` returns a READER_MAP key; when a real extension suffix is ever needed (e.g. `custom.py:137`), use `file_extension(name)` instead. Out of scope here but noted.
