# Telemetry: finish OTel tracing, add MLflow assessment tracking

Date: 2026-08-26
Status: Draft for review

## Summary

AIDRIN gains two related but independent capabilities:

1. **Tracing (OpenTelemetry).** Complete the existing, half-built instrumentation so a
   metric evaluation produces a real span on every surface, not just in two web routes.
2. **Assessment tracking (MLflow).** Record readiness assessments as MLflow runs so a
   dataset's scores can be compared across versions and over time.

They are separate features with separate consumers. They share one hook point, which is
why they are designed together and shipped in that order.

Scope is the **CLI and MCP/skill surfaces**. The web interface is in scope for the tracing
fixes only.

## Goals

- Every metric evaluation that passes through `run_metric` produces a span that encloses
  the work. Three CLI/MCP entry points bypass `run_metric` and are out of scope for Phase
  1: `run_custom_metric` (`aidrin/mcp/server.py:370`), `run_custom_remedy` (`:384`), and
  `summarize_dataset`.
- A CLI or skill-driven assessment produces MLflow runs carrying readiness scores,
  runtime, and a redacted result artifact.
- Both degrade to zero-overhead no-ops when their optional extras are absent, matching the
  existing `[telemetry]` pattern.
- Telemetry never changes a metric's result and never raises into caller code.

## Non-goals

Explicitly deferred, each with a reason:

| Deferred | Reason |
|---|---|
| Web metric routes and Readiness Report as MLflow runs | Parallel code path (~9 routes), needs per-user experiment scoping, and makes redaction load-bearing against arbitrary uploads. Revisit once the shape is proven. |
| Remote/Globus execution tracking | `run_metric` executes on the endpoint (`aidrin/compute/remote.py:429`), not the client. Would need the extra, a reachable tracking URI, and credentials on the HPC node. |
| Agentic pipeline tracking | Different data (tokens, cost, generated code) and already has `aidrin/agentic/token_tracker.py`. Worth doing, separately. |
| Celery span context propagation | Only 6 `.delay()` sites exist (`web/routes/metrics.py:3115, 3180, 3251, 3265, 3281, 3876`); two are fire-and-forget. Low value for the cost. |
| MLflow OTLP trace ingest bridge | Needs MLflow >= 3.6 with a SQL backend store and an HTTP exporter. Config-only, reversible, do it when someone asks. |
| Generic result flattener | See "Metric keys" below. The headline table plus the JSON artifact cover the need without the correctness risk. |

## Current state

Verified in the tree at `d3d02f9`.

**Correctly instrumented.** `web/routes/metrics.py:237` (`metric.data_quality`) and `:2935`
(`metric.data_structure`) open an enclosing span per request and nest 14 child spans around
the individual metric calls. This is the pattern to extend.

**Vestigial.** Seven `trace_metric(...)` sites — `metrics.py:3142, 3195, 3307, 3369, 3601,
3646, 3718` — open the span *after* the work finishes and wrap only `span.set_attribute()`,
passing a hand-computed duration. Every one is a zero-duration marker.

**Untraced.** The CLI (`aidrin/headless/`) and the MCP server (`aidrin/mcp/server.py`) have
no telemetry at all. `web/telemetry.py` lives under `web/`, so `aidrin/` cannot use it
without importing Flask.

**Untracked.** No assessment results are persisted anywhere durable. The web caches results
in `current_app.TEMP_RESULTS_CACHE`, an in-memory dict (`web/routes/utils.py:232-247`) —
per-process, lost on restart, no history.

**The seam.** `aidrin/headless/api.py:499 run_metric()` is the single local entry point for
MCP tools, CLI commands, `run_batch_metrics`, `run_data_quality`, and
`run_privacy_assessment`. It already computes `start_time`/`elapsed`. Two MCP tools bypass
it — `run_custom_metric` (`aidrin/mcp/server.py:370`) and `run_custom_remedy` (`:384`) —
and are out of scope for phase 2.

## Part A — Tracing

### A1. Move the tracer into `aidrin/`

New package, framework-agnostic, importing nothing from `web/`:

- `aidrin/telemetry/__init__.py` — public API and no-op fallbacks (`_NoOpTracer`,
  `_NoOpSpan`, `get_tracer`, `trace_metric`), moved verbatim from `web/telemetry.py`
- `aidrin/telemetry/otel.py` — provider, resource, exporter selection

`web/telemetry.py` shrinks to the Flask-specific part: `init_telemetry(app)` calls into
`aidrin.telemetry` and then `FlaskInstrumentor().instrument_app(app)`, re-exporting
`get_tracer`/`trace_metric`/`_NoOpTracer`/`_NoOpSpan` so `web/routes/metrics.py:11` and
`tests/integration/test_telemetry.py:3` keep working unchanged.

The module-global `_tracer` must exist in exactly one place — `aidrin/telemetry` — with
`web/telemetry.py` holding no copy of its own.

CI runs `flake8 --config=tox.ini aidrin/ web/ worker/` with no `--select`
(`.github/workflows/lint.yml:29`), so the re-exports need `__all__` or `# noqa: F401`.

Environment variables are unchanged: `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME`
keep their standard names. An earlier draft proposed renaming them; that was wrong — it
breaks the OTel convention, `docker/local/docker-compose.yml:23`, and
`docs/source/web_installation.rst:352,380`, and does not fix the problem it targeted.

### A2. Span at the seam

`run_metric()` wraps its dispatch in one span carrying `metric.name`, `metric.category`,
`file.name`, `file.type`, and `metric.duration_ms`. Exceptions set an error status
carrying **the exception type only, never `str(exc)`** — see B3.

Attribute sources, all of which need stating because the obvious source is absent:

- `metric.category` comes from `METRIC_REGISTRY[key]["category"]`, i.e. the vocabulary
  `data-quality`, `data-structure`, `impact-of-data-on-AI`, `fairness-and-bias`,
  `data-governance`. It is deliberately **not** `metric.pillar`: that attribute name is
  used by the web `trace_metric` sites with a *different* vocabulary (`data_quality`,
  `fairness_bias`, `impact_on_ai`, `data_governance`, `understandability`) and appears
  nowhere in `aidrin/`. Phase 1 does not unify the two; using distinct attribute names
  keeps them from being silently joined as if they matched. Custom metrics have no
  registry entry and so omit the attribute.
- `file.name` and `file.type` must be derived — `os.path.basename(file_path)` and
  `_normalize_file_type(...)`. All three MCP call sites (`server.py:235, 270, 316`) pass
  neither, and the CLI passes only `file_type` (`cli.py:940, 965, 984`), so reading the
  parameters directly yields `None` on the dominant path.
- `metric.duration_ms` is set inside `_finalize`, the only place that computes `elapsed`
  after consolidation.

**The blanket exception guard specified in B4 applies to this span too, and ships in Phase
1.** A2 is otherwise the first code to run inside the custom-metric `try` block, whose
`except FileNotFoundError` (`:524`) would relabel any telemetry failure as "Unknown
metric".

Most branches already end in `return _finalize(result)`, but the 7 fast-path metrics
(`api.py:530-538`) and the custom-metric path (`:515-521`) inline a byte-identical copy of
`_finalize`'s body (`:540-547`) instead of calling it. Those collapse into calls, giving
one exit and one hook. `_finalize` moves above the fast-path branch; its closure over `metric_key`
(assigned `:509`) and `start_time` survives the move, since Python closures bind late.

**Prerequisite — the two rewritten paths are currently untested.** No test in the repo
calls `headless.api.run_metric` with any of the 7 fast-path metrics or with a custom
metric. (`test_cli.py`'s calls cover only `hipaa-compliance`, `file-reference-validation`
and `outliers-custom` argument validation; `test_compute_executor.py`'s `completeness`
calls go through `RemoteExecutor`, not this function; `test_public_api.py` exercises
`aidrin/__init__.py`'s `calculate_*` helpers, which use `celery.apply()` and never reach
`run_metric`.) A round-trip test for each path must be written and passing **before** the
consolidation, or the placement bug described above ships undetected.

### A3. Fix the seven web call sites

Move each span to enclose the work it measures, matching `:237` and `:2935`. The two
correct blocks must not be flattened or removed.

The 7 sites are not uniformly shaped, so the rule is per-route rather than a blanket
transformation:

- The span opens at the top of the `if request.method == "POST"` block, alongside the
  existing `start_time`, and closes after the work — `store_result()`
  (`web/routes/utils.py:232`) returns a redirect and stays *outside* the span.
- Early `return jsonify(...)` error exits must close the span with an error status.
  `fair_assessment` (`:3657-3720`) has five such exits before its trace point, with the
  actual work at `:3710`.
- `correlation_analysis` (`:3195`) sits inside a nested if/else whose else-branch returns
  early; the span belongs on the working branch only.
- `class_imbalance` calls `read_file()` at `:3327-3328`, outside both the POST block and
  `start_time`; that read is not currently measured and stays outside the span, so the
  span's meaning matches the other six.

## Part B — MLflow assessment tracking

### B1. Run model

**One MLflow run per `run_metric` call**, created and closed within that call, plus **one
parent run per assessment**.

The parent is created by `start_assessment`, terminated immediately
(`set_terminated(..., "FINISHED")`), and re-opened for writes only in the sense that MLflow
permits `log_metric` on a terminated run — verified against the installed 3.15.2. Nothing
stays open across a call boundary. Per-metric runs carry `aidrin.session_id` **and**
`mlflow.parentRunId`, which gives real nesting in the UI; `tags.aidrin.session_id = '<id>'`
filters correctly.

The parent is not optional bookkeeping. With one HEADLINE metric per run, the runs-table
comparison view would compare rows that each have a single populated column, and no row
would show a dataset's readiness profile — which is precisely what "compare across versions
and over time" needs. `end_assessment` writes the aggregated HEADLINE metrics onto the
parent; that aggregated row is the comparable unit.

This replaces an earlier session-scoped design, for two reasons:

- MLflow params are write-once. A session-scoped run logging per-file params raises
  `MlflowException` on the second file of any batch — the normal case.
- `mlflow._active_run_stack` became a `ThreadLocalVariable` in 2.18. MCP dispatches sync
  tool functions on worker threads, so a run started on one thread is invisible from
  another; fluent-API calls would silently create stray runs instead of using the session.

Consequences: no `atexit` handler, no staleness timeout, no supersede rule, no orphaned
runs, and no `session.py`. Nothing stays open across a call boundary.

**All logging goes through `MlflowClient(...).log_metric(run_id, ...)` and friends. The
fluent API (`mlflow.log_metric`, `mlflow.start_run`) is never used.**

Auto-nesting under a caller's active run is dropped: `mlflow.active_run()` reads
in-process state, and the CLI and MCP server are separate processes from a user's training
script. A `AIDRIN_MLFLOW_PARENT_RUN_ID` env var covers the cross-process case if wanted
later.

### B2. Metric keys

A `HEADLINE` table maps nine scores to stable, comparable keys. Stable, hand-written keys
are what make cross-run comparison and dashboards work. The source paths are **not**
uniform — two nest the score under a parent key — so they are enumerated here rather than
rediscovered during implementation:

| MLflow key | Metric | Source path |
|---|---|---|
| `aidrin.quality.completeness` | `completeness` | `["Overall Completeness"]` (`completeness.py:71`) |
| `aidrin.quality.duplicity` | `duplicity` | `["Duplicity scores"]["Overall duplicity of the dataset"]` (`duplicity.py:48`) |
| `aidrin.quality.outliers` | `outliers` | `["Outlier scores"]["Overall outlier score"]` (`outliers.py:79`) |
| `aidrin.fairness.class_imbalance` | `class_imbalance` | `["Imbalance Degree score"]` (`class_imbalance.py:404`) |
| `aidrin.governance.k_anonymity` | `k_anonymity` | `["k-Value"]` (`privacy_measure.py:938`) |
| `aidrin.structure.max_pairwise_correlation` | `max_pairwise_correlation` | `["Max Pairwise Correlation"]` (`max_pairwise_correlation.py:102`) |
| `aidrin.structure.constant_feature_count` | `constant_feature_count` | `["Constant feature count"]` (`constant_feature_count.py:72`) |
| `aidrin.quality.feature_coverage_ratio` | `feature_coverage_ratio` | `["Feature Coverage Ratio (%)"]` (`feature_coverage_ratio.py:66`) |
| `aidrin.quality.row_level_completeness` | `row_level_completeness` | `["Row-Level Completeness (%)"]` (`row_level_completeness.py:36`) |

A missing path is skipped silently, not an error — metrics fail to a `{"Error": ...}` dict.

No generic flattener. AIDRIN result dicts are keyed by column name (e.g.
`completeness.py:45`, `privacy_measure.py:204`), and real column names contain characters
outside MLflow's key charset (alphanumerics, `_`, `-`, `.`, space, `/`; max 250 chars).
Sanitizing them collides — `Income (USD)` and `Income [USD]` both become `Income__USD_` —
and MLflow does not error on a repeated key, it appends another step to the same series,
silently merging two columns into one chart. Full fidelity lives in the JSON artifact
instead.

**Non-finite values are skipped.** Constant columns yield NaN from skewness, kurtosis, and
correlation; `_sanitize` (`api.py:262-263`) passes them through as `float('nan')`. MLflow
stores NaN behind a flag that the UI renders as `0` and maps infinities to ±max float — a
readiness dashboard showing `correlation = 0` for "undefined" is worse than a gap. The sink
checks `math.isfinite()` and skips the key, recording it as a **tag**
(`aidrin.skipped_metrics`, a comma-joined list) rather than in the artifact — under the
allowlist most metrics have no artifact body to record it in.

### B3. Redaction

**AIDRIN detects PII and PHI. It must not upload it.** `_strip_visualizations`
(`api.py:434-456`) filters six visualization keys and is not a privacy control.

Confirmed raw-value leaks in metric results:

| Source | Leak |
|---|---|
| `hipaa_compliance.py:58-62` | `"examples": list(set(col_findings))[:5]` — up to 5 verbatim matched values per column: SSNs, emails, phone numbers, IPs, URLs, VINs, medical record numbers, postal codes |
| `duplicity_by_features.py:65-74` | `"Feature values"` — actual joint column values of the top-N duplicate groups |
| `custom_outliers.py:549-557` | Preview/export rows carrying `"value"` and `"location"` for each flagged cell |
| `statistical_rate.py:34-35`, `class_imbalance.py` | Sensitive-attribute and target values as dict keys |
| `file_reference_validation.py:503` | `"Invalid references"` — `value`, `normalized_value`, `resolved_path`: raw file paths stored in the dataset |
| `statistical_rate.py:141-143` and the representation-rate family (`representation_rate`, `compare_representation_rate`, `real_repreentation_rate`, `conditional_demo_disp`) | Payloads keyed by sensitive-attribute values |
| Every metric's `except` branch | `result_dict["Error"] = str(e)` (e.g. `privacy_measure.py:222,229,484,491`; `outliers.py:141`; `class_imbalance.py:416,420`). Pandas/numpy messages routinely echo column names and offending cell values |
| Chart PNGs | Category labels — i.e. sensitive-attribute values — rendered into the image |

**The allowlist is the whole mechanism. There is no denylist.**

- A metric's result body is logged **only** if that metric declares a safe projection, and
  a projection may yield **scalars only — never a subtree**. `{key: scalar}`, full stop.
- A metric with no declared projection logs its HEADLINE scalars and runtime, and no body.
  This is the default for all 20-odd metrics that do not declare one, and for every metric
  added in future.
- `hipaa_compliance` never logs a body. Only `total_flags` and `potential_types_detected`.

An earlier draft proposed a `_redact_for_export()` denylist dropping `examples`,
`Duplicate groups`, `value`, `location`, `preview`, `export_rows`. That approach is
rejected, and the reason is worth recording so it is not reintroduced: it already leaks on
a metric in the skill's advertised surface. `file_reference_validation.py:503` returns
`"Invalid references"`, whose entries carry `value`, `normalized_value` **and**
`resolved_path` — raw file paths stored in the dataset, e.g.
`/data/patients/MRN-4417723/scan.dcm`. The denylist catches `value` and misses the other
two, and misses the containing key entirely. Enumerating bad keys cannot be made safe.
- Column names and chart PNGs are logged only under `AIDRIN_MLFLOW_LOG_DATA_DETAILS=1`
  (default off). File paths are hashed unless the same flag is set.

**Exception text is never recorded, anywhere.** Spans, tags, params and artifacts record
the exception **type** only. This applies to A2's span error status as much as to the sink:
OTel's `record_exception` captures the message and stack trace and OTLP ships it to a
collector with no redaction at all, so an unguarded `str(e)` leaks cell values off-box on
the tracing path even when MLflow is disabled.

Two further notes for the implementer:

- Redaction must not depend on `strip_visualizations`, which is a caller-controlled flag
  defaulting to `False` in `run_metric`. `privacy_measure.py:1073, 1213, 1335` emit
  `histogram_data` that `_strip_visualizations` happens to catch — but only when the caller
  asked for it.
- `_strip_visualizations`'s `EXCLUDED_KEYS` contains `descriptive_statistics`
  (underscored), while `privacy_measure.py` emits `"Descriptive statistics of the risk
  scores"` (spaced), which is column-keyed and is not stripped today. Another reason the
  allowlist cannot lean on it.

### B4. Failure isolation

Hard invariant: **telemetry never changes `run_metric`'s return value and never raises.**

- Every sink call is wrapped in a blanket `except Exception` and logged at warning level.
- `MLFLOW_HTTP_REQUEST_TIMEOUT` is set low (default is 120s, multiplied by retries — a
  wedged tracking server would otherwise hang an MCP tool call for minutes and then discard
  a computed result).
- `mlflow.config.enable_async_logging()` keeps the hot path off a synchronous round-trip
  per metric. (Exact path: `mlflow.config.enable_async_logging`; it is not exposed as
  `mlflow.enable_async_logging` on 3.15.2.)
- **`mlflow.flush_async_logging()` is called before each CLI command exits and at the end
  of `end_assessment`, inside the guard.** Async logging otherwise flushes only via
  MLflow's own `atexit` hook, which a short-lived `aidrin run` or a SIGTERM'd MCP server
  may never reach — silently dropping everything. This is the same `atexit` unreliability
  the run model deliberately avoids, and it must not return through this door.
- `MLFLOW_HTTP_REQUEST_MAX_RETRIES` is pinned low alongside the timeout; it defaults to
  **7**, so timeout alone still permits a multi-minute worst case.
- Async logging means failures surface on a background thread, where the blanket `except`
  around the call site cannot see them. The flush call is the point where they become
  observable, so it is also where the warning is emitted.
- A test asserts `run_metric` returns correct results with a sink that raises on every call.

### B5. What gets logged

- **Tags:** `aidrin.session_id`, `aidrin.interface` (`cli`/`mcp`), `aidrin.version`,
  `aidrin.trace_id` (the OTel cross-link), `aidrin.metric`
- **Params:** metric name, file type, aidrin version. Per-run and short — never column
  lists, which can exceed the 6000-char limit and raise.
- **Metrics:** `HEADLINE` scores, `aidrin.runtime_seconds`
- **Artifacts:** the redacted result JSON; the final markdown report via `end_assessment`

`mlflow.log_input()` and dataset lineage are deferred: `MAX_DATASET_DIGEST_SIZE` is 36, so
a sha256 hex digest raises, and `MetaDataset` serializes the resolved absolute path,
contradicting path hashing.

### B6. Gating and discovery

```toml
mlflow = ["mlflow-skinny>=2.18"]
```

`mlflow-skinny`, not `mlflow`: the full package pulls in Flask, alembic, `docker`,
graphene, gunicorn, sqlalchemy, scikit-learn, and a `pyarrow<18` pin that risks conflicting
with AIDRIN's `pyarrow>=15.0.0`. Everything used here — `MlflowClient`, `log_metric`,
`log_artifact`, `enable_async_logging` — is in skinny. A user running a local tracking
server installs full `mlflow` themselves. The `>=2.18` floor is **not** a fix for the
thread-local run stack — 2.18 is where that behaviour *begins*. It is pinned so the
supported range has one consistent behaviour rather than straddling the change, and because
`MlflowClient` sidesteps the issue at every version. Do not relax it on the theory that it
fixed something.

Enabled by `MLFLOW_TRACKING_URI` plus `AIDRIN_MLFLOW_ENABLED=1`. Experiment name from
`AIDRIN_MLFLOW_EXPERIMENT` (default `aidrin`). The import is lazy, so a disabled
installation pays nothing.

**Validate the tracking URI once at sink init**, and on failure warn once and report
`mlflow_enabled: false` for the rest of the process. Without this, B4's blanket guard turns
an unusable tracking server into silence while discovery still advertises tracking as on.
The common case is not hypothetical: a plain `file:///.../mlruns` URI now raises
`MlflowException` at `MlflowClient()` construction on 3.15.2 — the filesystem backend is in
maintenance mode and requires `MLFLOW_ALLOW_FILE_STORE=true` or a database backend.

**Discovery.** The MCP `list_metrics` tool (`aidrin/mcp/server.py:83-92`) currently
returns `list_available_metrics()` verbatim, a dict keyed by category. It gains a wrapper:

```json
{"metrics": {<category>: [...]}, "mlflow_enabled": true}
```

The boolean must **not** be added as a sibling of the category keys — `SKILL.md:55-62`
instructs the model to iterate that mapping as the metric catalogue, and a stray non-list
value there would be read as a category. The skill reads `mlflow_enabled` during its
existing step-1 preflight, so there is no extra tool and no extra round trip.
`list_available_metrics()` itself is unchanged (`api.py:309-341`), so the CLI is
unaffected. `aidrin list` prints a one-line footer when tracking is on.

### B7. MCP and skill surface

Two new MCP tools:

- `start_assessment(file_path, ...)` — mints and returns a session id; no MLflow run is
  opened
- `end_assessment(session_id, report_path=None, notes=None)` — uploads the report and
  writes a summary run

**How `session_id` reaches the sink.** The MCP metric tools gain an optional
`session_id` parameter, which the skill passes through from `start_assessment`'s return
value. Explicit threading, not hidden state: the MCP server is one process serving many
tool calls, and a process-global "current session" would be wrong the moment two
assessments overlap. When `session_id` is absent, the call gets a one-off session tagged
`implicit=true`.

`aidrin batch` and `aidrin data-quality` mint a session id automatically, and
`run_batch_metrics` performs the same parent-run rollup that `end_assessment` does at the
end of its loop — otherwise CLI users get N orphan runs and no comparable row.

`.claude/skills/aidrin/SKILL.md` gains two workflow steps, both conditional on
`mlflow_enabled`: call `start_assessment` before step 7 (Run metrics), and
`end_assessment(report_path=...)` after step 8 (Write the report). The report template
gains an MLflow run-link line. When tracking is off, the skill's workflow is unchanged.

## Testing

- **No-op:** with neither extra installed, all calls no-op and `run_metric` results are
  byte-identical. Extends `tests/integration/test_telemetry.py`.
- **Spans enclose work:** `InMemorySpanExporter`; assert nonzero duration and that the span
  encloses the metric call. Asserted for the `run_metric` seam *and* for the
  `data_quality`/`data_structure` routes, guarding against regressing the two blocks that
  are already correct.
- **MLflow content:** `MlflowClient` assertions on tags, params, metrics, and artifacts.
  The store needs `MLFLOW_TRACKING_URI=file://<tmp>` **plus `MLFLOW_ALLOW_FILE_STORE=true`**
  — without it `MlflowClient()` raises on construction and no MLflow test can start. A
  `sqlite:///` backend is the alternative but needs sqlalchemy and alembic, which
  `mlflow-skinny` does not ship, so it would mean a test-only CI dependency.
- **Redaction is structural, not per-metric:** iterate `METRIC_REGISTRY` and assert that
  every metric without a declared projection logs no result body. This is the test that
  still holds when metric #29 is added. Per-metric fixtures for `hipaa_compliance`
  (synthetic SSNs/emails), `file_reference_validation` (distinctive fixture path) and
  `duplicity_by_features` back it up.
- **No fluent API:** assert a 10-metric batch produces exactly 10 runs plus 1 parent, and
  no run outside the expected experiment — a stray `mlflow.log_metric` shows up at once.
  Cheaper still, a grep test that `aidrin/telemetry/` contains no `mlflow.log_`.
- **Exception text never escapes:** force a metric to fail and assert no span attribute,
  tag, or param contains the exception message.
- **`AIDRIN_MLFLOW_LOG_DATA_DETAILS` defaults off:** column names absent, paths hashed.
- **Non-finite:** a constant-column CSV through skewness/kurtosis; assert the key is skipped
  and noted, not logged as 0.
- **Sink failure:** a sink raising on every call; assert results are unchanged and nothing
  propagates.
- **CI:** add `[mlflow]` to the extras matrix at `.github/workflows/tests.yml:23`.

## Phases

**Phase 1 — Tracing.** A1, A2, A3. Self-contained, fixes a live bug, no MLflow dependency.
Ships alone.

**Phase 2 — MLflow.** B1-B7. Depends on the A1 package and the A2 seam.

## Risks

| Risk | Mitigation |
|---|---|
| `run_metric` is on every surface's hot path, and its fast-path and custom-metric branches have **no existing test coverage** | Write round-trip tests for both branches first (A2 prerequisite); only then consolidate. The consolidation is byte-for-byte equivalent, but nothing in the suite would currently prove it |
| Redaction allowlist drifts as metrics are added | Unknown metrics log no body by default; the PHI fixture test fails loudly |
| A tracking server outage degrades the tool | Blanket exception guard, low HTTP timeout, async logging |
| `mlflow-skinny` version drift reintroduces the thread-local issue | Floor pinned at `>=2.18`; logging goes through `MlflowClient`, which is unaffected either way |
