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

**Note on dependencies (two separate branches):**
- The per-file error handling mirrors the `load_dataframe` helper + friendly-error
  mapping on the **`parquet-support`** branch (`web/routes/utils.py`). It is a
  non-trivial helper; if this feature lands first, replicate it here.
- `MAX_CONTENT_LENGTH` (the request-size cap this spec relies on) is on the
  **`upload-size-limit`** branch (`web/__init__.py`), *not* `parquet-support`. It
  is absent on `develop`/this branch today.

These are independent branches; neither is on `develop` yet, so this design must
not assume either exists until merged.

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
        "records": int|None, "features": int|None,  # from a single read; NO metrics
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

- Reads each file via `read_file`, which returns **`DataFrame | None | str`**.
  `summarize_files` must branch on all three: a `DataFrame` → `status:"ok"`;
  `None` (unsupported/missing name) or a `str` (read error message) →
  `status:"error"` with that message. (This is the same tri-state the
  `load_dataframe` helper handles — see dependency note.)
- **Phase 1 computes NO metrics** — only structural facts available from a single
  read: `records` (`len(df)`), `features` (`len(df.columns)`), `size_bytes`
  (`os.path.getsize`, no parse), and load `status`. Completeness/duplicates/etc.
  are deliberately excluded here; they remain in the per-file Data Quality view.
  (Keeping metrics out also avoids the row-wise-vs-cell-wise completeness
  question entirely for now.)
- A file that fails to load becomes a `status: "error"` row with a short
  message — **one bad file never aborts the batch**.
- **Synchronous cost:** summarizing up to 50 files (combined up to the request
  cap) can be slow. Phase 1 reads each file once; if this proves too heavy,
  apply a per-file row/size cap for the summary pass (note, not yet enforced).
- Lives in the core package (e.g. `aidrin/batch.py`), re-exported from
  `aidrin/__init__.py`. Consumed by the web combined-summary endpoint, the CLI's
  batch mode, and library users.

### Layer 2 — Web active-file state (Approach A shim)

A presentation-only construct in the Flask session:

- `uploaded_files`: list of
  `{"id": uuid, "name": str, "type": str, "path": str, "source": "local"|"globus"}`.
  Globus entries additionally carry `endpoint_id` (and the remote path lives in
  `path`). The previously top-level `globus_file_*` keys are **folded into the
  entry**, not kept separately. **Stored server-side** (keyed by `user_id`), not
  in the cookie — see Limits (session storage).
- `session["active_file_id"]`: the currently selected file's id (small pointer,
  kept in the cookie).
- A `set_active_file(file_id)` helper sets `active_file_id` **and writes the
  active file's path/name/type into the existing `uploaded_file_*` session
  keys**. For a **Globus** entry it must ALSO repopulate the exact legacy keys
  that downstream code still reads — `globus_file_path`, `globus_file_name`,
  `globus_file_type`, and `globus_endpoint_id` — because `core.py:118-122,179-182,288`,
  `utils.py:119`, `llm.py:218`, `routes/globus.py:131-143`, and the
  `globus_summary:{endpoint_id}:{file_path}` cache key all depend on them. So
  "folding `globus_file_*` into the list entry" means they are no longer the
  *source of truth* (the list is) — but the shim re-derives them for the active
  file so existing consumers keep working.

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
4. **Combined summary:** after a multi-file upload the inspector **lands on the
   combined summary** (the batch overview), not a single file's panels.
   `GET /files/summary`: **local** files go through `aidrin.summarize_files`
   (one read → records, features, size, status — no metrics); the web route
   decorates each row with `source`. **Globus** files appear immediately with
   metadata (name, type, size, source); their records/features are fetched
   **asynchronously** via the existing remote `_summary_statistics` (which already
   returns `records_count`/`features_count`, `web/globus.py:144-145`) and stream
   into the row when ready — reusing the `globus_summary:{endpoint_id}:{file_path}`
   cache so already-viewed files are instant. Clicking any row activates that file
   and drills into its per-file panels.
5. **Metrics:** unchanged — they read the active file through the legacy keys
   (local) or the restored Globus context (remote).

## New / Changed Endpoints

| Endpoint | Change |
| --- | --- |
| `POST /inspector` | Accept multiple files; build the list; infer types. |
| `GET /files` | List `uploaded_files` (+ which is active) for the switcher. |
| `POST /files/<id>/activate` | Set the active file. |
| `POST /files/<id>/remove` | Remove a file (delete local file from disk + list). **If the removed file was active**, activate the next remaining file (or, if none remain, clear `uploaded_file_*` so the inspector returns to the upload panel). Always re-run `set_active_file`. |
| `GET /files/summary` | Combined per-file overview + totals (local synchronous; Globus records/features fetched async via existing remote summary). |
| Globus selection route | Append into the shared list (`source:"globus"`, `endpoint_id`); fold in `globus_file_*`. |
| All metric / summary / feature routes | **Unchanged**; execution dispatched by source (local routes vs `remote_metric_runner`). |

## Type Inference

New `infer_file_type(filename)` in `aidrin/file_handling/file_parser.py`:

- Maps real extensions to reader keys via an explicit `EXTENSION_MAP`, resolving
  the Excel quirk (`READER_MAP` currently uses the combined key
  `".xls, .xlsb, .xlsx, .xlsm"`; the map points `.xls/.xlsb/.xlsx/.xlsm` at it).
- Unknown extension → `None` → the file is listed with `status: "error"`
  ("Unsupported file type") and cannot be made active.
- **Caveat:** the inferred value is a READER_MAP *key*, which for Excel is the
  combined string `".xls, .xlsb, .xlsx, .xlsm"` — and `uploaded_file_type` is
  reused as a literal filename suffix in `custom.py:137`
  (`remedied_{session_id}{file_type}`). That is already broken for Excel today;
  this design must not make it worse — store a real extension alongside the
  reader key (e.g. derive the suffix from the original filename, not the key).

## Frontend (inspector)

- **Upload dropzone:** add `multiple`; support multi-file drag-drop. **Remove**
  the "File type" `<select>` (type is inferred). Note this is **not** a one-line
  change: today the upload is a native full-page form POST → redirect
  (`main.js:45` `form.submit()`, `core.py:58`). Multi-file upload with per-file
  status/error rows implies an **AJAX upload** (`fetch` + `FormData`) and a
  client-rendered file list — a real rewrite of `uploadForm()`. Removing the
  `<select>` also drops its `accept`-attribute filtering and the existing
  client-side "select a file type" validation guard (`main.js:31`); replace with
  extension-based client validation.
- **File switcher:** a list (in the sidebar) of uploaded files, each showing
  name + type/status badge, the active one highlighted; click to activate;
  per-file remove button.
- **Combined summary ("Batch Overview"):** the **default landing view** after a
  multi-file upload. Two parts:
  - **Totals strip** (cards): `# files`, `# loaded OK` / `# failed`,
    `total records`, files-by-type, files-by-source, total size.
  - **Per-file table**: columns **File · Type · Source · Records · Features ·
    Size · Status** (no metrics column in phase 1), **sorted by file name**
    (case-insensitive). Failed rows show the friendly error inline (`—` for
    stats). Clicking a row activates that file → its per-file panels.
  - **Local vs Globus rows:** local rows render fully on first paint (synchronous
    read). Globus rows render with metadata immediately and a "loading…"
    records/features cell that **fills in asynchronously** from the remote
    `_summary_statistics` (cached per file). `total records` updates as remote
    counts arrive.
  - **Table + totals only** — no charts in phase 1.
- **Globus panel:** allow selecting multiple remote files; each selected file is
  appended to the shared list as a `source:"globus"` entry. Activating one keeps
  the inspector in `globus_mode` (remote execution).

## Caching

- Per-file metric caching already works because the cache key includes the file.
- **Change:** key the cache on the **unique stored filename / file_id** instead
  of the display `file_name`, to prevent collisions when two files in a batch
  share a display name. This must move **all four** file-name-derived sites
  together or cached results become unretrievable: `generate_metric_cache_key`,
  the `store_result` user-key (`user:{id}:file:{name}:{metric}`), the
  `cached_result` lookup (`core.py:286-294`), and the `clear_all_user_cache`
  prefix match. (Telemetry `trace_metric(file_name=...)` may keep the display
  name — cosmetic only.)

## Limits

- `MAX_CONTENT_LENGTH` (from the `upload-size-limit` branch; default 1 GB) caps
  the **whole** multipart request, bounding the combined batch size.
- New `AIDRIN_MAX_UPLOAD_FILES` (default **50**) bounds the number of files per
  batch.
- **Enforcement ordering:** `MAX_CONTENT_LENGTH` is enforced by Flask **before**
  the body is parsed (returns a bare 413); `AIDRIN_MAX_UPLOAD_FILES` can only be
  checked **after** parsing `getlist("file")`. Add a friendly 413 handler and a
  clear "too many files" message so the two limits don't produce confusing UX.
- **Session storage (important):** Flask's default session is a client-side
  signed cookie (~4 KB). A 50-entry `uploaded_files` list — especially with long
  remote Globus paths — can exceed that and **silently drop the session**.
  Therefore store `uploaded_files` **server-side** (e.g. in `TEMP_RESULTS_CACHE`
  keyed by `user_id`), keeping only small pointers (`active_file_id`, the legacy
  `uploaded_file_*`/`globus_file_*` shim values) in the cookie.

## Error Handling

- **Per-file load failure:** surfaced as a `status: "error"` row in the summary
  with a short message; the batch continues. The active-file detail view shows
  the friendly read error (existing `load_dataframe` behavior).
- **Too many files / unsupported type:** clear, user-facing messages.
- **Active Globus file vs. local existence check:** the inspector's stale-session
  validation (`core.py:65-78`) and several routes guard on
  `os.path.exists(uploaded_file_path)`. A Globus active file's path is **remote**,
  so this is `False` on the AIDRIN server and would wrongly **wipe the session**.
  Add a `source == "globus"` bypass to every such existence check (treat remote
  files as present; let the Globus path handle reachability).
- **Empty batch / no active file:** the inspector falls back to the upload panel
  (existing stale-session handling generalizes to "no files").

## Testing

- **Core:** `summarize_files` — records/features/size/status + totals, mixed
  types, a failing file among good ones, empty input, and `read_file` returning
  each of `DataFrame`/`None`/`str`. Assert **no metric** fields are present
  (records = `len(df)`, features = `len(df.columns)` only). `infer_file_type` —
  each supported extension, Excel variants, unknown extension.
- **Web (integration):** multi-file upload builds the list and sets an active
  file; `activate` updates the legacy keys and an existing metric still works;
  `/files/summary` shape + totals; `remove` deletes file + entry; **removing the
  active file** activates the next (or returns to the upload panel); per-file
  error appears in the summary without 500s; `AIDRIN_MAX_UPLOAD_FILES` enforced
  (and ordering vs. the 413 size cap); cached metric results survive the file_id
  re-key (store then retrieve).
- **Globus:** multi-file selection appends to the shared list (mocked); a Globus
  active file is **not** wiped by the local `os.path.exists` stale check, and the
  shim repopulates `globus_file_*`/`globus_endpoint_id`; the batch overview
  fills a Globus row's records/features from the remote `_summary_statistics`
  result (mocked) and serves a second request from the `globus_summary` cache.
- **Session storage:** a 50-file list with long remote paths persists (does not
  overflow the cookie) — verifies the server-side storage decision.
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
