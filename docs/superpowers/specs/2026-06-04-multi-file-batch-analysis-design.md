# Multi-File Batch Analysis — Design

**Date:** 2026-06-04
**Branch:** `multi-file-analysis` (off `develop`)
**Status:** Approved design — pending implementation plan

## Summary

Let users analyze **multiple files at once** (a batch of independent datasets,
with possibly different schemas) instead of a single file. Phase 1 treats each
file independently: users analyze one **active file** at a time using the
existing inspector, and can view a **combined cross-file summary**. A later
**phase 2** will add relational/different-schema handling (joins across files);
this design deliberately leaves the seams for it but does not implement it.

## Goals (Phase 1)

- Upload / select **many files** via local multi-select + drag-drop, and via
  the existing **Globus** remote integration.
- Per-file format is **inferred from the file extension** (mixed types allowed);
  the manual "File type" dropdown is removed.
- An **active-file switcher**: one file is active at a time and the entire
  current inspector (summary, metrics, visualizations) operates on it.
- A **combined summary**: a per-file overview table plus aggregate totals.
- Local uploads and Globus transfers feed **one** source-agnostic file list.
- The batch/aggregation logic is a **session-free core primitive** reused by the
  web UI, the library, and the CLI.

## Non-Goals (Phase 1 — YAGNI)

- Directory upload (`webkitdirectory`) and zip-archive upload.
- Same-schema column-level comparison across files.
- Simultaneous side-by-side metric rendering for multiple files.
- Relational joins / multi-table modeling (**phase 2**).

## Background / Current State

The single-file assumption is deep in the web layer:

- The Flask session holds `uploaded_file_path` / `uploaded_file_name` /
  `uploaded_file_type` (a single file). These keys are referenced ~74 times
  across `web/routes/{core,metrics,custom,llm}.py`, `web/routes/utils.py`, and
  the inspector templates.
- `read_file((path, name, type))` returns one DataFrame; there are ~10
  `read_file` / `load_dataframe` call sites.
- The metric result cache key is built from a single `file_name`
  (`generate_metric_cache_key`).
- **Globus is remote *compute*, not just a remote file source.** `web/globus.py`
  serialises `remote_metric_runner` and ships it to a Globus Compute **endpoint**,
  where `aidrin` runs the metric next to the data. A Globus file's
  `globus_file_path` is a path **on the remote endpoint**, not on the AIDRIN
  server. It has its own session keys (`globus_file_path/name/type`,
  `globus_endpoint_id`), its own execution path, and its own frontend mode
  (`globus_mode` / `AIDRIN_GLOBUS_*` / `fetchGlobusSummary`). This execution path
  must remain — local metric routes cannot run on a remote path.
- The library API (`aidrin.calculate_*(file_info)`) is **session-free** and
  already supports multiple files by iteration. The CLI/headless mode (on other
  branches) is likewise config/arg driven and session-free.

**Note on dependencies:** the per-file error handling described here mirrors the
`load_dataframe` helper and friendly-error mapping introduced on the
`parquet-support` branch. If this feature lands before that work is merged, it
should include an equivalent helper; otherwise it reuses it.

## Architecture: Two Layers

The central decision is to split the feature into a presentation-agnostic core
and a web-only state layer.

### Layer 1 — Core batch primitive (session-free)

A new `aidrin` function operates purely on a list of `file_info` tuples:

```python
def summarize_files(file_infos):
    """Return {"files": [per_file, ...], "totals": {...}}.

    per_file = {
        "name": str, "type": str,
        "records": int|None, "features": int|None,
        "completeness": float|None,   # fraction of non-null cells, 0..1
        "size_bytes": int|None,
        "status": "ok"|"error",
        "error": str|None,            # short message when status == "error"
    }
    totals = {
        "file_count": int,
        "ok_count": int, "error_count": int,
        "total_records": int,
        "by_type": {type: count, ...},
    }
    """
```

- Reads each file via `read_file`; computes lightweight stats **without Celery**
  (e.g. completeness = `df.notna().to_numpy().mean()`), so it is cheap and safe
  to call synchronously.
- A file that fails to load becomes a `status: "error"` row with a short
  message — **one bad file never aborts the batch**.
- Lives in the core package (e.g. `aidrin/batch.py`), re-exported from
  `aidrin/__init__.py`. Consumed by the web combined-summary endpoint, the CLI's
  batch mode, and library users.

### Layer 2 — Web active-file state (Approach A shim)

A presentation-only construct in the Flask session:

- `session["uploaded_files"]`: list of
  `{"id": uuid, "name": str, "type": str, "path": str, "source": "local"|"globus"}`.
  Globus entries additionally carry `endpoint_id` (and the remote path lives in
  `path`). The previously top-level `globus_file_*` keys are **folded into the
  entry**, not kept separately.
- `session["active_file_id"]`: the currently selected file's id.
- A `set_active_file(file_id)` helper sets `active_file_id` **and writes the
  active file's path/name/type into the existing `uploaded_file_*` session
  keys**. For a Globus entry it also restores the Globus execution context
  (endpoint id + remote path) the frontend's `globus_mode` needs.

This compatibility shim means every existing **local** metric route, the ~10
read sites, and the templates keep working **unchanged** — they always operate on
the active file. Execution stays **dispatched by source**: a local active file
runs through the local routes; a Globus active file runs through the existing
`remote_metric_runner` path. Only the upload/Globus entry points and a few new
file-management endpoints need to be multi-file aware.

## Data Flow

1. **Upload (local):** `POST /inspector` reads `request.files.getlist("file")`.
   For each file: enforce count/size limits → save with a unique stored name →
   `infer_file_type(filename)` → append `{id, name, type, path, source:"local"}`
   to `uploaded_files`. Set the first newly-added file active (via the shim).
2. **Globus:** the Globus selection flow appends entries with `source:"globus"`
   (carrying `endpoint_id` + remote `path`) to the **same** `uploaded_files`
   list. The `globus_file_*` keys are folded into the entry. The **remote
   execution path is unchanged** — activating a Globus file still dispatches
   through `remote_metric_runner` (`globus_mode`), not the local routes.
3. **Switch active file:** `POST /files/<id>/activate` → `set_active_file(id)` →
   the frontend re-renders the inspector for the new active file, in local or
   Globus mode depending on the entry's `source`.
4. **Combined summary:** `GET /files/summary`. **Local** files are summarized
   directly via `aidrin.summarize_files`. **Globus** files are listed with
   metadata only (name, type, size, source; stats shown as `n/a`) in phase 1 —
   computing remote stats would require a per-file Globus Compute call, deferred
   to a later phase.
5. **Metrics:** unchanged — they read the active file through the legacy keys
   (local) or the restored Globus context (remote).

## New / Changed Endpoints

| Endpoint | Change |
| --- | --- |
| `POST /inspector` | Accept multiple files; build the list; infer types. |
| `GET /files` | List `uploaded_files` (+ which is active) for the switcher. |
| `POST /files/<id>/activate` | Set the active file. |
| `POST /files/<id>/remove` | Remove a file (delete from disk + list). |
| `GET /files/summary` | Combined per-file overview + totals (Globus = metadata only). |
| Globus selection route | Append into the shared list (`source:"globus"`, `endpoint_id`); fold in `globus_file_*`. |
| All metric / summary / feature routes | **Unchanged**; execution dispatched by source (local routes vs `remote_metric_runner`). |

## Type Inference

New `infer_file_type(filename)` in `aidrin/file_handling/file_parser.py`:

- Maps real extensions to reader keys via an explicit `EXTENSION_MAP`, resolving
  the Excel quirk (`READER_MAP` currently uses the combined key
  `".xls, .xlsb, .xlsx, .xlsm"`; the map points `.xls/.xlsb/.xlsx/.xlsm` at it).
- Unknown extension → `None` → the file is listed with `status: "error"`
  ("Unsupported file type") and cannot be made active.

## Frontend (inspector)

- **Upload dropzone:** add `multiple`; support multi-file drag-drop. **Remove**
  the "File type" `<select>` (type is inferred).
- **File switcher:** a list (in the sidebar) of uploaded files, each showing
  name + type/status badge, the active one highlighted; click to activate;
  per-file remove button.
- **Combined summary panel:** a new view rendering the per-file overview table
  (name, type, #records, #features, completeness, size, status) and the totals;
  clicking a row activates that file. Errors render inline per row. Globus rows
  show metadata only with stats as `n/a` (phase 1).
- **Globus panel:** allow selecting multiple remote files; each selected file is
  appended to the shared list as a `source:"globus"` entry. Activating one keeps
  the inspector in `globus_mode` (remote execution).

## Caching

- Per-file metric caching already works because the cache key includes the file.
- **Change:** key the cache on the **unique stored filename / file_id** instead
  of the display `file_name`, to prevent collisions when two files in a batch
  share a display name. Update `generate_metric_cache_key` and the `store_result`
  user-key accordingly.

## Limits

- `MAX_CONTENT_LENGTH` already caps the **whole** multipart request (the
  parquet/upload-limit work sets this; default 1 GB) — this naturally bounds the
  combined batch size. No per-file cap needed.
- New `AIDRIN_MAX_UPLOAD_FILES` (default **50**) bounds the number of files per
  batch; exceeding it returns a clear error and rejects the upload.

## Error Handling

- **Per-file load failure:** surfaced as a `status: "error"` row in the summary
  with a short message; the batch continues. The active-file detail view shows
  the friendly read error (existing `load_dataframe` behavior).
- **Too many files / unsupported type:** clear, user-facing messages.
- **Empty batch / no active file:** the inspector falls back to the upload panel
  (existing stale-session handling generalizes to "no files").

## Testing

- **Core:** `summarize_files` — per-file stats, totals, mixed types, a failing
  file among good ones, empty input. `infer_file_type` — each supported
  extension, Excel variants, unknown extension.
- **Web (integration):** multi-file upload builds the list and sets an active
  file; `activate` updates the legacy keys and an existing metric still works;
  `/files/summary` shape + totals; `remove` deletes file + entry; per-file error
  appears in the summary without 500s; `AIDRIN_MAX_UPLOAD_FILES` enforced.
- **Globus:** multi-file transfer appends to the shared list (mocked transfer).
- Follow TDD (red → green) per the existing reader/route test patterns.

## Phase 2 Seam (relational / different schemas)

The `uploaded_files` list and the `summarize_files` primitive are the extension
points. Phase 2 can add: schema fingerprinting, grouping files by schema,
defining join keys across files, and cross-file/relational metrics — built on
the same file list and core batch layer, without re-architecting phase 1.

## Rollout / Compatibility

- Single-file behavior is preserved: uploading one file yields a one-item list,
  that file is active, and the experience is identical to today.
- The shim keeps all existing routes/tests valid; changes concentrate in the
  upload entry points, the new file-management endpoints, the Globus unification,
  and the frontend switcher/summary.
