# Full assessment workflow

The eleven-step assessment behind "is my dataset AI-ready", plus the custom
metric and remediation workflows its last two steps offer.

Read this when SKILL.md's path choice sends you here: the user wants an overall
readiness judgment, or they named one metric whose column roles you would be
inferring. A single metric whose columns are named or not needed is answered by
the quick answer path in SKILL.md and does not need this file.

## Contents

- Full assessment path — the checklist and Steps 1-11
- Assessment tracking — only when `mlflow_enabled` is true
- Custom metrics — scaffolding a metric AIDRIN does not ship
- Remediation — applying fixes to the dataset

### Full assessment path

Copy this checklist and work through it in order:

Where several questions are open at once — local or remote, domain grounding,
plan approval — put them in one turn rather than asking each as you reach it.
Answering once beats answering three times, and the wait between turns is the
expensive part for the user, not the reading. Step 6 still has to carry its own
explicit yes/no on the full metric list: batching it alongside other questions
is fine, but a narrower question answered in that turn does not stand in for the
plan approval.

```
- [ ] 1. Preflight: confirm AIDRIN is available; read which metrics exist; check for remote endpoints
- [ ] 2. Check for domain grounding: ask if the user has domain literature to evaluate against
- [ ] 3. Elicit intent: how will the user use this dataset?
- [ ] 4. Inspect: read the AIDRIN-parsed schema + descriptive stats
- [ ] 5. Plan: map intent + columns → metrics + arguments (with rationale)
- [ ] 6. Confirm plan with the user (HARD gate on column roles + domain grounding)
- [ ] 7. Validate planned column names against the schema
- [ ] 8. Run metrics (+ the agentic pipeline, if domain grounding was requested; if tracking is on, open an assessment first and pass its session_id)
- [ ] 9. Write the report from ../assets/report-template.md; save raw JSON alongside
- [ ] 9b. If tracking is on: close the assessment, attaching the report
      (MCP: `end_assessment(session_id, report_path=...)`; CLI: `aidrin batch ... --report <path>`)
- [ ] 10. Ask if the user wants any custom metrics evaluated
- [ ] 11. Ask if the user wants any remedies applied to the dataset
```

### 1. Preflight

**MCP:** Call `list_metrics()`. Pass `category=` to filter by group (data-quality,
data-structure, impact-of-data-on-AI, fairness-and-bias, data-governance).

The response is `{"metrics": {<category>: [...]}, "mlflow_enabled": <bool>}`. Read the
metric catalogue from `metrics`, and note `mlflow_enabled` — it decides whether this
assessment is recorded (see Assessment tracking below). No extra call is needed for it.

**CLI:** Run `aidrin list --capabilities`. It returns the same catalogue wrapped as
`{"metrics": {...}, "mlflow_enabled": <bool>, "experiment": <name|null>}` — the same
shape the MCP tool returns, so the tracking section below applies to both paths. Plain
`aidrin list` returns the bare catalogue and is what you want if you only need the
metric names. If it fails, see [reference/installation.md](installation.md).

The returned catalogue is the source of truth. If a metric the user requests is
not listed, **do not run it** — instead, offer to implement it as a custom
metric using `create_custom_metric` (see the Custom metrics section below).

**Remote endpoints:** also call `list_remote_profiles()` (MCP) or run
`aidrin remote list` (CLI). If any profile is configured, ask once whether this
dataset is local or on that endpoint, then keep that answer for the session.

### Assessment tracking (only when `mlflow_enabled` is true)

When the preflight reports `mlflow_enabled: true`, AIDRIN records this assessment to
MLflow so the dataset's readiness can be compared over time.

1. Before running any metric, call `start_assessment(file_path)` and keep the returned
   `session_id`.
2. Pass `session_id=` to every `run_aidrin_metric` call in this assessment.
3. After writing the report, call `end_assessment(session_id, report_path=<path>)`. This
   writes the dataset's aggregated readiness scores and attaches the report.

Each metric becomes its own MLflow run, nested under one parent run that carries the
aggregated scores. Mention the tracked run once in your report; do not otherwise change
how you assess or what you report.

When `mlflow_enabled` is false, skip all of this — do not call the assessment tools and do
not mention tracking.

**On the CLI path** there is no session to manage: `aidrin batch` and `aidrin data-quality`
open and close their own assessment. To attach the finished report to it, pass
`aidrin batch <config> --report <path/to/report.md>` — the equivalent of `end_assessment`'s
`report_path`. Write the report first, then run the batch with `--report`, or re-run the
batch once the report exists. The flag is ignored when tracking is off, so it is always
safe to pass.

Remote batches (`aidrin remote batch`, or `profile=`) execute on the endpoint and are not
tracked; `--report` has nothing to attach to there.

Only what AIDRIN computes is recorded: readiness scores and runtimes. Column names, cell
values and file paths are deliberately withheld from the tracking server, so a tracked
assessment never exports the data it is assessing.

### 2. Check for domain grounding

Ask every time, before eliciting general intent:

> "Do you have domain-specific literature (PDFs, standards, regulations, guidelines)
> this dataset should be evaluated against? If so, share the file or folder path and
> I'll ground part of the assessment in those documents, in addition to the standard
> metrics. If not, I'll run the standard assessment only."

**If no path is given**, skip straight to Step 3. Nothing else about the workflow changes.

**If a path is given:**
- Requires `pip install 'aidrin[agentic]'` and an API key for one of the two supported
  providers — OpenRouter (`OPENROUTER_API_KEY`) or LBL CBORG (`CBORG_API_KEY`) — available
  in the environment. The pipeline uses exactly one provider for the whole run; don't mix
  the two. If a build-index call reports agentic dependencies are missing, tell the user
  and fall back to the standard workflow rather than retrying.
- Ask what specific domain requirements or questions to check against that literature
  (e.g. "Does more than 80% of the data conform to IEC smart-meter resampling
  standards?"). The user supplies these — don't invent domain-specific questions
  yourself, they know the regulation better than you do.
- Ask which provider and model to use (e.g. "OpenRouter or CBORG, and which model on
  that provider? Default: OpenRouter with `openai/gpt-oss-120b`."). One answer sets a
  single `llm` block (`base_url` + `model`) reused by all four LLM stages (executor,
  retrieval, complexity_scorer, remediation) — don't ask per stage, and don't let the
  user pick different providers for different stages. Leave `llm.embedding_model` on
  its default (`openai/text-embedding-3-large`) unless the user brings it up unprompted.
- **How the dataset gets loaded for the pipeline** (the agentic profiler is a separate
  code path from AIDRIN's own file parser — it does not reuse Step 4's reader):
  - Plain comma-separated CSV → use `paths.data_csv` directly, no extra step.
  - Any other AIDRIN-supported format (Excel, JSON, NPZ, H5, Parquet) → write a small
    `data_loader.py` yourself that wraps AIDRIN's own `read_file()`
    (`aidrin.file_handling.file_parser.read_file`) — the same reader Step 4 already
    used successfully, so no separator/sheet-name guessing needed. Point
    `paths.data_loader` at it.
  - A format AIDRIN doesn't parse at all (e.g. a semicolon-delimited `.txt`) → ask the
    user for the path to a `.py` file with a function that returns a pandas DataFrame,
    the same way `examples/agentic/power_consumption/loader.py` does it. Point
    `paths.data_loader` at `"<path>:<function_name>"` and use it as-is. Don't invent
    one yourself without seeing the file — a wrong delimiter/encoding guess silently
    produces bad data — and don't materialize it to CSV first; that doubles storage
    for no benefit when only the agentic pipeline needs it.
- Carry the resource path and questions forward — they get folded into the Step 6 plan
  confirmation and used to build the config in Step 8. See [reference/advanced.md](advanced.md)
  for the full config schema and command reference.

### 3. Elicit intent

**If the user already stated a specific dimension** (e.g. "check fairness", "is my data
private", "check for bias", "assess completeness"), treat that as the intent — do not
ask again. Only ask for any column information still needed for that dimension (e.g.
"which column is the sensitive attribute?" for a fairness check).

**If no intent is stated**, ask how the user plans to use the dataset. Examples that
change the plan: train a supervised model (and on what target?), ensure fairness across
groups, publish/share the dataset, general quality check, or "it contains PII". Real
answers are often blended (train AND publish) — handle the union.

**A blank or skipped answer is not an answer.** If you asked this alongside other
questions (e.g. via a batched question tool) and this one came back empty, do not
silently substitute your own inference and move on — ask it again, directly, before
building the plan in Step 5.

Dimension → metric mapping for focused requests:

| Stated dimension | Metrics to run |
|---|---|
| Fairness / bias | class-imbalance, statistical-rates, representation-rate |
| Privacy / PII / anonymity | k-anonymity, l-diversity, t-closeness, entropy-risk, single-attribute-risk, multiple-attribute-risk |
| HIPAA / PHI compliance | hipaa-compliance |
| Data quality / completeness / duplicates / outliers | completeness, duplicity, outliers |
| File paths / referenced files / manifest validation | file-reference-validation |
| Data structure / distribution shape / collinearity / redundant features | max-pairwise-correlation, skewness, kurtosis |
| Feature relevance / AI impact | feature-relevance, correlations |
| Class imbalance | class-imbalance |
| FAIR / metadata quality (Croissant, RO-Crate, DCAT-US 3.0 or 1.1, DataCite JSON) | `aidrin fair <metadata.json>` (detects the standard; MCP: `check_fair_compliance`); scores the metadata file, not the dataset |
| Data structure / organization | constant-feature-count |
| Full readiness (no specific dimension) | all applicable metrics per the intent table in Step 5 |

Always add the zero-arg quality baseline (completeness, duplicity, outliers) even for
dimension-specific requests — it takes no column args and gives essential context.

For a focused file-reference request, run only `file-reference-validation` unless the
user also asks for broader readiness analysis. Confirm the path-bearing targets and,
when relative references do not use the manifest directory, the base directory. MCP
checks the filesystem of the MCP server host, not the user's client machine.
Use `target_match="regex"` only when the user wants each target value treated as a
full-match regular expression; exact names remain the default.

### 4. Inspect the dataset

**MCP:** `summarize_dataset(file_path="...")`

**CLI:** `aidrin summarize <file>` (add `--summary` for a human-readable table; `--max-features N` to limit output on wide datasets)

This returns shape, all column names, per-column descriptive stats (numerical: mean/std/min/max/quartiles; categorical: unique count/top value/freq), and missing counts per column — using AIDRIN's own file parser, so column sets are accurate for non-CSV formats (JSON/NPZ/H5 reshape data differently than a plain pandas read).

Use the output to identify candidate column roles: target, sensitive attributes, quasi-identifiers, id column, categorical vs numerical.

**If this errors with "Unsupported file type"** (e.g. a semicolon-delimited `.txt`,
a proprietary format, or anything else AIDRIN's parser doesn't recognize), AIDRIN has
no built-in reader for it, and general inspection/metrics can't run on this file as-is.
Don't treat it as a blocker on its own:

- If domain grounding was requested in Step 2, its third loader case covers exactly
  this — get a user-supplied `.py` loader and point `paths.data_loader` at it for the
  agentic pipeline. That pipeline never needed the general reader in the first place.
- If domain grounding was not requested, tell the user plainly that AIDRIN has no
  built-in reader for this format, so the standard metric catalogue can't run on it —
  ask if they want to reconsider domain grounding (to use a custom loader via the
  agentic path) or provide the data in a supported format instead.

### 5. Build the plan

Map intent + columns to metrics using the table below. For each chosen metric,
note the arguments you will pass. Give a one-line rationale per metric. Always
include the zero-arg quality baseline.

| User intent | Metrics | Columns needed |
|---|---|---|
| Train supervised model | completeness, duplicity, outliers, feature-relevance, class-imbalance, correlations | target; categorical/numerical features; correlations & feature-relevance need columns |
| Ensure fairness across groups | class-imbalance, statistical-rates, representation-rate | target + sensitive attribute(s) |
| Publish / share externally | k-anonymity, l-diversity, t-closeness, entropy-risk, single-attribute-risk, multiple-attribute-risk | quasi-identifiers, sensitive column, id column + eval columns |
| General quality / exploration | completeness, duplicity, outliers, constant-feature-count, correlations | correlations needs columns |
| Contains PII / sensitive data | governance + privacy set above, hipaa-compliance | quasi-identifiers, sensitive column; hipaa-compliance needs columns to scan |

Always-run baseline (zero-arg): completeness, duplicity, outliers.

### 6. Confirm the plan (HARD gate)

Present the plan AND explicitly list every inferred column role — target /
sensitive / quasi-identifiers / id — each with a one-line reason. Add: "I may
have missed indirect identifiers (e.g. zip, birthdate, rare categories) — please
confirm or correct these." Do not run anything until the user confirms. Wrong
quasi-identifiers produce a falsely reassuring privacy result.

If Step 4's general inspection was skipped or failed (e.g. `aidrin summarize`
rejected the format and a custom loader was used instead per Step 2), say so
explicitly instead of presenting an empty column-role list — e.g. "General
inspection wasn't available for this format; column roles below come from the
agentic profiler / your description instead."

If domain grounding was requested in Step 2, also list the resource path(s) that
will be indexed, the exact domain questions that will be run against them, and the
provider + model that will be used for all four LLM stages — this is the only
checkpoint before any LLM API calls happen, so make sure the user sees it before you
build the index or run the pipeline.

**This confirmation must be its own explicit yes/no request covering the complete
metric list** — e.g. "Run this plan?" with the full list restated. A narrower question
asked in the same turn (confirming one column's role, resolving a setup blocker, etc.)
does not satisfy this gate, even if the user answers it. If the dedicated plan-approval
question wasn't asked and explicitly answered, the plan is still unconfirmed — do not
call any run tool or CLI command yet.

### 7. Validate column names

Check every column name in the plan against the schema from Step 4. Fix typos /
casing / non-existent columns before running.

### 8. Run the metrics

Run only the metrics confirmed in Step 6 — don't add, drop, or substitute any once you
start, even if you think of a better one mid-run; go back to the user if scope needs to
change. Don't execute the whole batch silently: give a short progress note between
groups (e.g. "baseline done — next: correlations") rather than running uninterrupted
for minutes with no visible checkpoint.

**MCP path (preferred):**
- Zero-arg baseline: one call — `run_data_quality_check(file_path="...")` runs completeness, duplicity, and outliers together.
- Per metric: `run_aidrin_metric(file_path="...", metric="class-imbalance", target_column="income")`. All column args are named kwargs — no positional ordering to worry about. If `mlflow_enabled` was true at preflight, also pass `session_id=` (from Step 1's Assessment tracking) to every call.
- If a metric fails, its returned JSON contains an `Error`/`ErrorType` key. Record it as "Not run: <reason>" and continue with the rest.

**CLI path (fallback):**
- Default: one `aidrin run <metric> <file> <args...>` per metric. This isolates errors.
- Batch the zero-arg baseline: `aidrin batch <config>` with `{"file_path": "...", "metrics": ["completeness","duplicity","outliers"]}`.
- NOTE: `aidrin run` exits 0 even on failure — detect failures by checking the JSON output for an `Error`/`ErrorType` key, not the exit code.
- Args are positional — see [reference/metrics.md](metrics.md) for order.

**Domain-grounded pipeline (if requested in Step 2):**
1. Write a short (1 paragraph) `metadata.txt` describing the dataset — pull from the
   elicited intent (Step 3) and the schema/stats from Step 4. Save it next to the dataset.
2. Write `config.yaml` following the schema in [reference/advanced.md](advanced.md):
   `paths.metadata_csv` = the file from step 1, `vector_store.sources` = the resource
   path from Step 2, `retrieval.questions` = the user's domain questions from Step 2.
   Set `llm.base_url` and `llm.model` to the provider and model chosen in Step 2 — one
   block, reused by all four LLM stages. Leave `llm.embedding_model` on
   `openai/text-embedding-3-large` unless the user said otherwise. For loading the dataset itself, use whichever of the three cases
   from Step 2 applied: `paths.data_csv` for plain CSV, a `read_file()`-wrapping loader
   you write for another AIDRIN-supported format, or the user-supplied loader path for
   a format AIDRIN can't parse.
3. Build the index (skip if one already exists for this config): MCP
   `agentic_build_index(config_path="...")` / CLI `aidrin agentic build-index -c <config>`.
4. Run the pipeline: MCP `agentic_run(config_path="...", output_path="...")` / CLI
   `aidrin agentic run -c <config> -o <output>`.
5. Keep the returned JSON (`profile` + `queries` + `token_usage`) alongside the other
   raw metric JSON for Step 9.

### 9. Write the report

Fill in [assets/report-template.md](../assets/report-template.md). Report each
score with its directional meaning (from [reference/metrics.md](metrics.md)). Flag extremes.
Keep privacy/fairness findings explicitly conditional on the confirmed roles.
Do not state a ready/not-ready verdict — give findings + suggested next steps and
let the user decide. Save each metric's raw JSON next to the report and list the
calls/commands run. If the domain-grounded pipeline ran, fill in the report's
"Domain-grounded findings" section too — one entry per question, with its answer,
complexity/confidence, and suggested remediation from the returned JSON.

### 10. Offer custom metrics

After delivering the report, ask:

> "Are there any additional metrics you'd like to evaluate that aren't covered
> by the built-in set? I can scaffold a custom metric for anything specific to
> your domain or use case."

If the user says yes, follow the Custom metrics workflow below, then append
the findings to the report (sections 4 and 6) before proceeding to Step 11.
The remedy offer in Step 11 must be based on the complete picture — built-in
and custom metrics combined.
If the user says no, proceed to Step 11.

### 11. Offer remediation

After Step 10, ask:

> "Would you like me to apply any remedies to the dataset based on the findings?
> For example: [list 1–3 concrete issues found, e.g. 'cap outliers in hours.per.week',
> 'drop duplicate rows', 'rebalance the income classes']. I can implement and run
> a remedy that writes a cleaned copy of the dataset."

If the user says yes, follow the Remediation workflow below.
Do not apply any remedy without explicit user confirmation — data changes are irreversible.

## Custom metrics

When the user wants a non-standard metric or a data-cleaning step. `file_path` accepts any
supported format (CSV, Excel, JSON, NPZ, HDF5, Parquet) — pass `file_type` to override
detection when the extension is ambiguous. Remedy output is always saved as CSV, regardless
of the input format, since JSON/NPZ/HDF5 don't round-trip losslessly back to their original
structure.

**MCP:**
1. `create_custom_metric(name="my_audit", directory="/path/to/dir")` — scaffolds a `CustomDR` class template file.
2. User edits the file: implement `metric(self, **kwargs)` returning a dict; `remedy(self, metric_results)` returning a DataFrame. Access the dataset via `self.dataset`.
3. `run_custom_metric(metric_name_or_path="/path/to/my_audit.py", file_path="...", file_type="...")` — runs the metric (after user review of the file).
4. `run_custom_remedy(metric_name_or_path="/path/to/my_audit.py", file_path="...", output_dir="...", file_type="...")` — applies the remedy and saves a new CSV.

**CLI:**
- Scaffold: `aidrin add-custom-module <name> --dir <dir>` — creates the `CustomDR` class template.
- Run: `aidrin run custom <path> <file> metric --file-type <type>` / `aidrin run custom <path> <file> remedy --file-type <type>`.

## Remediation

If the user asks to fix, clean, or remediate the dataset based on metric findings, use
the `remedy()` path to produce a corrected output file. After the user confirms, apply it —
do not just describe what should change.

**Workflow:**
1. Identify the issue from the metric result (e.g. high duplicity, missing values, imbalanced classes).
2. `create_custom_metric(name="<issue>_remedy", directory="<dataset_dir>")` — scaffold the template.
3. Implement the `remedy(self, metric_results)` method to address the specific issue. Access the dataset via `self.dataset` and return a cleaned DataFrame.
4. `run_custom_remedy(metric_name_or_path="<path>", file_path="<dataset>", output_dir="<dir>")` — apply the fix and save the remedied CSV.
5. Report: path to the remedied file, what was changed, and any caveats (e.g. rows dropped, values imputed).

**CLI:** `aidrin run custom <path> <file> remedy`

**Notes:**
- The `metric()` method stub can be left as a pass-through if the user only needs remediation.
- Confirm the remedy logic with the user before running — data changes are not reversible without the original.
- If the user wants to remediate multiple issues, create a separate custom metric per issue and chain them (output of one becomes input of the next).
