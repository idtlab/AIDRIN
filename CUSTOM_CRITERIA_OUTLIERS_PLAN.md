# Custom Criteria Outliers With Value Iterators

## Summary

Add **Check outliers with custom criteria** to Data Quality using a shared target/value-iterator layer. The metric will support tabular DataFrame columns and native HDF5 dataset paths. Local examples in `temp/` are useful for manual validation, but automated tests must generate their own CSV/HDF5 fixtures because `temp/` is not committed.

Implement this as an additive, minimal-impact feature. Existing Data Quality metrics, existing result schemas, current `/feature-set` behavior, and `hdf5Reader.read()` must remain unchanged.

## Implementation Checklist

- [x] Milestone 1: Add target/value iterators and `aidrin.calculate_custom_outliers` core API.
- [x] Milestone 1 tests: Cover CSV/HDF5 targets, range/regex rules, missing/fill handling, validation, and preview caps.
- [x] Milestone 2: Add local Flask route integration, target discovery, UI rule editor, and renderer escaping.
- [x] Milestone 2 tests: Cover local `/data-quality` custom rules, target discovery, renderer escaping, and existing metric regressions.
- [x] Milestone 3: Add Globus target discovery/submission/remote dispatch behavior.
- [x] Milestone 3 tests: Cover Globus custom-criteria params and remote bundled results.
- [x] Final validation: Run the full available test suite.
- [ ] Delivery: Commit each milestone, push a branch, open PR over `develop`, monitor CI, and fix root causes until checks pass.

## Key Interfaces

Add an internal iterator module, for example `aidrin/file_handling/value_iterators.py`, with:

- `iter_targets(file_info)`: returns selectable targets shaped as `{name, target_type, dtype, shape, display_label}`.
- `iter_value_blocks(file_info, target)`: yields per-target arrays or chunks shaped as `{target, target_type, values, offset, locate}` where `values` is a pandas Series or NumPy array, `offset` is optional block-origin metadata, and `locate(index_tuple)` returns structured location metadata in global target coordinates.

Target types:

- `column`: DataFrame column target, used for CSV, Excel, JSON, Parquet, and as a fallback for current flattened reader output.
- `hdf5_dataset`: native HDF5 dataset path, used for `.h5` files.

Example target metadata:

```json
{
  "name": "/S_01_01/X",
  "target_type": "hdf5_dataset",
  "dtype": "float32",
  "shape": [128],
  "display_label": "/S_01_01/X (float32, 128)"
}
```

```json
{
  "name": "Rupture Realization #",
  "target_type": "column",
  "dtype": "object",
  "shape": [50],
  "display_label": "Rupture Realization #"
}
```

HDF5 value locations preserve native path and index metadata, with display strings derived only at the UI/result edge. Example structured location:

```json
{
  "path": "/S_01_01/X",
  "index": [0],
  "display": "/S_01_01/X[0]"
}
```

This avoids ambiguity for dataset names containing commas, such as `/S_01_01/STLA,STLO,STDP`, and supports multidimensional arrays such as `/group/data[1,2]`.

`locate(index_tuple)` is defined in global target coordinates. For v1, a single loaded block can pass indices through directly; future true chunked reads must either have `locate` translate within-chunk indices to global dataset indices or carry an explicit block offset so reported HDF5 locations remain correct.

Tabular locations use structured metadata:

```json
{
  "row_index": 12,
  "source_line": 14,
  "display": "row 12"
}
```

`source_line` is optional and must be omitted when the reader cannot derive it confidently.

Add public API:

```python
aidrin.calculate_custom_outliers(file_info, rules, max_outliers=100)
```

Rule schema:

```json
{
  "id": "waveform-x-range",
  "name": "S_01_01 X waveform range",
  "target": "/S_01_01/X",
  "target_type": "hdf5_dataset",
  "criteria_type": "range",
  "min": -1.0,
  "max": 1.0,
  "min_inclusive": true,
  "max_inclusive": true,
  "allow_missing": false
}
```

`id` is required after validation. The UI should generate stable IDs for rule rows; the public API should reject missing/duplicate IDs with a validation error rather than silently inventing keys. `name` is optional and defaults to `id` for display.

```json
{
  "id": "rupture-realization-integer",
  "name": "Rupture realization is integer",
  "target": "Rupture Realization #",
  "target_type": "column",
  "criteria_type": "regex",
  "pattern": "^[0-9]+$",
  "allow_missing": false
}
```

## Implementation Changes

- Implement `custom_outliers` as a new structured data metric that consumes iterator blocks rather than directly reading DataFrames.
- Keep existing `completeness`, IQR `outliers`, `duplicity`, and `hdf5Reader.read()` behavior unchanged. Reuse helper behavior where needed, but do not refactor existing readers or metric schemas as part of this feature.
- Keep the new iterator layer in a new module rather than modifying existing reader contracts.
- Use vectorized checks over arrays/chunks. The metric should materialize full boolean masks and summary counts, but only build detailed outlier records for the preview cap.
- Range rules convert values to numeric and report non-convertible values as invalid with reason `non_numeric`.
- Range rules allow one-sided bounds: `min` or `max` may be omitted/null, but at least one bound is required.
- Regex rules evaluate a documented canonical string form and report invalid values with reason `regex_mismatch`. Use `str(value)` for scalar values after missing detection, and test numeric/float behavior explicitly so patterns like `^[0-9]+$` have predictable results.
- Missing values are counted separately and treated as invalid unless `allow_missing=true`.
- HDF5 iteration should use `h5py` directly, visit only dataset objects, skip unsupported compound/object datasets with an explicit per-rule error, and avoid depending on the existing flattening reader.
- HDF5 missing-value handling must reuse the existing `_collect_fill_values` behavior from `hdf5Reader` so `_FillValue`, `missing_value`, and native fill sentinels are classified consistently with completeness and other metrics.
- Explicit fill sentinels from user-provided values, `_FillValue`, `missing_value`, and non-default native fill values are counted as missing, not ordinary numeric outliers.
- Uncertain native default fill values, especially HDF5 default zero, must follow the current reader policy in v1: if they match data, classify them as missing and emit/log the same warning semantics as `hdf5Reader.read()`. This preserves cross-metric consistency but must be called out in results or logs because zero can be a valid waveform value.
- For large HDF5 datasets, v1 may load a dataset/block into memory for correctness, but the iterator boundary must be chunk-ready so this can be replaced with true chunked reads without changing the metric API.

## Web App Changes

- Extend Data Quality with a fourth checkbox: **Check outliers with custom criteria**.
- Add a compact rule editor under that checkbox:
  - Add/remove rule rows.
  - Target dropdown populated from `iter_targets(file_info)`.
  - Criteria dropdown: `range` or `regex`.
  - Range inputs: min, max, inclusive toggles.
  - Regex input: pattern.
- Add a dedicated target-discovery route that returns `iter_targets(file_info)`. Do not overload `/feature-set`, because that route currently returns flattened DataFrame columns and those are not meaningful for native HDF5 inspection.
- Submit rules as hidden JSON field `custom_outlier_rules`; `/data-quality` validates it and adds a `Custom Criteria Outliers` result card only when the new checkbox is selected. Existing checkbox names, payloads, and result cards for completeness, IQR outliers, and duplicity must remain unchanged.
- Keep standard rendering: summaries and outlier preview appear in Results; raw JSON contains the structured details.
- Treat rule `id`, rule `name`, target labels, preview values, and all result keys as untrusted user-controlled content. Before exposing this feature, update the generic result renderer to escape keys and scalar values in `renderScoresSection` and `buildResultCard`, or ensure untrusted rule IDs/names are not used as display keys. The preferred fix is renderer-wide escaping implemented as small helper calls, preserving existing renderer structure and output shape.
- Preserve compatibility with existing raw JSON display by continuing to use `escapeHtml(JSON.stringify(...))` for raw JSON.
- In `web/static/js/inspector.js`, isolate new behavior in small helpers for custom-rule editor setup, rule serialization, and target loading. Avoid broad refactors of `workspaceSubmit`, result rendering, or existing metric branches.

## Globus Behavior

- Custom criteria should work in Globus mode in v1 if the remote endpoint has the updated AIDRIN package and can access the selected file.
- Add a Globus target-discovery path before enabling the rule editor in Globus mode. The local target-discovery route only works for files uploaded to the Flask server.
- Required v1 behavior: when Globus mode is active, load targets through a remote discovery task using the selected remote file path/type. Do not offer manual target entry in v1. If discovery fails or the endpoint does not support it, disable custom-criteria setup and show a clear unsupported/error message.
- Extend the Globus branch in `workspaceSubmit('/data-quality')` to include `custom_outliers` in the selected metric list and pass serialized `custom_outlier_rules` plus `max_outliers` only when the new checkbox is selected. Existing Globus behavior for completeness, IQR outliers, and duplicates must remain unchanged.
- Extend `web/globus.py` remote dispatch so `_data_quality()` calls `aidrin.calculate_custom_outliers(file_info, rules, max_outliers=...)` and returns `Custom Criteria Outliers` in the bundled result.
- If Globus cannot support custom criteria for a given endpoint or file, the UI should return a clear unsupported/error result instead of silently ignoring the checkbox.

## Result Shape

Return:

- `Rule summaries`: keyed by a sanitized internal rule key derived from rule `id`, with original user-provided `id` and `name` stored as raw API data. Include target, target type, criteria type, total, valid, outlier, missing, outlier rate, preview limit, and truncated flag. Escape user-controlled values only when rendering HTML, not in the public API/raw JSON payload, to avoid data pollution and double escaping.
- `Outlier preview`: keyed by the same sanitized internal rule key, with up to `max_outliers` records per rule. Each record includes target, target type, value, reason, and structured location. HDF5 locations include `path`, `index`, and display string; tabular locations include row index and optional source-line metadata when the reader can provide it.
- CSV line numbers are optional metadata, not a guaranteed field. They should come from reader/iterator knowledge, such as a single-header CSV where physical line is `row_index + 2`, and should not be guessed for generic parsed DataFrames, multi-header files, or non-CSV formats.
- `Errors`: validation or unsupported-target errors, when present.

Default preview cap is 100 per rule. The public API accepts `max_outliers`.

## Acceptance Examples

CSV: `temp/Simulations_Flatfile_1header.csv`

- Regex `^[0-9]+$` on `Rupture Realization #` reports 25 valid rows and 25 outliers ending in `patch`.
- Range `[-10, 20]` on `Hypocenter Position (km) 2` reports 40 valid rows and 10 outliers at value `-20`.

HDF5: `temp/mock_rechdf5_output_nxny.h5`

- Target discovery lists root scalar datasets, station metadata datasets, and waveform datasets like `/S_01_01/X`, `/S_01_01/Y`, `/S_01_01/Z`.
- Range rules on waveform datasets report locations with native array indices, not flattened DataFrame row numbers.
- Dataset names containing commas, such as `/S_01_01/STLA,STLO,STDP`, are selectable and processed correctly.
- Equivalent generated HDF5 test fixtures include at least one multidimensional dataset to verify locations such as `/group/data[1,2]`.
- Generated HDF5 fixtures include explicit fill values so fill sentinels are counted as missing instead of numeric outliers.

## Test Plan

- Unit tests for `iter_targets` and `iter_value_blocks` on generated CSV and HDF5 fixtures.
- Unit tests for regex, range, one-sided ranges, missing values, non-numeric range values, invalid regex, missing target, duplicate-target rules with different IDs, and capped previews.
- Unit tests for regex stringification on numeric and float values.
- HDF5 unit tests must generate fixtures in-test following the existing `tests/unit/test_hdf5_reader.py` style. Include `/S_01_01/X`, `/Y`, `/Z`, comma-containing dataset names, a multidimensional dataset, and explicit fill-value metadata.
- HDF5 tests must verify fill-value-to-missing behavior is consistent with `hdf5Reader._collect_fill_values`.
- HDF5 tests must include the uncertain default-zero case and assert the v1 policy: default zero matches are counted as missing and warning semantics are preserved.
- Frontend/security tests or targeted JS tests must verify result rendering escapes user-controlled rule IDs, rule names, keys, and scalar preview values.
- Globus tests or focused unit coverage must verify custom outlier params are included in data-quality Globus submissions and remote dispatch returns `Custom Criteria Outliers`.
- Public API tests for `aidrin.calculate_custom_outliers`.
- Integration tests for `/data-quality?return_type=json` with custom rules on the sample CSV.
- Regression tests confirming existing completeness, IQR outliers, and duplicity behavior is unchanged.
- Regression tests or existing test runs should confirm current `/feature-set`, local Data Quality submissions, and Globus Data Quality submissions still work when custom criteria is not selected.

## Assumptions

- The Data Quality UI should default to native HDF5 dataset paths for `.h5` files, because those preserve meaningful scientific locations.
- The current flattened HDF5 DataFrame representation remains available only as a fallback where the app already exposes columns.
- No new CLI is added in this pass; the importable Python API is the non-web interface.
- Local files in `temp/` are examples for manual review only; implementation tests must not depend on them.
- Minimal-impact constraint takes precedence over cleanup: avoid unrelated refactors, avoid changing existing public metric outputs, and keep all new behavior gated behind the custom-criteria option.
