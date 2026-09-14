# Intent-Based Metric Recommendation — Design

Date: 2026-09-08
Status: Revised after domain and technical review

## Problem

AIDRIN exposes 29 metrics across six pillars. After loading a dataset, a user faces a sidebar of
pillars and panels with no guidance about which checks matter for what they are actually trying to
do. Someone preparing training data cares about class imbalance and leakage; someone about to
publish a dataset cares about re-identification and FAIR metadata; someone who just took an
instrument run cares whether the ingest worked at all. Today all three see the same undifferentiated
menu and have to know the field well enough to choose.

This feature asks the user what they plan to do with the dataset and answers with a prioritised,
explained list of which metrics to check.

## Scope

**In scope:** the Flask web inspector, and a recommendation engine in `aidrin/intent.py`.

**Out of scope for this iteration:** the `aidrin` CLI, the MCP server, and the headless API.
`aidrin/intent.py` is designed so those surfaces can consume it later without rework, but no CLI
subcommand or MCP tool is built now.

**Explicitly not a goal:** running metrics. This feature computes no metric, dispatches no Celery
task, and produces no scores. It is advisory only. Its entire output is a list of what the user
should check and why, with links to the panels where they can check it.

**In scope by necessity:** this feature introduces `session["intent"]` and a cache entry, so it owns
resetting them. Three existing reset paths in `web/routes/core.py` gain a `session.pop("intent")`.
That is cleaning up state this feature creates, not unrelated refactoring.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Recommendation engine | Hybrid: curated map + LLM extras | A hand-written map guarantees a sane baseline and is unit-testable without a network. The LLM adds intent-specific extras a static map cannot anticipate from free text. |
| Intent input | Multi-select presets + free text | A dataset is realistically for training *and* publishing. Presets anchor the user; free text catches what presets miss. |
| Parameter input | None | The user supplies no column names or metric arguments. The panel the card links to already collects whatever it needs, and asking an LLM to propose column names is the least reliable part of the pipeline. |
| Card actionability | Jump only | Cards link to the relevant panel. No pre-checking, no pre-filling, no running. |
| **Availability** | **Curated map for everyone; LLM is an enhancement** | The deterministic half needs no network and no key, and it is the more trustworthy half. Hiding it behind an optional dependency would leave default installs with no guidance at all. |
| Surface | Web UI only | Ships one surface well rather than three thinly. |
| Entry point | Auto modal after dataset load | Highest capture rate at the moment the question is most relevant. Dismissal is remembered for the session. |
| **Timestamp detection** | **None — always offer `temporal_completeness`** | Detection is unreliable at the source (see "Rejected: datetime detection"). A card the user cannot act on costs a glance; the alternative costs a change to shared CSV parsing. |

### Rejected: datetime detection

An earlier draft filtered `temporal_completeness` on whether the dataset had a datetime column.
This cannot be done reliably without changing shared code:

- `/summary-statistics` classifies columns as numeric-non-bool or string-or-bool
  (`web/routes/core.py:519-527`); `all_features` is their concatenation, so a `datetime64` column
  appears in **neither** list and the cached payload carries no datetime signal.
- Reading the frame directly does not help either: `csv_reader.py:8` is
  `pd.read_csv(path, index_col=False)` with no `parse_dates`, so a CSV timestamp column arrives as
  `object` dtype and is already counted as *categorical*. A dtype check would return `False` for
  essentially every CSV — silently withholding the timestamp check from precisely the users who
  have a timestamp column.

Adding `parse_dates` to the CSV reader would fix it properly but would change a column that is text
today into a date, shifting behaviour in existing metrics and tests. That risk is not worth carrying
for an advisory feature. **`temporal_completeness` is therefore always offered when an intent calls
for it**, and the applicability filter has no datetime rule.

## Architecture

The gate decision splits the feature across two blueprints: the curated half is always registered,
the LLM half is imported lazily and only when available.

```
aidrin/intent.py                     the curated engine
  INTENTS                            7 preset intents (key, label, description)
  INTENT_PROFILES                    intent -> {critical: [...], recommended: [...]}
  METRIC_KEYS                        local key list; test asserts it matches METRIC_REGISTRY
  WEB_ONLY                           metrics in the web UI but not METRIC_REGISTRY
  DISPLAY_NAMES                      metric key -> human-readable label
  PANEL_BY_METRIC                    metric key -> panel id
  APPLICABILITY                      metric -> required column kinds
  recommend_metrics(intents, profile) -> list[dict]

web/routes/intent.py                 ALWAYS registered
  POST /intent/recommend             curated always; LLM enhancement when available
  POST /intent/dismiss

web/llm.py                           optional enhancement layer
  RECOMMEND_SYSTEM_PROMPT
  recommend_for_intent(...)          -> {"summary", "rationales", "extras"} | None
  parse_recommendation(text)         -> dict | None   (importable without openai)

web/templates/_components/intent_modal.html
web/templates/_panels/_intent.html
web/templates/_components/sidebar.html            (one new entry)
web/templates/inspector.html                      (two includes)
web/routes/core.py                                (session.pop("intent") x3)
web/static/js/inspector.js                        (modal + card rendering)
```

`web/routes/intent.py` is registered unconditionally in `web/routes/__init__.py`, alongside `core`
and `metrics`. It imports `web.llm` **lazily inside the handler**, guarded by `is_llm_available()`,
so the module never hard-depends on `openai`.

### `aidrin/intent.py` does not import `METRIC_REGISTRY`

An earlier draft claimed this module would be "pure — no Flask, no LLM". That was false. Importing
`aidrin.headless.api` executes `aidrin/headless/__init__.py`, which imports `.api`, which pulls in
pandas, numpy, celery, matplotlib, seaborn, dython, sklearn — and **Flask**, via
`aidrin/file_handling/readers/hdf5_reader.py:7` and `json_reader.py:6`. It is one of the heaviest
imports in the repo.

So `intent.py` declares its own `METRIC_KEYS` list and does **not** import the registry at module
scope. Drift is caught in the test instead:

```python
def test_metric_keys_match_registry():
    from aidrin.headless.api import METRIC_REGISTRY
    assert set(intent.METRIC_KEYS) == set(METRIC_REGISTRY)
```

The module stays genuinely importable in isolation, and a metric added to the registry without a
corresponding intent entry still fails CI.

## Component: the intent taxonomy

Seven presets. `fine_tuning` is merged into `training`: as separate entries their profiles differed
only in which of the same metrics was critical, which does not meet the bar for a distinct choice a
user has to parse. The memorisation concerns specific to fine-tuning (near-duplicates memorised
verbatim, personal data becoming extractable from the trained model) are folded in as critical
entries on the merged profile.

| Key | Label |
|---|---|
| `training` | Training or fine-tuning a model |
| `inference` | Inference or serving |
| `agentic` | Agentic use or RAG |
| `publishing` | Publishing, sharing, or archiving |
| `benchmarking` | Benchmarking or evaluation |
| `curation` | Curating or QC-ing newly collected data |
| `exploration` | Exploratory or statistical analysis |

`curation` is the one addition. Every other intent presumes the dataset is *finished* and asks "is
it good enough to consume?" `curation` asks "did the collection or ingest actually work?" — a
schema-contract question. Given the Globus integration and the datacard generator, a large share of
AIDRIN users touch a dataset before anyone has decided what model it is for.

The user selects zero or more and may add free text. Zero intents with free text is valid: the
curated baseline is empty and the LLM supplies everything, each entry marked AI-suggested. Zero
intents with no free text is rejected.

## Component: the curated map

Every key is present in `METRIC_KEYS` or `WEB_ONLY`, enforced by a unit test rather than by review.

| Intent | Critical | Recommended |
|---|---|---|
| `training` | completeness, duplicity, duplicity_by_features, class_imbalance, max_pairwise_correlation, hipaa_compliance | outliers, correlations, feature_relevance, constant_feature_count, skewness, representation_rate, file_reference_validation |
| `inference` | completeness, row_level_completeness, feature_coverage_ratio, constant_feature_count, outliers_custom | outliers, duplicity, null_count_trend, temporal_completeness, hipaa_compliance |
| `agentic` | completeness, duplicity, duplicity_by_features, hipaa_compliance, file_reference_validation, outliers_custom | feature_coverage_ratio, k_anonymity, row_level_completeness |
| `publishing` | hipaa_compliance, k_anonymity, completeness, fair_assessment, file_reference_validation | l_diversity, t_closeness, entropy_risk, single_attribute_risk, multiple_attribute_risk, duplicity, constant_feature_count, representation_rate |
| `benchmarking` | duplicity, duplicity_by_features, class_imbalance, max_pairwise_correlation, completeness | representation_rate, statistical_rates, conditional_demographic_disparity, feature_relevance, outliers_custom |
| `curation` | completeness, row_level_completeness, constant_feature_count, duplicity, file_reference_validation | feature_coverage_ratio, outliers, outliers_custom, null_count_trend, temporal_completeness, duplicity_by_features |
| `exploration` | completeness, outliers, duplicity, max_pairwise_correlation | skewness, kurtosis, correlations, constant_feature_count, feature_coverage_ratio |

### Editorial decisions behind the table

These were corrected during domain review and are recorded so they are not silently undone:

- **`max_pairwise_correlation` is critical for `training` and `benchmarking`.** A feature at
  |r| ≈ 1.0 with the target is leakage, and leakage is the definition of a materially wrong result:
  99% validation accuracy on a worthless model. It is AIDRIN's cheapest leakage detector.
- **`duplicity_by_features` is critical wherever contamination matters.** Exact-row `duplicity`
  catches the easy case; what actually leaks is the same record with a different id or timestamp.
  For `benchmarking` this is *the* defining failure. For `agentic`, near-duplicate chunks are the
  classic RAG failure — retrieval returns five near-identical paragraphs and burns the context
  window.
- **`feature_relevance` is not critical for `training`.** It is a feature-selection convenience;
  skipping it degrades a model rather than invalidating it. It is more valuable for `benchmarking`
  (is all the signal in one feature?), where it now appears.
- **`agentic` does not use quasi-identifier privacy metrics.** `k_anonymity` and `entropy_risk`
  answer "can rows in an aggregate release be linked back to individuals," which is not the RAG
  leak. The RAG leak is a chunk of free text containing a name or an MRN being retrieved into a
  prompt — which `hipaa_compliance`'s regex scan already catches. `entropy_risk` is dropped;
  `k_anonymity` is demoted.
- **`outliers_custom` is critical for `inference`, `agentic`, and prominent in `curation`.** It is
  the only mechanism AIDRIN has for expressing a schema contract — valid ranges, allowed category
  values, regex on identifiers.
- **`skewness`/`kurtosis` are not in `inference`.** Distribution shape of a serving batch is only
  interpretable against a training-time reference, which AIDRIN does not compute or store.
- **`l_diversity` is demoted in `publishing`.** It is a refinement of k-anonymity and is meaningless
  until k-anonymity holds. Its rationale must say "after k-anonymity passes."
- **`differential_privacy` appears in no profile.** `run_differential_privacy` produces
  differentially private noise statistics for selected columns — a remediation utility, not an
  assessment of whether what you hold is safe to release. It does not answer any intent's question.
- **`file_reference_validation` is critical for `publishing` and `curation`.** The most common
  defect in a deposited scientific dataset is a manifest whose paths stop resolving once the data
  moves to an archive.

### Known limitations to state in card rationales

- `duplicity_by_features` is a **within-file** check. If the user holds train and test as two files
  — the normal case — AIDRIN cannot detect cross-file contamination at all. The `benchmarking` cards
  must say so rather than implying the check suffices.
- AIDRIN has no metric for chunk length, staleness, contradiction, or provenance. The `agentic`
  profile cannot fully deliver on the intent's promise, and the summary should say so rather than
  padding the list.
- Several critical metrics require the user to nominate columns or supply rules (`class_imbalance`,
  `statistical_rates`, `k_anonymity`, `row_level_completeness`, `temporal_completeness`,
  `outliers_custom`). Each rationale must name what the user has to bring, or the card is a dead end.

### Recommendable metrics

`METRIC_KEYS` is the 27 keys of `METRIC_REGISTRY` (`aidrin/headless/api.py:53`) plus `WEB_ONLY`:

| Key | Panel | Note |
|---|---|---|
| `fair_assessment` | `fair-assessment` | DCAT/Datacite metadata evaluation; requires a metadata upload |
| `conditional_demographic_disparity` | `fairness` | Present in `_fairness.html`, absent from `METRIC_REGISTRY` |

`WEB_ONLY` entries carry their own `category` and `description`, mirroring the registry's shape.

### Display names

`METRIC_REGISTRY` entries carry only `category`, `description`, `runner`, and `required_args` — no
human-readable label. `DISPLAY_NAMES` supplies one per key (`class_imbalance` → "Class Imbalance",
`hipaa_compliance` → "HIPAA Compliance", `k_anonymity` → "k-Anonymity"). A unit test asserts every
recommendable metric has an entry.

### Metric-to-panel mapping

`PANEL_BY_METRIC`, verified against the checkbox `name` attributes in `web/templates/_panels/`:

| Panel | Metrics |
|---|---|
| `data-quality` | completeness, row_level_completeness, feature_coverage_ratio, temporal_completeness, null_count_trend, outliers, outliers_custom, duplicity, duplicity_by_features |
| `data-structure` | constant_feature_count, max_pairwise_correlation, skewness, kurtosis, file_reference_validation |
| `correlation-analysis` | correlations |
| `feature-relevance` | feature_relevance |
| `class-imbalance` | class_imbalance |
| `fairness` | statistical_rates, representation_rate, conditional_demographic_disparity |
| `privacy-preservation` | k_anonymity, l_diversity, t_closeness, entropy_risk, single_attribute_risk, multiple_attribute_risk, differential_privacy |
| `hipaa-compliance` | hipaa_compliance |
| `fair-assessment` | fair_assessment |

Note `file_reference_validation` has registry category `data-quality` but lives in the
`data-structure` panel. **Cards are therefore grouped by panel, not by category**, so a card never
sits under a heading that disagrees with where its link goes.

## Component: the applicability filter

A recommendation the dataset cannot support is noise. Each candidate is tested against the profile:

| Requirement | Metrics |
|---|---|
| at least one categorical column | class_imbalance, statistical_rates, representation_rate, conditional_demographic_disparity, k_anonymity, l_diversity, t_closeness, entropy_risk, hipaa_compliance, single_attribute_risk, multiple_attribute_risk |
| at least one numerical column | skewness, kurtosis, feature_relevance |
| at least two columns | correlations, max_pairwise_correlation |
| at least one string column | file_reference_validation |

Metrics with no entry are always applicable — including `temporal_completeness`, per the decision
above. **When the profile is empty or unavailable (see Globus mode below), no filtering occurs**:
the filter fails open in every uncertain case.

`fair_assessment` has no column requirement but does require a metadata upload the user may not
have; its rationale states this, matching how the Readiness Report already labels that section
optional.

## Component: the dataset profile

The profile grounds the LLM's rationale. It is never used to propose column names to the user, and
the curated recommendation works without it.

```python
{
  "rows": 48842,
  "columns": 15,
  "numerical": ["age", "fnlwgt", ...],     # capped at 50, plus a count
  "categorical": ["workclass", ...],       # capped at 50, plus a count
  "columns_with_nulls": 6,                 # best-effort; None when underivable
}
```

### Source and cache key

Built from the `summarystats` entry already in `current_app.TEMP_RESULTS_CACHE` — warm, because
`initWorkspace()` fetches `/summary-statistics` on load.

The key uses a **different convention** from the colon-separated one at `web/routes/utils.py:246`.
`/summary-statistics` (`core.py:467`) calls `generate_metric_cache_key(file_name, "summarystats",
selected_keys=selected)`, which produces a **pipe-separated** key
(`utils.py:193-197`). The new route must reproduce the HDF5 branch at `core.py:461-465` verbatim —
read `session["selected_keys"]`, handle the string-vs-list form, sort — or the lookup misses 100% of
the time on HDF5 and falls through.

`columns_with_nulls` is **not** in the payload. It is derived as `records_count` minus each column's
`count` from `summary_statistics` (numerics) and `categorical_summary` (categoricals). It is `None`
when `summary_statistics` is `{}` (no numeric columns, `core.py:507-508`), and the LLM prompt simply
omits the line in that case.

### On a cache miss: degrade, do not read

An earlier draft fell back to `load_dataframe`. That materialises the whole file
(`file_parser.py:217`) with `MAX_CONTENT_LENGTH` defaulting to **1 GB** (`web/__init__.py:75-79`),
synchronously inside the request fired right after the modal is submitted — and it triggers exactly
on the 30-minute-expiry path, i.e. when a user returns to the tab later. A multi-second-to-minute
blocking read for a feature that "runs no metrics" is not acceptable.

**On a cache miss the profile is `None`.** The curated recommendation is unaffected; the LLM is
called with intents and free text only; the applicability filter fails open. No file is read.

### Globus mode

In Globus mode `session["uploaded_file_path"]` is empty, `/summary-statistics` is never called, and
the Globus summary lives under a third key shape, `globus_summary:{endpoint_id}:{file_path}`
(`web/routes/globus.py:135`), which does not start with `user:`. The `load_dataframe` fallback is
impossible — the file is on a remote endpoint.

**Globus mode therefore uses `profile = None`**, exactly as the cache-miss path. Recommendations are
curated plus whatever the LLM infers from intents and free text alone. Reading the Globus summary
cache is a possible later refinement, not a requirement.

## Component: the LLM enhancement

`recommend_for_intent(intents, notes, profile, baseline, config)` makes a single text-only call. No
image, no vision fallback. `max_tokens=3000`: `training` + `publishing` unions to roughly 19
baseline metrics, and 19 rationales plus a summary plus extras will truncate at 2000, dropping the
whole response to the fallback more often than intended.

The prompt supplies the recommendable catalog (key, category, description), the profile, the
selected intents, the free text, and the baseline keys. Column name lists are capped at 50 per kind
with a count, so a wide dataset cannot produce an unbounded, user-controlled prompt.

```json
{
  "summary": "one or two sentences addressed to the user",
  "rationales": {"completeness": "why this matters for this dataset and intent"},
  "extras": [{"metric": "k_anonymity", "why": "..."}]
}
```

`parse_recommendation` is lenient — strips ``` fences, locates the outermost JSON object — because
the endpoint is any OpenAI-compatible API and `response_format` is not universally supported. It is
a module-level function with no `openai` dependency, so it is unit-testable without the extra.

Validation is strict: keys not in the recommendable set are dropped; extras already in the baseline
are dropped; extras are capped at 5 and re-filtered through the applicability filter; every string
is truncated to 400 characters; anything that raises returns `None`.

Note `web/llm.py:95` already uses `max_tokens`, which newer OpenAI models reject in favour of
`max_completion_tokens`. The new call inherits this pre-existing issue; it is not fixed here.

### Degradation

`recommend_for_intent` returns `None` on a missing config, an API error, a malformed response, or a
response that validates to nothing. It is not called at all when `openai` is absent or no key is
configured. In every such case the route returns the curated list with each metric's `description`
from the registry as its rationale, and `llm_used: false`.

## Component: routes

`web/routes/intent.py`, registered unconditionally.

### `POST /intent/recommend`

Request: `{"intents": ["training", "publishing"], "notes": "credit-risk model for EU deployment"}`

Rejects a request with neither intents nor notes as 400. Does **not** require an LLM key.

Response:

```json
{
  "intents": ["training", "publishing"],
  "summary": "...",
  "llm_used": true,
  "model": "gpt-4o-mini",
  "recommendations": [
    {
      "metric": "class_imbalance",
      "display_name": "Class Imbalance",
      "panel": "class-imbalance",
      "priority": "critical",
      "source": "curated",
      "reason_intents": ["training"],
      "why": "..."
    }
  ]
}
```

**Ordering:** critical first, then by `len(reason_intents)` descending, then by panel. The secondary
sort matters — `training` + `publishing` + `benchmarking` is an ordinary selection that unions to
roughly a dozen criticals, at which point the badge stops meaning anything. Floating the metrics
that several intents agree on keeps the top of the list useful. The UI collapses criticals beyond
the first six into an "also critical" list.

Stores intent in `session["intent"]` and the response in `TEMP_RESULTS_CACHE` under
`user:{user_id}:file:{file_name}:intent`, readable through the existing
`/cached-result/intent` route with no backend change (`core.py:429` builds the key generically).

**`notes` is truncated to 500 characters before being stored in the session.** The Flask session is
a plain signed cookie (`web/__init__.py:49`, no server-side backend) with a ~4 KB budget that the
free-text field could otherwise blow.

### `POST /intent/dismiss`

Body `{}`. Records that the user skipped the modal so it does not reopen on every panel change.
Returns `{"success": true}`.

### Reset paths in `web/routes/core.py`

Three transitions currently leave intent state stale. Each gains `session.pop("intent", None)`:

| Path | Current behaviour | Consequence without the fix |
|---|---|---|
| `POST /inspector` new upload (`core.py:54-58`) | clears user cache, pops `selected_keys` only | modal never reopens; panel empty because its cache entry was wiped |
| `/clear-dataset-selection` (`core.py:310-351`) | clears user cache | same, on an HDF5 dataset switch |
| `/filter-file` (`core.py:250-307`) | clears nothing | **worst:** the `…:intent` entry survives and has no `selected_keys` component, so the panel restores recommendations computed for a different set of columns. `/cached-result` does not check `is_metric_cache_valid` (`core.py:428-434`), so there is no TTL rescue |

`/clear` (`core.py:211-247`) already calls `session.clear()` and needs no change.

## Component: UI

### Modal

`web/templates/_components/intent_modal.html`, included from `inspector.html` whenever
`uploaded_file_path` is set. **No LLM condition.** This follows from the availability decision and
resolves a bug the earlier gate created: `saveLLMSettings()` (`inspector.js:7365`) sets
`window.AIDRIN_LLM_ENABLED = true` without a reload, so a user who uploaded a file and *then*
configured a key would have had no modal element in the DOM and no way to reach the feature until
they reloaded. With the modal ungated, that path disappears.

Contents: seven intent checkboxes, a free-text "Anything else we should know?" field, `[Skip]` and
`[Get recommendations]`. The submit button is disabled until a checkbox is ticked or the text field
is non-empty.

### Modal trigger

Opened from the point where the dataset summary is genuinely ready, in both modes:

- **Normal mode:** the `if (data.success)` branch of `loadDataOverview` (`inspector.js:4596-4699`).
  Its sibling `else if (data.needs_dataset_selection)` branch (`:4700`) renders the HDF5 picker
  instead, so hooking the success branch naturally excludes the picker state — the modal does not
  appear until the user has chosen datasets and `initWorkspace()` re-runs.
- **Globus mode:** `renderGlobusSummary` (`:1624`), placed *after* the `if (data.error)` early
  return at `:1629-1635`. Not `fetchGlobusSummary`, which either short-circuits on a cached result
  or hands off to `pollGlobusSummary` up to ~4 minutes later — hooking it would open the modal over
  the loading spinner.

`window.AIDRIN_INTENT_ASKED` is a page-load Jinja constant, so `submitIntent()` and `skipIntent()`
must also set it locally. On a dataset switch the server drops `session["intent"]` (above) and
`initWorkspace()` re-runs, so the modal correctly reopens for the new dataset.

### Panel

`web/templates/_panels/_intent.html`, id `panel-intent`, plus a sidebar entry "Intent &
Recommendations" above Readiness Report. Both are **unconditional**, matching the modal — there is
no configuration under which they lead to a dead panel.

Contents: the summary line, panel-grouped cards ordered as above, and a collapsed "Change intent"
form duplicating the modal's fields.

Card: display name, panel name, priority badge, an "AI-suggested" badge when `source` is `ai`, the
`reason_intents` line, the rationale, and a link calling `showPanel(panel)`.

### JavaScript

In `web/static/js/inspector.js`:

- `maybeShowIntentModal()` — called from the two trigger points above
- `submitIntent()` — POSTs to `/intent/recommend`, renders, then `showPanel('intent')`
- `skipIntent()` — POSTs to `/intent/dismiss`, closes the modal
- `renderIntentRecommendations(data)` — builds the cards
- `_restoreIntentFromCache()` — called from `showPanel`

**Do not add `intent` to `_panelCacheMap`** (`inspector.js:456-465`). That map routes a cached
payload into `renderWorkspaceResults(resp.data, ...)` at `:492`, which expects metric-result shape.
The intent restore needs its own branch. The map's own comment already carves out non-metric panels.

**Insertion points are constrained by existing tests.** `tests/unit/test_inspector_js_security.py`
slices the file by source markers: `"function escapeHtml(str)"` → `"\n\n// ==== FAIR Assessment"`,
and `"function renderCategoricalPieCharts"` → `"\nfunction renderHdf5DatasetPicker"`. New functions
must not land inside those windows. Adding a call inside `initWorkspace` is safe.

### XSS

All LLM-authored text (`summary`, `why`) passes through `escapeHtml` (`inspector.js:3422`) before
insertion, matching `_renderLLMCallout`.

The existing security test asserts a **hardcoded fragment list**, so new unescaped code would pass
it silently. This feature must add explicit fragments to that list: the required
`${escapeHtml(rec.why)}` and `${escapeHtml(data.summary)}` forms, and the forbidden bare `${rec.why}`
and `${data.summary}` forms.

`escapeHtml` is HTML-context only and does not neutralise a `javascript:` URL or an event-handler
body. The jump control is `onclick="showPanel('${panel}')"` where `panel` comes from the server-side
`PANEL_BY_METRIC` — a fixed vocabulary, never LLM output. This holds only as long as `extras[].metric`
validation against the recommendable set stays strict.

## Testing

### `tests/unit/test_intent.py`

- `METRIC_KEYS` equals `set(METRIC_REGISTRY)` (the drift guard replacing the module-scope import)
- every metric key in every profile is in `METRIC_KEYS` or `WEB_ONLY`
- every recommendable metric has a `PANEL_BY_METRIC` entry and a `DISPLAY_NAMES` entry
- every `WEB_ONLY` entry has `category` and `description`
- single intent returns its critical and recommended sets
- multiple intents union, and priority merges by maximum
- `reason_intents` lists every selected intent that requested the metric
- ordering: critical first, then by `len(reason_intents)` descending
- `temporal_completeness` is never filtered out
- applicability drops `correlations` on a single-column profile
- **a `None` profile disables filtering entirely** (cache-miss and Globus paths)
- an unknown intent key is ignored rather than raising
- empty intents return an empty list

### `tests/unit/test_intent_llm_parsing.py`

- bare JSON, fenced JSON, and JSON with surrounding prose all parse
- unknown metric keys in `rationales` and `extras` are dropped
- extras already in the baseline are dropped; extras capped at 5
- over-long strings truncated
- malformed JSON returns `None`

Imports `parse_recommendation` from `web.llm` without requiring `openai`.

### `tests/integration/test_intent_routes.py`

CI note: `.github/workflows/tests.yml` has **no `[llm]` matrix row** — `openai` arrives only via the
`[agentic]` and `[mcp]` include entries, so the LLM path exercises in 2 of ~15 jobs. Because
`/intent/recommend` is now always registered, the curated path tests run in **every** job, which is
the main reason the gate change improves testability.

- 200 without any LLM configured, returning the curated list with `llm_used: false` and registry
  descriptions as rationales
- 400 with neither intents nor notes
- happy path with `recommend_for_intent` monkeypatched: response shape, ordering, `source` labelling
- LLM failure: monkeypatched to return `None` → curated list, `llm_used: false`
- result is cached; a second call does not re-invoke the LLM
- `notes` longer than 500 characters is truncated in the session
- HDF5: the cache key includes `selected_keys` and a lookup with different selected keys misses
- each of the three reset paths clears `session["intent"]`

LLM-dependent assertions use `pytest.mark.skipif`, not a bare `return`, so the report shows
*skipped* rather than a silent pass.

## Risks

**Advice quality.** The curated map is an opinion, documented in one table in one file. Unit tests
pin its structure, not its editorial content.

**Prompt injection via column names.** Column names from an untrusted dataset reach the prompt. The
response is validated against a fixed key set and every rendered string is escaped, so the worst
case is misleading advice text.

**Modal fatigue.** An auto-opening modal interrupts users who want to explore. Mitigated by Skip
being remembered for the session.

**Registry drift.** A metric added to `METRIC_REGISTRY` without `METRIC_KEYS`, `PANEL_BY_METRIC`, and
`DISPLAY_NAMES` entries fails a unit test. A metric added to the web UI but not the registry stays
invisible until someone adds it to `WEB_ONLY`; accepted.

**Unfillable timestamp cards.** Per the decision above, `temporal_completeness` is offered to
`inference` and `curation` users regardless of whether the dataset has a timestamp column. Its
rationale must state that a timestamp column and a frequency are required.

**Synchronous LLM call.** The enhancement runs inside a Flask request thread. Unlike the metric
panels, there is no Celery path. A slow endpoint blocks one worker for the duration; the curated
result is what the user gets if it fails.
