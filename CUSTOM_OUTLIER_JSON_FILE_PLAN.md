# JSON File Input for Custom Criteria Outliers

## Goal

Allow users to provide custom-outlier conditions from a JSON file through the
web app, the `aidrin` CLI, and the MCP server. The feature must use the
existing custom-outlier rule semantics unchanged: rules define expected valid
values, and values that fail a rule are reported as outliers.

## Current behavior

- The custom-outlier engine already accepts a list of criteria-tree rules.
- The CLI accepts either an inline JSON array (the optional `rules-json`
  positional argument) or repeatable `--rule` shorthand for simple rules.
- The web app has a manual rule editor that serializes the rule list into the
  `custom_outlier_rules` request field for both local and Globus execution.
- MCP exposes both the generic `run_aidrin_metric` tool and the dedicated
  `run_custom_outlier_check` tool; both currently take inline `rules_json`.

## Accepted JSON format

The file is a UTF-8 JSON document whose root value is the existing rules
array. No wrapper object or alternative rule syntax is introduced.

```json
[
  {
    "id": "valid-age",
    "name": "Valid age",
    "target": "age",
    "target_type": "column",
    "allow_missing": false,
    "criteria": {
      "type": "range",
      "min": 0,
      "max": 120,
      "min_inclusive": true,
      "max_inclusive": true
    }
  }
]
```

The existing validator remains the source of truth for rule IDs, target
types, range bounds, regular expressions, nested `and`/`or`/`not` criteria,
and missing-value behavior. A file only changes how the same rule list is
supplied.

## Implementation

### Shared headless path

- Add a small shared JSON-file loader for custom-outlier rules in the headless
  metric path. It reads a local UTF-8 file, parses JSON, and returns the raw
  list to the existing runner and validator; do not serialize it again, so
  `run_outliers_custom` receives an already-parsed list and does not take its
  string-parsing branch.
- Update `run_metric(..., metric="outliers-custom")` to accept `rules_file`
  in addition to its current parsed `rules` and inline `rules_json` inputs.
- Determine source exclusivity from values that are non-`None` and non-empty,
  never from key presence: CLI kwargs always contain sibling `rules` and
  `rules_json` keys with `None` values. Exactly one of non-empty `rules`,
  `rules_json`, and `rules_file` is allowed.
- Keep `run_metric` as the defensive shared enforcement layer. The CLI also
  rejects its own conflicting argument combinations before calling it, using
  a consistent `Use exactly one custom-outlier rule source` message; API and
  MCP callers receive the equivalent `Provide exactly one ...` validation
  error from `run_metric`.
- Report file-read failures, malformed JSON, and a non-array root before the
  metric executes. An empty array is a distinct valid-JSON case that reaches
  the existing `_validate_rules` error for an empty rule list. Preserve all
  other criteria validation and the metric output shape.

### CLI

- Add `--rules-file PATH` to `aidrin run outliers-custom`.
- Keep the existing positional `rules-json` input and repeatable `--rule`
  shorthand unchanged for backward compatibility.
- In CLI argument handling, reject `--rules-file` combined with either inline
  `rules-json` or `--rule` before `run_metric` is called; retain the existing
  early `rules-json` plus `--rule` rejection. Add regression coverage that
  positional-only and `--rule`-only calls still work while their sibling kwargs
  are `None`.
- Document the new form, for example:

  ```bash
  aidrin run outliers-custom dataset.csv --rules-file rules.json
  ```

### MCP

- Add optional `rules_file` arguments to both `run_custom_outlier_check` and
  generic `run_aidrin_metric`.
- Change the dedicated tool signature to
  `rules_json: str | None = None`; it forwards `rules_json` and `rules_file`
  unchanged to `run_metric`, which owns the exactly-one-source guard and file
  loading. Keep inline `rules_json` supported.
- Document that the path is resolved on the MCP server host and must be
  readable by that process.

### Web app

- Keep manual rule entry as the default and add an explicit source selector:
  **Manual rules** or **JSON file**.
- For the JSON-file source, display a `.json` file chooser and hide the manual
  rule editor. The selected file is read in the browser at submission time,
  parsed as a rules array, and is not imported into the editor.
- Do not import the file into the editor, upload or persist the file, or alter
  the existing `/data-quality` route contract. Submit the parsed array through
  the current `custom_outlier_rules` field.
- Implement an async shared source resolver. In JSON-file mode it awaits
  `File.text()`/the equivalent reader and returns the parsed array; in manual
  mode it returns the existing serialized editor array. Make `workspaceSubmit`
  async and await this resolver before either local `FormData` construction or
  Globus `remoteParams` construction. Preserve the promise returned to
  `withSubmitGuard`, and do not call `fetch` or `submitGlobusMetric` until the
  resolver has settled successfully.
- Apply only lightweight browser checks to a file source: a selected file,
  readable text, valid JSON, and a non-empty array root. Deep rule validation
  remains authoritative in Python `_validate_rules` for both local and remote
  execution; surface its returned error in the usual metric result rather than
  claiming browser-side criteria-validation parity.
- Use the resolved array for both local and Globus requests so the two web
  modes receive identical rule objects. Show actionable browser errors for no
  selected file, read failure, malformed JSON, non-array content, or an empty
  array; do not submit for those shape failures.

### Documentation and example

- Update CLI and web usage documentation with the file format, source
  exclusivity, examples, and existing valid-value semantics.
- Update MCP tool descriptions for `rules_file` and its server-local path
  requirement.
- Add one reusable example JSON rule file using the accepted array format.

## Compatibility and non-goals

- Existing manual web rules, inline CLI/MCP JSON, and CLI `--rule` shorthand
  continue to work unchanged.
- Rule evaluation remains independent per rule; this feature does not add a
  global AND/OR interpretation.
- No new criteria operators, wrapper configuration schema, rule-file saving,
  browser-side persistence, remote URL fetching, or changes to metric results
  are included.
- This capability does not add `rules_file` support to batch/config runs;
  `outliers_custom` is not currently wired through `run_batch_metrics`.

## Validation

- Headless/API: valid file loading; unreadable path; invalid JSON; non-array
  JSON; empty array; missing source; and every conflicting pair of non-empty
  rule sources. Assert file-loaded lists bypass the runner's string parsing.
- CLI: successful `--rules-file` run; positional-only and `--rule`-only
  regressions with their sibling values `None`; and nonzero, clear failures for
  malformed or missing files and source conflicts.
- MCP: dedicated and generic metric tools both run from `rules_file`, retain
  inline JSON behavior, make `rules_json` optional on the dedicated tool, and
  surface the shared failures.
- Web: source-selector visibility; successful file parsing; local and Globus
  submission using the resolved file rules; and all browser shape-error cases.
  Verify asynchronous ordering: neither local `fetch` nor `submitGlobusMetric`
  is called before the selected file resolves.
- Parser consistency: use a shared fixture corpus for valid rules, malformed
  JSON, non-array roots, and empty arrays. Exercise the Python loader and a
  unit-testable browser JSON parsing helper against that corpus, asserting the
  same final accept/reject outcome and comparable error category. An empty
  array is intentionally rejected earlier as a browser shape error, while the
  Python loader passes it to `_validate_rules`; both paths must reject it
  overall. Cross-surface result equivalence is then assessed on the parsed
  rules array, not on an assumption that the browser invokes the Python
  loader.
- Regression: existing custom-outlier unit, CLI, integration, and frontend
  checks remain green; run full pytest, flake8, Prettier for changed web
  assets, and the documentation build before merge.

## Review acceptance criteria

- A single valid rules file produces equivalent custom-outlier results via the
  web app, CLI, and both MCP tool surfaces after each has produced the same
  parsed rules array.
- No caller can accidentally mix a file with an inline or shorthand rule
  source.
- The accepted file format is documented, backward compatibility is preserved,
  and source-shape failures tell users how to correct their input; deep rule
  failures remain the existing server-side validation result.

## Implementation checklist

- [x] Review and finalize the design, compatibility boundaries, and test plan.
- [ ] Add the shared file loader and source validation for the headless API.
- [ ] Add CLI and MCP `rules_file` interfaces with compatibility tests.
- [ ] Add the asynchronous web JSON-file source flow for local and Globus runs.
- [ ] Add documentation, examples, parser-consistency coverage, and full validation.
