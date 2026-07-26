# File Reference Validation: Implementation Plan

## Milestone checklist

- [x] Milestone 0: Create the feature branch and finalize this decision-complete checklist.
- [x] Milestone 1: Implement the core metric, filesystem security semantics, metadata, and format-focused unit tests.
- [x] Milestone 2: Integrate the headless API, CLI, and batch configuration with focused tests.
- [x] Milestone 3: Integrate generic and dedicated MCP tools plus the bundled AIDRIN skill documentation and tests.
- [ ] Milestone 4: Integrate the local web Data Quality panel, allowed-root configuration, rendering, and integration tests.
- [ ] Milestone 5: Complete user documentation, refresh the code index, and pass the full test, lint, formatting, docs, and wheel-build gates.

Each milestone is committed separately. Existing unrelated `.gitignore` and `temp/` contents are excluded from feature commits.

## Summary and scope

Add one opt-in Data Quality metric, `file_reference_validation`, for explicitly selected path-bearing columns or string-valued HDF5 datasets. It verifies regular files on the execution host and returns complete validity summaries, invalid locations, file size, owner, creation time when available, and modification time.

Support the library/headless API, CLI, batch, local web, generic MCP, and a dedicated MCP tool. Do not add the metric to the fast `data-quality` bundle. Globus support is out of scope and its web control remains disabled.

Do not modify existing file readers, `read_file()`, `aidrin/__init__.py`, worker code, database state, or unrelated frontend panels.

The implementation follows the conventional plain `calculate_*` function plus `@shared_task` wrapper. Web calls the plain function synchronously, and headless runners invoke the task's `__wrapped__` function. The worker registers the task only because `web/routes/metrics.py` imports the module while `create_app()` registers the blueprint; there is no task autodiscovery.

## Core metric

Create `aidrin/structured_data_metrics/file_reference_validation.py` with:

```python
calculate_file_reference_validation(
    file_info,
    path_targets,
    base_dir=None,
    max_results=100,
    scan_limit=None,
    allowed_roots=None,
)
```

and a conventional `@shared_task` wrapper.

### Inputs and scanning

- `file_info` is `(file_path, file_name, file_type[, selected_keys])`.
- Default `base_dir` is the canonical parent directory of `file_info[0]`.
- Require exact `path_targets`; normalize and deduplicate them while preserving order.
- Discover targets through `iter_targets()` and scan with `iter_value_blocks()`, `iter_indexed_values()`, and supplied missing masks.
- Accept pandas object/string/category targets and HDF5 byte/unicode/string datasets. Numeric and boolean targets produce target-scoped errors.
- Decode bytes as UTF-8. Undecodable bytes and non-string occurrences are `unsupported_value`.
- Preserve original values but trim surrounding whitespace before resolution. Empty normalized values are missing.
- Expand `~`; do not expand environment variables, globs, or URI schemes.
- Validate `max_results` and `scan_limit` as non-negative integers. `max_results=0` and `scan_limit` of `None` or `0` mean unlimited.
- `scan_limit` applies globally to occurrences in selected-target order, including missing and unsupported values.

CLI, batch, and MCP scan all values by default. Web uses an administrator-controlled hard cap: prefer `current_app.config["FILE_REFERENCE_WEB_SCAN_LIMIT"]`, otherwise read `AIDRIN_FILE_REFERENCE_WEB_SCAN_LIMIT`, and default to `10000`. Require a positive integer; invalid values log a warning and fall back to `10000`. Web users cannot override this cap and are directed to CLI or MCP for complete larger scans.

### Resolution, security, and caching

For each unique normalized reference alias:

1. Resolve relative values under `base_dir` and canonicalize using host-native real-path and case normalization.
2. If roots are enforced, reject paths outside them before explicit target `lstat()` or `stat()` calls.
3. Call `lstat()` once per unique alias to identify symlinks.
4. Call `stat()` once per unique alias target to verify the resolved object and collect metadata.
5. Do not use separate `exists()` or `is_file()` calls.
6. Follow symlinks. Symlinks to regular files are valid; symlinks to directories are `not_a_file`; missing or looping targets are `broken_symlink`.
7. Count only regular files as valid.

Use an alias cache keyed by normalized absolute reference path and a target cache keyed by canonical resolved path. Different aliases or symlinks may share one metadata record. Root containment uses normalized real paths and `os.path.commonpath()`; mixed Windows drives or comparison failures are outside the roots.

Stable invalid reasons are `not_found`, `not_a_file`, `permission_denied`, `broken_symlink`, `outside_allowed_root`, `invalid_path`, and `unsupported_value`. Owner lookup or unavailable creation time never invalidates a file.

### Output contract

```json
{
  "Description": "Validates dataset values as references to regular files on the execution host.",
  "Summary": {
    "candidate_values": 0,
    "scanned_values": 0,
    "unscanned_values": 0,
    "scan_limit": null,
    "scan_complete": true,
    "valid_references": 0,
    "invalid_references": 0,
    "missing_references": 0,
    "unique_reference_values": 0,
    "unique_resolved_paths": 0,
    "unique_valid_files": 0,
    "validity_rate": 0.0,
    "all_references_valid": false,
    "invalid_details_truncated": false,
    "metadata_details_truncated": false
  },
  "Target summaries": {},
  "Invalid references": [],
  "File metadata": [],
  "Errors": []
}
```

- Derive `candidate_values` from selected target shapes before scanning.
- `unscanned_values = candidate_values - scanned_values`.
- `scan_complete` is false whenever the scan limit prevents processing all candidates.
- `validity_rate = valid_references / scanned_values`, or `0.0` when nothing was scanned.
- `all_references_valid` requires a complete scan, at least one scanned value, no invalid or missing references, and no target errors.
- Target summaries repeat candidate, scanned, unscanned, completion, valid, invalid, missing, and validity-rate fields.
- Invalid details are occurrence-level and retain row/source-line or HDF5 path/index locations.
- Metadata is one record per canonical valid file with `resolved_path`, `occurrences`, `size_bytes`, nullable `owner_name`, nullable `created_at`, `created_at_source`, `modified_at`, and `referenced_via_symlink`.
- Timestamps are UTC ISO 8601 with `Z`. Creation source is `birthtime`, `windows_ctime`, or `unavailable`; Unix `st_ctime` is never reported as creation time.
- Detail arrays preserve encounter order and are independently capped by `max_results`.

## Exact integration hooks

### Headless, CLI, and batch

- Add the task import and runner in `aidrin/headless/runners.py`.
- Add the Data Quality registry entry and explicit `run_metric()` dispatch/validation in `aidrin/headless/api.py`.
- In `aidrin/headless/cli.py`, add a positional `path-targets` branch to `_add_required_metric_args()`, add metric-specific `--base-dir`, `--max-results`, and `--scan-limit` flags in the subparser loop, and forward all four values from `_build_run_kwargs()`.
- In `aidrin/headless/config.py`, add `path_targets`, `base_dir`, `max_results`, and `scan_limit`; add dashed aliases; normalize `path_targets` as a list.
- Add all four fields to the explicit payload built by `run_batch_metrics()`.

CLI syntax:

```text
aidrin run file-reference-validation MANIFEST "path_column,image_path" \
  --base-dir /data/project --max-results 100
```

### MCP

- Extend `run_aidrin_metric` with `path_targets`, `base_dir`, `max_results`, and `scan_limit`, including its explicit kwargs list.
- Add `verify_file_references(file_path, path_targets, file_type=None, base_dir=None, max_results=100, scan_limit=None)` delegating to `run_metric()`.
- Ensure generic and dedicated tools return equivalent JSON and document that resolution occurs on the MCP server host.
- Add the intent and tool to `.claude/skills/aidrin/SKILL.md` and a new metric section to its `reference/metrics.md`; do not add it to the normal readiness baseline.

### Web route and UI

- Import `calculate_file_reference_validation` at module level in `web/routes/metrics.py`; this import also registers the shared task during worker app initialization.
- Add `file_reference_validation` to the hardcoded Data Quality selected tuple and add a metric-scoped POST handler.
- Read `file_reference_targets`, `file_reference_root_id`, `file_reference_base_subdirectory`, and `file_reference_max_results`.
- Prefer `current_app.config["FILE_REFERENCE_ALLOWED_ROOTS"]`, otherwise parse `AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS` as a JSON array. Accept only absolute existing directories, canonicalize and deduplicate them, ignore invalid entries with warnings, and disable the feature when none remain.
- Recompute roots and root IDs server-side. Build `base_dir` only from the chosen root plus a relative subdirectory; reject absolute subdirectories, traversal, nonexistent directories, and canonical escape. Absolute manifest references may resolve beneath any configured root.
- Pass all configured roots as `allowed_roots` and the administrator web cap as `scan_limit`.
- Extend `/custom-outlier-targets` additively with `file_reference.enabled`, root `{id, label}` choices, and `scan_limit`. File-reference configuration errors must not break custom-outlier target discovery.
- Add a disabled-by-default panel control with exact target selection, root selection, relative base subdirectory, and `max_results`.
- Add a separate `loadFileReferenceOptions()` call from local `initWorkspace()`. Do not refactor or change the existing lazy `loadCustomOutlierTargets()` flow.
- Show object/string/category and HDF5 string targets. Order names containing `path`, `file`, `filename`, `filepath`, or `location` first and label them "Suggested" without preselecting them.
- Auto-select one root; require a choice for multiple roots. Explain server-host execution and the web cap.
- Render escaped, accessible invalid-reference and metadata tables and a prominent partial-scan warning. Keep the existing JSON download.
- Local `initWorkspace()` is not called in Globus mode; leave the control disabled there with a concise explanation.

## Tests and acceptance criteria

Add `tests/unit/test_file_reference_validation.py` and extend existing CLI, MCP, and inspector metric tests.

- Cover absolute, relative, `~`, whitespace, null bytes, missing values, unsupported scalars, undecodable bytes, directories, and missing files.
- Cover repeated aliases and direct/symlink references to one canonical file, including `lstat()`/`stat()` caching and occurrence counts.
- Cover permissions, broken/looping symlinks, direct and symlink root escape, and rejection before explicit target stat calls.
- Cover complete/partial scan invariants, limits reached within and between targets, unlimited semantics, detail truncation, and deterministic ordering.
- Mock Windows drive separation, case normalization, `windows_ctime`, macOS birth time, Linux unavailable creation time, and owner failure.
- Cover CSV, Excel, Parquet, supported JSON, NPZ, and string HDF5 without modifying readers.
- Cover registry and `run_metric()` validation, CLI parsing/forwarding, batch aliases/payload, and generic/dedicated MCP parity.
- Cover web selected-tuple dispatch, root configuration, tampered IDs, traversal, root escape, scan cap, partial-scan rendering, metric-scoped errors, and successful metadata.
- Confirm existing custom-outlier lazy loading and endpoint behavior remain compatible and Globus remains disabled.

Update CLI, web, Sphinx MCP, bundled skill, and metric-reference documentation. Verify documented commands against the implementation, then run full pytest, flake8, Prettier for touched frontend assets, Sphinx build, and wheel build.

No additional files should change unless a required gate proves one necessary.
