# Variable Unit Validation Across AIDRIN

## Summary

Add an opt-in `variable_unit_validation` Data Structure metric that verifies every logical dataset variable is classified as:

- A recognized physical unit, such as `m/s^2`
- Dimensionless, represented by `1`
- Explicitly `not_applicable`, for IDs, labels, free text, and similar variables

The metric measures metadata readiness only: it will not infer units from values, convert data, or prove that a syntactically valid unit is physically correct. This follows the [CF convention](https://cfconventions.org/cf-conventions/DOI/cf-conventions.html) practices for `units` metadata and dimensionless `1` while using [Pint](https://pint.readthedocs.io/en/latest/getting/tutorial.html) for parsing and dimensionality reporting.

## Implementation Checklist

- [x] Milestone 0: create the feature branch, audit the current cross-interface architecture, and add this checklist.
- [ ] Milestone 1: implement logical-variable discovery, unit parsing and normalization, declaration validation and precedence, result aggregation, the public Python function, and focused core tests.
- [ ] Milestone 2: integrate the headless registry and runner, local and remote CLI arguments, batch configuration, remote dispatch, MCP tools, and interface tests.
- [ ] Milestone 3: add the local Data Structure web editor, import/export and filtering behavior, result rendering, target-discovery candidates, and web tests.
- [ ] Milestone 4: add Globus capability negotiation and remote web dispatch, compatibility messaging, serialization, and tests.
- [ ] Milestone 5: document the metric and mapping contract, add registry/documentation consistency coverage, run all repository validation gates, and resolve any failures.

## Core Behavior

- Discover logical variables without scanning their values:
  - Tabular formats: DataFrame columns.
  - Native HDF5: dataset paths and `units` attributes.
  - Pandas/PyTables HDF5: logical columns, excluding internal storage datasets.
  - Parquet: Arrow field metadata keys `units`, with `unit` accepted as a compatibility alias.
  - CSV, Excel, JSON, and NPZ rely on variable-name annotations or an explicit mapping.
- Recognize only trailing name annotations:
  - `velocity (m/s)`
  - `velocity [m/s]`
  - Preserve the complete original variable name as its identifier.
- Resolve sources in this order:
  1. Explicit mapping
  2. Native HDF5/Parquet metadata
  3. Variable-name annotation
- Explicit mappings override lower sources and retain an override warning. Conflicting native metadata and name annotations fail validation unless an explicit mapping resolves them. Equivalent aliases normalize to the same unit; scale-different units such as `m/s` and `km/h` remain conflicts.
- Add `pint>=0.24.4,<0.26` to core dependencies. This permits Pint 0.24 on Python 3.10 and 0.25 on newer supported Python versions; CI must verify identical metric behavior across AIDRIN's Python 3.10-3.13 matrix. See the [Pint release history](https://github.com/hgrecco/pint/blob/master/CHANGES).
- Treat bare `g` as ambiguous before Pint interprets it as gram. Report remediation:
  - `gram` for mass
  - `[g]`, `g_0`, or `standard_gravity` for acceleration
  - Internally normalize `[g]` to Pint's `standard_gravity`. UCUM identifies `[g]` as standard acceleration of free fall; see the [UCUM change log](https://ns1.unitsofmeasure.org/trac/wiki/ChangeLog).
- Use exact variable names in the mapping schema:

```json
{
  "acceleration": {"unit": "m/s^2"},
  "normalized_score": {"unit": "1"},
  "station_id": {"status": "not_applicable"}
}
```

- Reject malformed mappings or multiple explicit mapping sources. Report unknown mapping keys as stale schema errors.
- Return machine-readable results:
  - `coverage_score` and `validity_score`, from 0 to 1
  - `all_variables_ready`
  - Counts for valid, missing, invalid, ambiguous, conflicting, dimensionless, and not-applicable variables
  - One record per variable containing name, dtype, chosen source, classification, original unit, normalized unit, dimensionality, status, and actionable message
  - Lower-priority declarations and override warnings
  - Unknown mapping variables
- An empty logical schema returns null scores and `all_variables_ready: false`.

## Public Interfaces and Web Experience

- Export `calculate_variable_unit_validation(file_info, unit_declarations=None)` from the Python package and add the shared task/runner.
- Register `variable_unit_validation` under `data-structure`; the CLI name is `variable-unit-validation`.
- CLI:
  - `aidrin run variable-unit-validation DATASET`
  - Optional mutually exclusive `--units-json JSON` and `--units-file PATH`
  - The same arguments work through `aidrin remote`; a units-file path is resolved on the execution host.
- Batch configuration accepts either an inline `unit_declarations` object or `units_file`.
- MCP:
  - Add dedicated `verify_variable_units`.
  - Extend `run_aidrin_metric` with `unit_declarations_json` and `units_file`.
  - Preserve local and remote routing through the headless registry.
- Web:
  - Add **Verify variable units** to Data Structure.
  - Extend the existing shared target-discovery response with discovered unit candidates instead of adding a second page-load request.
  - Provide a searchable, paginated editor showing variable, dtype, source, classification, unit, and validation status.
  - Prefill embedded/name units, but never automatically mark other variables dimensionless or not applicable.
  - Support browser-side JSON import/export using the same mapping schema. Edits are request-local and never mutate the uploaded dataset.
  - Render summary scores plus filterable missing, invalid, ambiguous, conflict, and override details with escaped content.
- Globus web execution gains a `variable_unit_validation_v1` capability and remote dispatch. Older workers disable the control with a clear compatibility message.
- Document the metric, mapping schema, precedence, supported name syntax, host-local mapping-file behavior, ambiguity policy, and the boundary that syntax validation is not physical-correctness validation.

## Test Plan

- Core unit tests:
  - Valid compound, Unicode, dimensionless, unknown, malformed, and ambiguous units.
  - `m/s^2`, `m/s²`, `standard_gravity`, `[g]`, `g_0`, bare `g`, and `gram`.
  - Parenthesized/bracketed trailing names and non-trailing text.
  - Mapping validation, exact-name matching, stale keys, source precedence, overrides, equivalent declarations, and conflicts.
  - HDF5 attributes, native datasets, Pandas HDFStore logical columns, and Parquet field metadata.
  - Empty schemas and every classification/result count.
- Interface tests:
  - Public API, local/remote CLI, batch normalization, generic and dedicated MCP tools, and remote headless dispatch.
  - Local web execution, editor import/export, result rendering, escaping, and Globus capability negotiation/serialization.
  - Registry-to-documentation consistency.
- Validation commands:
  - Focused unit/integration suites during development.
  - `PYTHONPATH=. uv run python -m pytest tests/`
  - `uv run flake8 --config=tox.ini aidrin/ web/ worker/`
  - `npx --yes prettier@3 --check web/static/css web/static/js`
  - Strict documentation build and wheel build.
  - Confirm no unrelated runtime custom-metric files are staged.

## Assumptions

- All variables must be explicitly classifiable; dtype alone never determines whether a unit is required.
- `not_applicable` needs no mandatory reason in v1.
- Explicit overrides may pass validation while retaining warnings; unresolved conflicts, missing/invalid/ambiguous units, and stale mapping keys make `all_variables_ready` false.
- Full CF/UDUNITS conformance, expected-quantity validation, value conversion, unit inference from data, and rewriting source-file metadata are outside v1.
