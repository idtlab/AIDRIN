---
name: aidrin
description: Use when the user asks "is my data AI ready", "is my dataset ready", "what is the quality of my data", whether data is good enough to train or publish, to check a dataset for bias, fairness, privacy, PII risk, class imbalance, duplicates, outliers, completeness, feature relevance, k-anonymity, or mentions AIDRIN. Supports CSV, Excel (.xls/.xlsb/.xlsx/.xlsm), JSON, NumPy (.npz), HDF5 (.h5), and Parquet files.
---

# Assessing dataset AI-readiness with AIDRIN

Drive AIDRIN to assess a dataset and produce an interpreted markdown report.
AIDRIN runs the metrics; you choose what to run based on the user's intent,
interpret the results, and report scores with their meaning. You do NOT
declare a final ready/not-ready verdict — that judgment is the user's.

## Tool path: MCP vs CLI

**Check for MCP first.** If the `list_metrics` tool appears in your available
tools, the AIDRIN MCP server is connected — use MCP tools throughout. MCP
accepts named parameters (no positional ordering), suppresses image side-effects
by default, and returns structured JSON directly. Fall back to the `aidrin` CLI
only when MCP is absent.

| Action | MCP tool | CLI equivalent |
|---|---|---|
| Preflight | `list_metrics()` | `aidrin list` |
| Summarize dataset | `summarize_dataset(file_path)` | `aidrin summarize <file>` |
| Quality baseline | `run_data_quality_check(file_path)` | `aidrin data-quality <file> [--detail]` |
| Single metric | `run_aidrin_metric(file_path, metric, ...)` | `aidrin run <metric> <file> <args...>` |
| Batch | `run_batch(config_path)` | `aidrin batch <config>` |
| Create custom metric | `create_custom_metric(name, directory)` | `aidrin add-custom-module <name> --dir <dir>` |
| Run custom metric | `run_custom_metric(metric_name_or_path, file_path)` | `aidrin run custom <path> <file> metric` |
| Apply custom remedy | `run_custom_remedy(metric_name_or_path, file_path)` | `aidrin run custom <path> <file> remedy` |
| Build agentic index | `agentic_build_index(config_path)` | `aidrin agentic build-index -c <config>` |
| Run agentic pipeline | `agentic_run(config_path, output_path, skip_vector)` | `aidrin agentic run -c <config> -o <output> [--skip-vector]` |

## Workflow

Copy this checklist and work through it in order:

```
- [ ] 1. Preflight: confirm AIDRIN is available; read which metrics exist
- [ ] 2. Elicit intent: how will the user use this dataset?
- [ ] 3. Inspect: read the AIDRIN-parsed schema + descriptive stats
- [ ] 4. Plan: map intent + columns → metrics + arguments (with rationale)
- [ ] 5. Confirm plan with the user (HARD gate on column roles)
- [ ] 6. Validate planned column names against the schema
- [ ] 7. Run metrics
- [ ] 8. Write the report from assets/report-template.md; save raw JSON alongside
- [ ] 9. Ask if the user wants any custom metrics evaluated
- [ ] 10. Ask if the user wants any remedies applied to the dataset
```

### 1. Preflight

**MCP:** Call `list_metrics()`. Pass `category=` to filter by group (data-quality,
impact-of-data-on-AI, fairness-and-bias, data-governance).

**CLI:** Run `aidrin list`. If it fails, see [reference/installation.md](reference/installation.md).

The returned list is the source of truth. If a metric the user requests is
not listed, **do not run it** — instead, offer to implement it as a custom
metric using `create_custom_metric` (see the Custom metrics section below).

### 2. Elicit intent

**If the user already stated a specific dimension** (e.g. "check fairness", "is my data
private", "check for bias", "assess completeness"), treat that as the intent — do not
ask again. Only ask for any column information still needed for that dimension (e.g.
"which column is the sensitive attribute?" for a fairness check).

**If no intent is stated**, ask how the user plans to use the dataset. Examples that
change the plan: train a supervised model (and on what target?), ensure fairness across
groups, publish/share the dataset, general quality check, or "it contains PII". Real
answers are often blended (train AND publish) — handle the union.

Dimension → metric mapping for focused requests:

| Stated dimension | Metrics to run |
|---|---|
| Fairness / bias | class_imbalance, statistical_rates, representation_rate |
| Privacy / PII / anonymity | k_anonymity, l_diversity, t_closeness, entropy_risk, single_attribute_risk, multiple_attribute_risk |
| Data quality / completeness / duplicates / outliers | completeness, duplicity, outliers |
| Feature relevance / AI impact | feature_relevance, correlations |
| Class imbalance | class_imbalance |
| Full readiness (no specific dimension) | all applicable metrics per the intent table in Step 4 |

Always add the zero-arg quality baseline (completeness, duplicity, outliers) even for
dimension-specific requests — it takes no column args and gives essential context.

### 3. Inspect the dataset

**MCP:** `summarize_dataset(file_path="...")`

**CLI:** `aidrin summarize <file>` (add `--summary` for a human-readable table; `--max-features N` to limit output on wide datasets)

This returns shape, all column names, per-column descriptive stats (numerical: mean/std/min/max/quartiles; categorical: unique count/top value/freq), and missing counts per column — using AIDRIN's own file parser, so column sets are accurate for non-CSV formats (JSON/NPZ/H5 reshape data differently than a plain pandas read).

Use the output to identify candidate column roles: target, sensitive attributes, quasi-identifiers, id column, categorical vs numerical.

### 4. Build the plan

Map intent + columns to metrics using the table below. For each chosen metric,
note the arguments you will pass. Give a one-line rationale per metric. Always
include the zero-arg quality baseline.

| User intent | Metrics | Columns needed |
|---|---|---|
| Train supervised model | completeness, duplicity, outliers, feature_relevance, class_imbalance, correlations | target; categorical/numerical features; correlations & feature_relevance need columns |
| Ensure fairness across groups | class_imbalance, statistical_rates, representation_rate | target + sensitive attribute(s) |
| Publish / share externally | k_anonymity, l_diversity, t_closeness, entropy_risk, single_attribute_risk, multiple_attribute_risk | quasi-identifiers, sensitive column, id column + eval columns |
| General quality / exploration | completeness, duplicity, outliers, correlations | correlations needs columns |
| Contains PII / sensitive data | governance + privacy set above | quasi-identifiers, sensitive column |

Always-run baseline (zero-arg): completeness, duplicity, outliers.

_Names above are readable labels. MCP uses underscore form (`class_imbalance`);
CLI `aidrin run` uses dash form (`class-imbalance`). See [reference/metrics.md](reference/metrics.md)._

### 5. Confirm the plan (HARD gate)

Present the plan AND explicitly list every inferred column role — target /
sensitive / quasi-identifiers / id — each with a one-line reason. Add: "I may
have missed indirect identifiers (e.g. zip, birthdate, rare categories) — please
confirm or correct these." Do not run anything until the user confirms. Wrong
quasi-identifiers produce a falsely reassuring privacy result.

### 6. Validate column names

Check every column name in the plan against the schema from Step 3. Fix typos /
casing / non-existent columns before running.

### 7. Run the metrics

**MCP path (preferred):**
- Zero-arg baseline: one call — `run_data_quality_check(file_path="...")` runs completeness, duplicity, and outliers together.
- Per metric: `run_aidrin_metric(file_path="...", metric="class_imbalance", target_column="income")`. Use **underscore form** for metric names. All column args are named kwargs — no positional ordering to worry about.
- If a metric fails, its returned JSON contains an `Error`/`ErrorType` key. Record it as "Not run: <reason>" and continue with the rest.

**CLI path (fallback):**
- Default: one `aidrin run <metric> <file> <args...>` per metric. This isolates errors.
- Batch the zero-arg baseline: `aidrin batch <config>` with `{"file_path": "...", "metrics": ["completeness","duplicity","outliers"]}`.
- NOTE: `aidrin run` exits 0 even on failure — detect failures by checking the JSON output for an `Error`/`ErrorType` key, not the exit code.
- Metric names under `aidrin run` are **dash form** (`class-imbalance`, `k-anonymity`). Underscore forms are rejected. Args are positional — see [reference/metrics.md](reference/metrics.md) for order.

### 8. Write the report

Fill in [assets/report-template.md](assets/report-template.md). Report each
score with its directional meaning (from [reference/metrics.md](reference/metrics.md)). Flag extremes.
Keep privacy/fairness findings explicitly conditional on the confirmed roles.
Do not state a ready/not-ready verdict — give findings + suggested next steps and
let the user decide. Save each metric's raw JSON next to the report and list the
calls/commands run.

### 9. Offer custom metrics

After delivering the report, ask:

> "Are there any additional metrics you'd like to evaluate that aren't covered
> by the built-in set? I can scaffold a custom metric for anything specific to
> your domain or use case."

If the user says yes, follow the Custom metrics workflow below, then append
the findings to the report (sections 4 and 5) before proceeding to Step 10.
The remedy offer in Step 10 must be based on the complete picture — built-in
and custom metrics combined.
If the user says no, proceed to Step 10.

### 10. Offer remediation

After Step 9, ask:

> "Would you like me to apply any remedies to the dataset based on the findings?
> For example: [list 1–3 concrete issues found, e.g. 'cap outliers in hours.per.week',
> 'drop duplicate rows', 'rebalance the income classes']. I can implement and run
> a remedy that writes a cleaned copy of the dataset."

If the user says yes, follow the Remediation workflow below.
Do not apply any remedy without explicit user confirmation — data changes are irreversible.

## Custom metrics

When the user wants a non-standard metric or a data-cleaning step:

**MCP:**
1. `create_custom_metric(name="my_audit", directory="/path/to/dir")` — scaffolds a `CustomDR` class template file.
2. User edits the file: implement `metric(self, **kwargs)` returning a dict; `remedy(self, metric_results)` returning a DataFrame. Access the dataset via `self.dataset`.
3. `run_custom_metric(metric_name_or_path="/path/to/my_audit.py", file_path="...")` — runs the metric.
4. `run_custom_remedy(metric_name_or_path="/path/to/my_audit.py", file_path="...", output_dir="...")` — applies the remedy and saves a new CSV.

**CLI:**
- Scaffold: `aidrin add-custom-module <name> --dir <dir>` — creates the `CustomDR` class template.
- Run: `aidrin run custom <path> <file> metric` / `aidrin run custom <path> <file> remedy`.

## Remediation

If the user asks to fix, clean, or remediate the dataset based on metric findings, use
the `remedy()` path to produce a corrected output file. Do not just describe what should
change — apply it.

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

## Agentic pipeline (advanced)

For domain-specific dataset evaluation grounded in field literature. Use when the
user has domain PDFs (research papers, standards, regulations) and wants to evaluate
whether the dataset meets domain-specific requirements — not just generic quality
checks. Requires `pip install 'aidrin[agentic]'` and an OpenAI-compatible API key.

**How domain specificity works:** You define domain-specific questions in the config
(`retrieval.question` / `retrieval.questions`). The pipeline embeds those questions,
retrieves the most relevant passages from the indexed domain PDFs, and feeds both the
retrieved context and the dataset profile to an LLM that generates analysis code. That
code is executed against the actual dataset (with a self-healing repair loop on failure).
The questions are where you inject domain knowledge — e.g. "Does more than 80% of the
data conform to IEC smart-meter resampling standards?" or "Which EU regulation requires
profiling consequences to be disclosed?"

**Pipeline stages:** profile → (build index if needed) → retrieve → execute/self-heal → score complexity → recommend remediation

### Config structure

The pipeline is entirely config-driven. Create a YAML file with these sections:

```yaml
llm:
  base_url: "https://api.openai.com/v1"   # any OpenAI-compatible endpoint

paths:
  data_loader: "./loader.py:load_dataset"  # Python function returning a DataFrame
  # OR: data_csv: "./data/mydata.csv"      # for plain CSV
  metadata_csv: "./data/metadata.txt"      # free-text domain description (required)

vector_store:
  sources:
    - ./sources                            # directory of domain PDFs
  embedding_model: text-embedding-ada-002
  vector_store_name: my_index             # output directory name
  chunk_size: 1000
  chunk_overlap: 200

retrieval:
  enabled: true                           # false = skip RAG, use LLM knowledge only
  answer_model: gpt-4o                    # any model served at base_url
  top_k: 3
  max_workers: 4                          # questions run in parallel
  question: "Single question as a string"
  # OR for multiple:
  # questions:
  #   - "First domain question"
  #   - "Second domain question"

executor:
  enabled: true
  max_attempts: 5                         # self-heal retries
  model: gpt-4o                           # any model served at base_url
  temperature: 0.0

complexity_scorer:
  enabled: true
  model: gpt-4o                           # any model served at base_url

remediation:
  enabled: true
  model: gpt-4o                           # any model served at base_url

output:
  save_log: true
```

`paths.data_loader` is required for non-CSV datasets. It points to a Python file and
function (`"./loader.py:load_dataset"`) that returns a pandas DataFrame.

When `retrieval.enabled: false`, the pipeline generates code from LLM knowledge and
the data profile alone — no PDFs or vector store needed.

### Running

**MCP:**
1. `agentic_build_index(config_path="/abs/path/config.yaml")` — index domain PDFs into FAISS (run once; skip if index already exists).
2. `agentic_run(config_path="/abs/path/config.yaml", output_path="results.json")` — runs the full pipeline. Set `skip_vector=True` only if you already built the index in a prior call.

**CLI:**
```bash
aidrin agentic build-index -c path/to/config.yaml
aidrin agentic run -c path/to/config.yaml -o path/to/results.json [--skip-vector]
```

Returns combined JSON: `profile` + `queries` (one entry per question: retrieval, execution, complexity, remediation) + `token_usage`.

## Gotchas

**MCP:**
- Metric names in `run_aidrin_metric` use **underscore form** (`class_imbalance`, `k_anonymity`). `list_metrics()` returns **dash form** names (`class-imbalance`, `k-anonymity`) — convert dashes to underscores before passing to `run_aidrin_metric`. Dash form raises `ValueError: Unknown metric`.
- `run_data_quality_check` and `run_aidrin_metric` suppress image writes internally (`save_images=False`). No workaround needed.
- Failures surface as `Error`/`ErrorType` keys in the returned JSON — not as raised exceptions.

**CLI:**
- `aidrin run` returns exit 0 even when a metric fails; detect failures via `Error`/`ErrorType` in the JSON output.
- Metric names under `aidrin run` are **dash form** (`class-imbalance`, not `class_imbalance`). Underscore forms are rejected.
- Per-metric args are **positional**, in the order shown by `aidrin run <metric> -h`. NOT `--flags`. Quote comma-separated column lists: `"zip,age"`.
- `aidrin run` writes visualization PNGs to `/tmp/aidrin_images` by default. Suppress via `aidrin batch` with `"save-images": false`.
- If `aidrin` is not on PATH, see [reference/installation.md](reference/installation.md).
- `--detail` is already the default for `run`/`batch`; no need to add it.

**Both paths:**
- `list_metrics()` / `aidrin list` is the source of truth for available metrics. If a requested metric is absent, do not run it — offer to scaffold it as a custom metric instead.
- For non-CSV (JSON/NPZ/H5), derive the schema via `read_file`, not a plain pandas read — column sets differ.
- `statistical_rates` is label-distribution, not model-output fairness.
- `feature_relevance` needs at least one of categorical/numerical columns plus the target, or it exits 2 (CLI) / errors in JSON (MCP).
- Confirm column roles with the user before running any governance or fairness metrics. Wrong quasi-identifiers produce falsely reassuring privacy results.

## Scope

This skill covers metric assessment (all built-in metrics, custom metrics, dataset remediation, and the agentic pipeline). Out of scope: the web UI.
