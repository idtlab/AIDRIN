# Intent-Based Metric Recommendation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a dataset loads in the AIDRIN web inspector, ask the user what they plan to do with it and answer with a prioritised, explained list of which metrics they should check.

**Architecture:** A pure-Python curated map (`aidrin/intent.py`) turns selected intents into a prioritised metric list. An always-registered Flask blueprint (`web/routes/intent.py`) serves it. When the optional `openai` package is installed and a key is configured, `web/llm.py` enhances the result with dataset-specific rationales and up to five extra suggestions. Nothing is ever computed or run — the output is advice plus links to existing panels.

**Tech Stack:** Python 3.10-3.13, Flask, pytest, vanilla JS + Tailwind (no build step), Jinja templates.

**Spec:** `docs/superpowers/specs/2026-09-08-intent-metric-recommendation-design.md`

## Global Constraints

- **Do not commit or push.** The user has explicitly instructed this for the current session. Each task ends with a `git add` step only; the `git commit` line is written out but must NOT be run until the user authorises it. When authorised, branch off `develop` first (AGENTS.md: default branch is `develop`, branch off it, target PRs at it).
- **No AI attribution in commit messages.** No "Generated with...", no co-author trailers, no robot emoji. Plain, human, present-tense subject. Avoid em dashes in commit messages and user-facing copy.
- `PYTHONPATH=.` is required for every pytest invocation.
- flake8 max line length is **150** (`tox.ini`). Applies to `aidrin/` and `web/`, not templates or static.
- Prettier must pass on any touched JS/CSS: `npx --yes prettier@3 --check web/static/css web/static/js`. Run `prettier --write` but only let it touch lines you changed.
- **This feature runs no metrics.** No Celery task, no `read_file`, no `load_dataframe`. If a task tempts you to read the dataset, you have misread the spec.
- Metric keys are the canonical identifiers everywhere. Never invent one; the full valid set is `METRIC_KEYS | set(WEB_ONLY)` from Task 1.
- All LLM-authored text reaching the DOM must pass through `escapeHtml`.

---

## File Structure

| File | Responsibility |
|---|---|
| `aidrin/intent.py` (create) | The catalog: intents, metric keys, display names, panel map, profiles, applicability, `recommend_metrics()`. No Flask, no LLM, no I/O. |
| `tests/unit/test_intent.py` (create) | Structural drift guards + `recommend_metrics()` behaviour. |
| `web/llm.py` (modify) | Adds `parse_recommendation()` (pure) and `recommend_for_intent()` (needs `openai`). |
| `tests/unit/test_intent_llm_parsing.py` (create) | `parse_recommendation()` only. Must not require `openai`. |
| `web/routes/intent.py` (create) | `POST /intent/recommend`, `POST /intent/dismiss`, profile builder, LLM merge. |
| `web/routes/__init__.py` (modify) | Register `intent_bp` unconditionally. |
| `web/routes/core.py` (modify) | Three `session.pop("intent", None)` calls. |
| `tests/integration/test_intent_routes.py` (create) | Route behaviour, caching, session reset. |
| `web/templates/_components/intent_modal.html` (create) | The auto-opening question. |
| `web/templates/_panels/_intent.html` (create) | Where results live. |
| `web/templates/_components/sidebar.html` (modify) | One nav entry. |
| `web/templates/inspector.html` (modify) | Two includes + one JS flag. |
| `web/static/js/inspector.js` (modify) | Modal control, submit, render, restore, two trigger points. |
| `tests/unit/test_inspector_js_security.py` (modify) | XSS fragment assertions for the new renderer. |

---

## Task 1: The intent catalog

**Files:**
- Create: `aidrin/intent.py`
- Test: `tests/unit/test_intent.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `INTENTS` (list of dicts with `key`/`label`/`description`), `INTENT_KEYS` (set), `METRIC_KEYS` (set), `WEB_ONLY` (dict), `DISPLAY_NAMES` (dict), `PANEL_BY_METRIC` (dict), `INTENT_PROFILES` (dict), `APPLICABILITY` (dict), `DESCRIPTIONS` (dict), `all_metric_keys()` -> set.

- [ ] **Step 1: Write the failing structural tests**

Create `tests/unit/test_intent.py`:

```python
"""Structural guards for the intent catalog.

These tests are the reason aidrin/intent.py does not import METRIC_REGISTRY
at module scope: importing aidrin.headless.api pulls in pandas, celery,
matplotlib, sklearn and Flask (via the HDF5/JSON readers). The drift guard
lives here instead, where the heavy import is acceptable.
"""

from aidrin import intent


def test_metric_keys_match_registry():
    """METRIC_KEYS must stay in step with the real registry."""
    from aidrin.headless.api import METRIC_REGISTRY

    assert intent.METRIC_KEYS == set(METRIC_REGISTRY)


def test_web_only_metrics_are_disjoint_from_registry():
    assert intent.METRIC_KEYS.isdisjoint(intent.WEB_ONLY)


def test_web_only_entries_carry_category_and_description():
    for key, meta in intent.WEB_ONLY.items():
        assert meta.get("category"), key
        assert meta.get("description"), key


def test_every_recommendable_metric_has_a_panel():
    assert set(intent.PANEL_BY_METRIC) == intent.all_metric_keys()


def test_every_recommendable_metric_has_a_display_name():
    assert set(intent.DISPLAY_NAMES) == intent.all_metric_keys()


def test_every_recommendable_metric_has_a_description():
    assert set(intent.DESCRIPTIONS) == intent.all_metric_keys()


def test_profile_keys_are_all_recommendable():
    valid = intent.all_metric_keys()
    for key, profile in intent.INTENT_PROFILES.items():
        for tier in ("critical", "recommended"):
            unknown = set(profile[tier]) - valid
            assert not unknown, f"{key}.{tier} has unknown metrics: {unknown}"


def test_no_metric_is_both_critical_and_recommended_for_one_intent():
    for key, profile in intent.INTENT_PROFILES.items():
        overlap = set(profile["critical"]) & set(profile["recommended"])
        assert not overlap, f"{key} lists {overlap} in both tiers"


def test_intents_and_profiles_cover_the_same_keys():
    assert {i["key"] for i in intent.INTENTS} == set(intent.INTENT_PROFILES)
    assert intent.INTENT_KEYS == set(intent.INTENT_PROFILES)


def test_there_are_seven_intents():
    assert len(intent.INTENTS) == 7


def test_every_intent_has_a_label_and_description():
    for entry in intent.INTENTS:
        assert entry["key"] and entry["label"] and entry["description"]


def test_every_panel_in_the_map_has_a_label():
    assert set(intent.PANEL_BY_METRIC.values()) <= set(intent.PANEL_LABELS)


def test_caveat_keys_are_recommendable():
    assert set(intent.CAVEATS) <= intent.all_metric_keys()


def test_metrics_needing_user_input_all_carry_a_caveat():
    """A critical card that leads to an unfillable panel is worse than no card."""
    needs_input = {
        "row_level_completeness",
        "temporal_completeness",
        "null_count_trend",
        "outliers_custom",
        "file_reference_validation",
        "class_imbalance",
        "feature_relevance",
        "statistical_rates",
        "k_anonymity",
        "l_diversity",
        "t_closeness",
        "entropy_risk",
        "single_attribute_risk",
        "multiple_attribute_risk",
    }
    assert needs_input <= set(intent.CAVEATS)


def test_applicability_requirements_are_known_kinds():
    assert set(intent.APPLICABILITY.values()) <= {
        "categorical",
        "numerical",
        "string",
        "two_columns",
    }


def test_applicability_keys_are_recommendable():
    assert set(intent.APPLICABILITY) <= intent.all_metric_keys()


def test_temporal_completeness_has_no_applicability_rule():
    """Spec decision: timestamp detection is unreliable, so never filter it."""
    assert "temporal_completeness" not in intent.APPLICABILITY


def test_differential_privacy_is_in_no_profile():
    """It is a remediation utility, not an assessment. Deliberately unused."""
    for profile in intent.INTENT_PROFILES.values():
        assert "differential_privacy" not in profile["critical"]
        assert "differential_privacy" not in profile["recommended"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/test_intent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aidrin.intent'`

- [ ] **Step 3: Write the catalog**

Create `aidrin/intent.py`:

```python
"""Intent-based metric recommendation.

Maps what a user plans to do with a dataset onto the AIDRIN metrics they
should check. Pure data plus one function: no Flask, no LLM, no file I/O.

This module deliberately does NOT import METRIC_REGISTRY. Importing
aidrin.headless.api executes aidrin/headless/__init__.py, which pulls in
pandas, numpy, celery, matplotlib, seaborn, dython, sklearn and Flask (the
last via aidrin/file_handling/readers/hdf5_reader.py). METRIC_KEYS below is
checked against the real registry in tests/unit/test_intent.py instead, so
drift is still caught without making this module expensive to import.
"""

from typing import Any, Dict, List, Optional, Set

CRITICAL = "critical"
RECOMMENDED = "recommended"

# Priority ordering, highest first. Used when several intents disagree.
_PRIORITY_RANK = {CRITICAL: 0, RECOMMENDED: 1}


INTENTS: List[Dict[str, str]] = [
    {
        "key": "training",
        "label": "Training or fine-tuning a model",
        "description": "Building or adapting a model using this data.",
    },
    {
        "key": "inference",
        "label": "Inference or serving",
        "description": "Scoring new records with a model that already exists.",
    },
    {
        "key": "agentic",
        "label": "Agentic use or RAG",
        "description": "Retrieval, tool use, or feeding this data into an LLM's context.",
    },
    {
        "key": "publishing",
        "label": "Publishing, sharing, or archiving",
        "description": "Releasing this dataset to others or depositing it in a repository.",
    },
    {
        "key": "benchmarking",
        "label": "Benchmarking or evaluation",
        "description": "Using this data to measure how well models perform.",
    },
    {
        "key": "curation",
        "label": "Curating or QC-ing newly collected data",
        "description": "Checking that a fresh collection or delivery is structurally sound.",
    },
    {
        "key": "exploration",
        "label": "Exploratory or statistical analysis",
        "description": "Understanding the data or fitting a statistical model.",
    },
]

INTENT_KEYS: Set[str] = {entry["key"] for entry in INTENTS}


# Mirrors aidrin.headless.api.METRIC_REGISTRY. Guarded by
# tests/unit/test_intent.py::test_metric_keys_match_registry.
METRIC_KEYS: Set[str] = {
    "completeness",
    "duplicity",
    "outliers",
    "constant_feature_count",
    "max_pairwise_correlation",
    "skewness",
    "kurtosis",
    "row_level_completeness",
    "duplicity_by_features",
    "feature_coverage_ratio",
    "temporal_completeness",
    "null_count_trend",
    "outliers_custom",
    "file_reference_validation",
    "correlations",
    "feature_relevance",
    "class_imbalance",
    "statistical_rates",
    "representation_rate",
    "k_anonymity",
    "l_diversity",
    "t_closeness",
    "entropy_risk",
    "single_attribute_risk",
    "multiple_attribute_risk",
    "differential_privacy",
    "hipaa_compliance",
}

# Exposed by the web UI but absent from METRIC_REGISTRY.
WEB_ONLY: Dict[str, Dict[str, str]] = {
    "fair_assessment": {
        "category": "understandability",
        "description": (
            "Evaluates DCAT or Datacite metadata against the FAIR principles. "
            "Requires uploading a JSON metadata file."
        ),
    },
    "conditional_demographic_disparity": {
        "category": "fairness-and-bias",
        "description": "Disparity in outcomes across groups, conditioned on a target value.",
    },
}


def all_metric_keys() -> Set[str]:
    """Every metric this module may recommend."""
    return METRIC_KEYS | set(WEB_ONLY)


DISPLAY_NAMES: Dict[str, str] = {
    "completeness": "Completeness",
    "duplicity": "Duplicity",
    "outliers": "Outliers",
    "constant_feature_count": "Constant Feature Count",
    "max_pairwise_correlation": "Max Pairwise Correlation",
    "skewness": "Skewness",
    "kurtosis": "Kurtosis",
    "row_level_completeness": "Row-Level Completeness",
    "duplicity_by_features": "Duplicates by Selected Features",
    "feature_coverage_ratio": "Feature Coverage Ratio",
    "temporal_completeness": "Temporal Completeness",
    "null_count_trend": "Null Count Trend",
    "outliers_custom": "Outliers with Custom Criteria",
    "file_reference_validation": "File Reference Validation",
    "correlations": "Correlation Analysis",
    "feature_relevance": "Feature Relevance",
    "class_imbalance": "Class Imbalance",
    "statistical_rates": "Statistical Rates",
    "representation_rate": "Representation Rate",
    "k_anonymity": "k-Anonymity",
    "l_diversity": "l-Diversity",
    "t_closeness": "t-Closeness",
    "entropy_risk": "Entropy Risk",
    "single_attribute_risk": "Single Attribute Risk",
    "multiple_attribute_risk": "Multiple Attribute Risk",
    "differential_privacy": "Differential Privacy",
    "hipaa_compliance": "HIPAA Compliance",
    "fair_assessment": "FAIR Assessment",
    "conditional_demographic_disparity": "Conditional Demographic Disparity",
}


# Fallback rationale when no LLM is available. Kept here rather than read from
# METRIC_REGISTRY so this module stays cheap to import.
DESCRIPTIONS: Dict[str, str] = {
    "completeness": "Column completeness scores and overall completeness.",
    "duplicity": "Dataset duplicates ratio.",
    "outliers": "Outlier proportions for numerical columns.",
    "constant_feature_count": "Count and list of columns with a single distinct non-null value.",
    "max_pairwise_correlation": "Strongest absolute pairwise correlation between features.",
    "skewness": "Per-feature skewness (distribution asymmetry).",
    "kurtosis": "Per-feature excess kurtosis (tail heaviness).",
    "row_level_completeness": "Percentage of rows where every required column is non-null.",
    "duplicity_by_features": "Duplicate rows computed using only the selected feature columns.",
    "feature_coverage_ratio": "Percentage of features whose non-null rate meets a threshold.",
    "temporal_completeness": "Percentage of expected time intervals present in the data.",
    "null_count_trend": "Null counts grouped by a batch column, to spot quality regressions.",
    "outliers_custom": "Flags values that fail user-provided valid-value range, regex, and compound rules.",
    "file_reference_validation": "Validates selected dataset values as references to files on this host.",
    "correlations": "Categorical and numerical correlation matrices.",
    "feature_relevance": "Feature relevance to target.",
    "class_imbalance": "Class imbalance degree.",
    "statistical_rates": "Statistical rates across sensitive groups.",
    "representation_rate": "Representation rate ratios for categorical values.",
    "k_anonymity": "k-anonymity score.",
    "l_diversity": "l-diversity score.",
    "t_closeness": "t-closeness score.",
    "entropy_risk": "Entropy risk score.",
    "single_attribute_risk": "Single attribute Markov-model risk scores.",
    "multiple_attribute_risk": "Multiple attribute Markov-model risk scores.",
    "differential_privacy": "Differentially private noise statistics for selected columns.",
    "hipaa_compliance": "Scan columns for HIPAA-regulated PHI (SSN, email, phone, IP, URLs, medical IDs, postal codes).",
    "fair_assessment": WEB_ONLY["fair_assessment"]["description"],
    "conditional_demographic_disparity": WEB_ONLY["conditional_demographic_disparity"]["description"],
}


# Honest limits, appended to the rationale so a card never overpromises. Two
# kinds: checks that cannot see the whole problem, and checks that need the
# user to bring something before the panel can run at all. Without these a
# critical-tier card can be a dead end.
CAVEATS: Dict[str, str] = {
    "duplicity_by_features": (
        "Note this compares rows within this file only, so it cannot detect overlap "
        "between separate train and test files."
    ),
    "row_level_completeness": "You will need to nominate the required columns.",
    "temporal_completeness": "You will need to nominate a timestamp column and a frequency.",
    "null_count_trend": "You will need to nominate a batch column.",
    "outliers_custom": "You will need to supply validity rules.",
    "file_reference_validation": "You will need to nominate which columns hold file paths.",
    "class_imbalance": "You will need to nominate the target column.",
    "feature_relevance": "You will need to nominate the target column.",
    "statistical_rates": "You will need to nominate a target column and a sensitive attribute.",
    "conditional_demographic_disparity": (
        "You will need to nominate a target column, a sensitive attribute, and a target value."
    ),
    "k_anonymity": "You will need to nominate the quasi-identifier columns.",
    "l_diversity": (
        "You will need quasi-identifiers and a sensitive column. Interpret this only "
        "after k-anonymity holds."
    ),
    "t_closeness": "You will need quasi-identifiers and a sensitive column.",
    "entropy_risk": "You will need to nominate the quasi-identifier columns.",
    "single_attribute_risk": "You will need an ID column and the columns to evaluate.",
    "multiple_attribute_risk": "You will need an ID column and the columns to evaluate.",
    "fair_assessment": "This one is optional and needs a DCAT or Datacite metadata file.",
}


# Which inspector panel each metric is configured in. Note
# file_reference_validation has registry category "data-quality" but lives in
# the Data Structure panel, which is why cards group by panel, not category.
PANEL_BY_METRIC: Dict[str, str] = {
    "completeness": "data-quality",
    "row_level_completeness": "data-quality",
    "feature_coverage_ratio": "data-quality",
    "temporal_completeness": "data-quality",
    "null_count_trend": "data-quality",
    "outliers": "data-quality",
    "outliers_custom": "data-quality",
    "duplicity": "data-quality",
    "duplicity_by_features": "data-quality",
    "constant_feature_count": "data-structure",
    "max_pairwise_correlation": "data-structure",
    "skewness": "data-structure",
    "kurtosis": "data-structure",
    "file_reference_validation": "data-structure",
    "correlations": "correlation-analysis",
    "feature_relevance": "feature-relevance",
    "class_imbalance": "class-imbalance",
    "statistical_rates": "fairness",
    "representation_rate": "fairness",
    "conditional_demographic_disparity": "fairness",
    "k_anonymity": "privacy-preservation",
    "l_diversity": "privacy-preservation",
    "t_closeness": "privacy-preservation",
    "entropy_risk": "privacy-preservation",
    "single_attribute_risk": "privacy-preservation",
    "multiple_attribute_risk": "privacy-preservation",
    "differential_privacy": "privacy-preservation",
    "hipaa_compliance": "hipaa-compliance",
    "fair_assessment": "fair-assessment",
}

PANEL_LABELS: Dict[str, str] = {
    "data-quality": "Data Quality",
    "data-structure": "Data Structure",
    "correlation-analysis": "Correlation Analysis",
    "feature-relevance": "Feature Relevance",
    "class-imbalance": "Class Imbalance",
    "fairness": "Fairness & Bias",
    "privacy-preservation": "Privacy Preservation",
    "hipaa-compliance": "HIPAA Compliance",
    "fair-assessment": "FAIR Assessment",
}


# See the spec's "Editorial decisions behind the table" section before
# changing any of these. differential_privacy is deliberately in no profile:
# it is a remediation utility, not an assessment.
INTENT_PROFILES: Dict[str, Dict[str, List[str]]] = {
    "training": {
        "critical": [
            "completeness",
            "duplicity",
            "duplicity_by_features",
            "class_imbalance",
            "max_pairwise_correlation",
            "hipaa_compliance",
        ],
        "recommended": [
            "outliers",
            "correlations",
            "feature_relevance",
            "constant_feature_count",
            "skewness",
            "representation_rate",
            "file_reference_validation",
        ],
    },
    "inference": {
        "critical": [
            "completeness",
            "row_level_completeness",
            "feature_coverage_ratio",
            "constant_feature_count",
            "outliers_custom",
        ],
        "recommended": [
            "outliers",
            "duplicity",
            "null_count_trend",
            "temporal_completeness",
            "hipaa_compliance",
        ],
    },
    "agentic": {
        "critical": [
            "completeness",
            "duplicity",
            "duplicity_by_features",
            "hipaa_compliance",
            "file_reference_validation",
            "outliers_custom",
        ],
        "recommended": [
            "feature_coverage_ratio",
            "k_anonymity",
            "row_level_completeness",
        ],
    },
    "publishing": {
        "critical": [
            "hipaa_compliance",
            "k_anonymity",
            "completeness",
            "fair_assessment",
            "file_reference_validation",
        ],
        "recommended": [
            "l_diversity",
            "t_closeness",
            "entropy_risk",
            "single_attribute_risk",
            "multiple_attribute_risk",
            "duplicity",
            "constant_feature_count",
            "representation_rate",
        ],
    },
    "benchmarking": {
        "critical": [
            "duplicity",
            "duplicity_by_features",
            "class_imbalance",
            "max_pairwise_correlation",
            "completeness",
        ],
        "recommended": [
            "representation_rate",
            "statistical_rates",
            "conditional_demographic_disparity",
            "feature_relevance",
            "outliers_custom",
        ],
    },
    "curation": {
        "critical": [
            "completeness",
            "row_level_completeness",
            "constant_feature_count",
            "duplicity",
            "file_reference_validation",
        ],
        "recommended": [
            "feature_coverage_ratio",
            "outliers",
            "outliers_custom",
            "null_count_trend",
            "temporal_completeness",
            "duplicity_by_features",
        ],
    },
    "exploration": {
        "critical": [
            "completeness",
            "outliers",
            "duplicity",
            "max_pairwise_correlation",
        ],
        "recommended": [
            "skewness",
            "kurtosis",
            "correlations",
            "constant_feature_count",
            "feature_coverage_ratio",
        ],
    },
}


# What a metric needs from the dataset to be worth suggesting at all.
# Metrics absent from this map are always applicable. temporal_completeness is
# deliberately absent: see the spec's "Rejected: datetime detection".
APPLICABILITY: Dict[str, str] = {
    "class_imbalance": "categorical",
    "statistical_rates": "categorical",
    "representation_rate": "categorical",
    "conditional_demographic_disparity": "categorical",
    "k_anonymity": "categorical",
    "l_diversity": "categorical",
    "t_closeness": "categorical",
    "entropy_risk": "categorical",
    "hipaa_compliance": "categorical",
    "single_attribute_risk": "categorical",
    "multiple_attribute_risk": "categorical",
    "skewness": "numerical",
    "kurtosis": "numerical",
    "feature_relevance": "numerical",
    "correlations": "two_columns",
    "max_pairwise_correlation": "two_columns",
    "file_reference_validation": "string",
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/test_intent.py -v`
Expected: PASS, no failures (around 18 tests).

- [ ] **Step 5: Lint**

Run: `flake8 --config=tox.ini aidrin/intent.py`
Expected: no output. The `outliers_custom` and `hipaa_compliance` description strings are long; keep them under 150 characters or wrap them.

- [ ] **Step 6: Stage (do not commit)**

```bash
git add aidrin/intent.py tests/unit/test_intent.py
# Authorised later only:
# git commit -m "Add intent catalog for metric recommendations"
```

---

## Task 2: `recommend_metrics()`

**Files:**
- Modify: `aidrin/intent.py` (append)
- Test: `tests/unit/test_intent.py` (append)

**Interfaces:**
- Consumes: everything from Task 1.
- Produces: `recommend_metrics(intents: List[str], profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]`. Each returned dict has exactly the keys `metric` (str), `display_name` (str), `panel` (str), `panel_label` (str), `priority` (`"critical"` or `"recommended"`), `source` (always `"curated"`), `reason_intents` (list of intent keys, in `INTENTS` order), `why` (str, the fallback description). Also produces `is_applicable(metric: str, profile: Optional[dict]) -> bool`.

- [ ] **Step 1: Write the failing behaviour tests**

Append to `tests/unit/test_intent.py`:

```python
# --------------------------------------------------------------------------
# recommend_metrics
# --------------------------------------------------------------------------

FULL_PROFILE = {
    "rows": 100,
    "columns": 4,
    "numerical": ["age", "income"],
    "categorical": ["sex", "race"],
    "columns_with_nulls": 1,
}


def _metrics(results):
    return [r["metric"] for r in results]


def _by_key(results):
    return {r["metric"]: r for r in results}


def test_empty_intents_returns_empty_list():
    assert recommend([]) == []


def recommend(intents, profile=FULL_PROFILE):
    return intent.recommend_metrics(intents, profile)


def test_unknown_intent_is_ignored_not_raised():
    assert recommend(["not_a_real_intent"]) == []


def test_unknown_intent_alongside_known_one_keeps_the_known_one():
    assert "completeness" in _metrics(recommend(["training", "bogus"]))


def test_single_intent_returns_its_critical_and_recommended_metrics():
    results = _by_key(recommend(["exploration"]))
    assert results["completeness"]["priority"] == "critical"
    assert results["skewness"]["priority"] == "recommended"


def test_result_shape_has_exactly_the_documented_keys():
    entry = _by_key(recommend(["exploration"]))["completeness"]
    assert set(entry) == {
        "metric",
        "display_name",
        "panel",
        "panel_label",
        "priority",
        "source",
        "reason_intents",
        "why",
    }
    assert entry["display_name"] == "Completeness"
    assert entry["panel"] == "data-quality"
    assert entry["panel_label"] == "Data Quality"
    assert entry["source"] == "curated"
    # completeness has no caveat, so why is the plain description
    assert entry["why"] == intent.DESCRIPTIONS["completeness"]


def test_a_metric_with_a_caveat_states_it_in_why():
    """Cards must say what the user has to bring, or they are dead ends."""
    entry = _by_key(recommend(["training"]))["class_imbalance"]
    assert intent.DESCRIPTIONS["class_imbalance"] in entry["why"]
    assert intent.CAVEATS["class_imbalance"] in entry["why"]


def test_within_file_limitation_is_stated_for_duplicate_detection():
    entry = _by_key(recommend(["benchmarking"]))["duplicity_by_features"]
    assert "within this file only" in entry["why"]


def test_multiple_intents_union_their_metrics():
    results = _metrics(recommend(["exploration", "publishing"]))
    assert "skewness" in results          # exploration only
    assert "fair_assessment" in results   # publishing only


def test_priority_merges_by_maximum():
    """duplicity is recommended for publishing, critical for exploration."""
    assert intent.INTENT_PROFILES["publishing"]["recommended"].count("duplicity") == 1
    assert intent.INTENT_PROFILES["exploration"]["critical"].count("duplicity") == 1
    results = _by_key(recommend(["publishing", "exploration"]))
    assert results["duplicity"]["priority"] == "critical"


def test_reason_intents_lists_every_intent_that_asked_for_the_metric():
    results = _by_key(recommend(["training", "exploration"]))
    assert results["completeness"]["reason_intents"] == ["training", "exploration"]


def test_reason_intents_follows_intents_declaration_order():
    """Order is stable regardless of how the caller ordered its selection."""
    a = _by_key(recommend(["exploration", "training"]))["completeness"]
    b = _by_key(recommend(["training", "exploration"]))["completeness"]
    assert a["reason_intents"] == b["reason_intents"] == ["training", "exploration"]


def test_criticals_are_ordered_before_recommended():
    results = recommend(["training"])
    priorities = [r["priority"] for r in results]
    assert priorities == sorted(priorities, key=lambda p: 0 if p == "critical" else 1)


def test_within_a_priority_more_agreeing_intents_sorts_first():
    results = recommend(["training", "benchmarking", "exploration"])
    criticals = [r for r in results if r["priority"] == "critical"]
    counts = [len(r["reason_intents"]) for r in criticals]
    assert counts == sorted(counts, reverse=True)


def test_ordering_is_deterministic():
    assert recommend(["training", "publishing"]) == recommend(["training", "publishing"])


def test_no_duplicate_metrics_in_output():
    results = _metrics(recommend(list(intent.INTENT_KEYS)))
    assert len(results) == len(set(results))


def test_applicability_drops_correlations_on_a_single_column_dataset():
    profile = {"rows": 10, "columns": 1, "numerical": ["age"], "categorical": []}
    assert "correlations" not in _metrics(recommend(["exploration"], profile))


def test_applicability_drops_categorical_metrics_when_no_categorical_columns():
    profile = {"rows": 10, "columns": 3, "numerical": ["a", "b", "c"], "categorical": []}
    assert "class_imbalance" not in _metrics(recommend(["training"], profile))


def test_applicability_drops_numerical_metrics_when_no_numerical_columns():
    profile = {"rows": 10, "columns": 3, "numerical": [], "categorical": ["a", "b", "c"]}
    assert "skewness" not in _metrics(recommend(["exploration"], profile))


def test_none_profile_disables_all_filtering():
    """Cache-miss and Globus paths pass None; the filter must fail open."""
    results = _metrics(intent.recommend_metrics(["exploration"], None))
    assert "correlations" in results
    assert "skewness" in results


def test_temporal_completeness_survives_a_profile_with_no_datetime_information():
    results = _metrics(recommend(["curation"]))
    assert "temporal_completeness" in results


def test_is_applicable_returns_true_for_unknown_metric():
    assert intent.is_applicable("not_a_metric", FULL_PROFILE) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/test_intent.py -v`
Expected: FAIL — `AttributeError: module 'aidrin.intent' has no attribute 'recommend_metrics'`

- [ ] **Step 3: Implement**

Append to `aidrin/intent.py`:

```python
def _fallback_why(metric: str) -> str:
    """Rationale used when no LLM tailors the card.

    The caveat is appended rather than replacing the description, so a card
    always says both what the check does and what the user must bring to it.
    """
    description = DESCRIPTIONS[metric]
    caveat = CAVEATS.get(metric)
    return f"{description} {caveat}" if caveat else description


def is_applicable(metric: str, profile: Optional[Dict[str, Any]]) -> bool:
    """Whether a metric is worth suggesting for this dataset.

    Fails open in every uncertain case: an unknown metric, a metric with no
    rule, or a missing profile all return True. A profile of ``None`` (cache
    miss, or Globus mode where no local profile exists) disables filtering
    entirely rather than silently withholding advice.
    """
    if profile is None:
        return True
    requirement = APPLICABILITY.get(metric)
    if requirement is None:
        return True
    if requirement in ("categorical", "string"):
        # /summary-statistics groups string and boolean columns together, so
        # "string" and "categorical" resolve to the same list.
        return bool(profile.get("categorical"))
    if requirement == "numerical":
        return bool(profile.get("numerical"))
    if requirement == "two_columns":
        return int(profile.get("columns") or 0) >= 2
    return True


def recommend_metrics(
    intents: List[str],
    profile: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return prioritised metric recommendations for the given intents.

    Parameters
    ----------
    intents:
        Intent keys. Unknown keys are ignored rather than raising, so a stale
        client cannot break the request.
    profile:
        Dataset profile used only to drop inapplicable metrics. ``None``
        disables filtering.

    Returns
    -------
    A list ordered critical-first, then by how many intents agree, then by
    panel and metric key for determinism. Nothing is computed or run.
    """
    # Iterate INTENTS rather than the caller's list so reason_intents ordering
    # is stable no matter how the client ordered its checkboxes.
    selected = [entry["key"] for entry in INTENTS if entry["key"] in set(intents)]

    best: Dict[str, str] = {}
    reasons: Dict[str, List[str]] = {}

    for intent_key in selected:
        profile_entry = INTENT_PROFILES[intent_key]
        for priority in (CRITICAL, RECOMMENDED):
            for metric in profile_entry[priority]:
                if not is_applicable(metric, profile):
                    continue
                reasons.setdefault(metric, []).append(intent_key)
                current = best.get(metric)
                if current is None or _PRIORITY_RANK[priority] < _PRIORITY_RANK[current]:
                    best[metric] = priority

    results = [
        {
            "metric": metric,
            "display_name": DISPLAY_NAMES[metric],
            "panel": PANEL_BY_METRIC[metric],
            "panel_label": PANEL_LABELS[PANEL_BY_METRIC[metric]],
            "priority": priority,
            "source": "curated",
            "reason_intents": reasons[metric],
            "why": _fallback_why(metric),
        }
        for metric, priority in best.items()
    ]

    results.sort(
        key=lambda r: (
            _PRIORITY_RANK[r["priority"]],
            -len(r["reason_intents"]),
            r["panel"],
            r["metric"],
        )
    )
    return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/test_intent.py -v`
Expected: PASS, no failures (around 40 tests).

- [ ] **Step 5: Lint and stage**

```bash
flake8 --config=tox.ini aidrin/intent.py
git add aidrin/intent.py tests/unit/test_intent.py
# Authorised later only:
# git commit -m "Add recommend_metrics to the intent catalog"
```

---

## Task 3: LLM enhancement layer

**Files:**
- Modify: `web/llm.py` (append)
- Test: `tests/unit/test_intent_llm_parsing.py` (create)

**Interfaces:**
- Consumes: `aidrin.intent.all_metric_keys`, `aidrin.intent.is_applicable`.
- Produces:
  - `parse_recommendation(text: str) -> Optional[dict]` — lenient JSON extraction, **no `openai` import**.
  - `validate_recommendation(raw: dict, baseline: List[str], profile: Optional[dict]) -> Optional[dict]` — returns `{"summary": str, "rationales": Dict[str, str], "extras": List[dict]}` or `None`. Each extra is `{"metric": str, "why": str}`.
  - `recommend_for_intent(intents, notes, profile, baseline, config) -> Optional[dict]` — same shape as `validate_recommendation`, or `None` on any failure.
  - `RECOMMEND_SYSTEM_PROMPT`, `MAX_EXTRAS = 5`, `MAX_TEXT = 400`, `MAX_COLUMNS_IN_PROMPT = 50`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_intent_llm_parsing.py`:

````python
"""Parsing and validation of the LLM recommendation response.

These tests must run without the openai package installed, so they import
only the pure helpers from web.llm.
"""

import pytest

from web.llm import MAX_EXTRAS, parse_recommendation, validate_recommendation


VALID = """
{"summary": "Looks fine.",
 "rationales": {"completeness": "6 of 15 columns have nulls."},
 "extras": [{"metric": "k_anonymity", "why": "You mentioned releasing this."}]}
"""


def test_parses_bare_json():
    assert parse_recommendation(VALID)["summary"] == "Looks fine."


def test_parses_fenced_json():
    assert parse_recommendation(f"```json\n{VALID}\n```")["summary"] == "Looks fine."


def test_parses_json_with_surrounding_prose():
    text = f"Here is my answer:\n{VALID}\nHope that helps."
    assert parse_recommendation(text)["summary"] == "Looks fine."


def test_malformed_json_returns_none():
    assert parse_recommendation("{not json at all") is None


def test_empty_text_returns_none():
    assert parse_recommendation("") is None


def test_non_object_json_returns_none():
    assert parse_recommendation("[1, 2, 3]") is None


def _validate(raw, baseline=(), profile=None):
    return validate_recommendation(raw, list(baseline), profile)


def test_unknown_rationale_keys_are_dropped():
    out = _validate({"rationales": {"completeness": "ok", "not_a_metric": "nope"}})
    assert out["rationales"] == {"completeness": "ok"}


def test_unknown_extra_metrics_are_dropped():
    out = _validate({"extras": [{"metric": "not_a_metric", "why": "x"}]})
    assert out["extras"] == []


def test_extras_already_in_baseline_are_dropped():
    out = _validate({"extras": [{"metric": "k_anonymity", "why": "x"}]}, baseline=["k_anonymity"])
    assert out["extras"] == []


def test_extras_are_capped():
    metrics = [
        "k_anonymity", "l_diversity", "t_closeness", "entropy_risk",
        "skewness", "kurtosis", "outliers", "duplicity",
    ]
    out = _validate({"extras": [{"metric": m, "why": "x"} for m in metrics]})
    assert len(out["extras"]) == MAX_EXTRAS


def test_extras_are_filtered_by_applicability():
    """A numerical-only dataset must not get a categorical extra."""
    profile = {"rows": 10, "columns": 3, "numerical": ["a", "b", "c"], "categorical": []}
    out = _validate({"extras": [{"metric": "k_anonymity", "why": "x"}]}, profile=profile)
    assert out["extras"] == []


def test_long_strings_are_truncated():
    out = _validate({"summary": "x" * 5000, "rationales": {"completeness": "y" * 5000}})
    assert len(out["summary"]) <= 400
    assert len(out["rationales"]["completeness"]) <= 400


def test_extra_without_a_why_is_dropped():
    assert _validate({"extras": [{"metric": "k_anonymity"}]})["extras"] == []


def test_non_dict_input_returns_none():
    assert _validate(None) is None
    assert _validate([1, 2]) is None


def test_response_that_validates_to_nothing_returns_none():
    assert _validate({"summary": "", "rationales": {}, "extras": []}) is None


def test_malformed_extras_entries_do_not_raise():
    out = _validate({"extras": ["a string", 42, {"metric": "k_anonymity", "why": "ok"}]})
    assert [e["metric"] for e in out["extras"]] == ["k_anonymity"]


def test_rationale_with_non_string_value_is_dropped():
    out = _validate({"rationales": {"completeness": {"nested": "object"}}, "summary": "ok"})
    assert out["rationales"] == {}
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/test_intent_llm_parsing.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_recommendation' from 'web.llm'`

- [ ] **Step 3: Implement**

Append to `web/llm.py`:

````python
# ---------------------------------------------------------------------------
# Intent-based metric recommendation
# ---------------------------------------------------------------------------

MAX_EXTRAS = 5
MAX_TEXT = 400
MAX_COLUMNS_IN_PROMPT = 50

RECOMMEND_SYSTEM_PROMPT = (
    "You are a data readiness advisor. The user will tell you what they plan to do "
    "with a dataset, and you will be given a catalog of available checks, a short "
    "profile of the dataset, and the checks already selected for them. "
    "Reply with a single JSON object and nothing else, in this exact shape:\n"
    '{"summary": "...", "rationales": {"<metric_key>": "..."}, '
    '"extras": [{"metric": "<metric_key>", "why": "..."}]}\n'
    "Rules: use only metric keys from the catalog; write one or two sentences per "
    "rationale explaining why that check matters for THIS dataset and THIS goal; "
    "propose at most five extras, and only checks not already selected; if a check "
    "needs the user to nominate a column or supply rules, say so in its rationale. "
    "Do not invent metric names. Do not suggest column names."
)


def parse_recommendation(text):
    """Extract the JSON object from an LLM reply.

    Lenient because the endpoint may be any OpenAI-compatible API and
    ``response_format`` is not universally supported: strips code fences and
    locates the outermost object. Returns None if nothing parses.
    """
    import json

    if not text or not isinstance(text, str):
        return None

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None

    try:
        parsed = json.loads(cleaned[start:end + 1])
    except (ValueError, TypeError):
        return None

    return parsed if isinstance(parsed, dict) else None


def _clean_text(value):
    """Coerce to a trimmed, length-capped string, or None if not text."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed[:MAX_TEXT] if trimmed else None


def validate_recommendation(raw, baseline, profile=None):
    """Drop anything the model made up.

    Metric keys must be real, extras must not duplicate the baseline, extras
    must pass the same applicability filter the curated list did, and every
    string is length-capped. Returns None when nothing survives.
    """
    from aidrin.intent import all_metric_keys, is_applicable

    if not isinstance(raw, dict):
        return None

    valid_keys = all_metric_keys()
    baseline_set = set(baseline or [])

    summary = _clean_text(raw.get("summary")) or ""

    raw_rationales = raw.get("rationales")
    if not isinstance(raw_rationales, dict):
        raw_rationales = {}

    rationales = {}
    for key, value in raw_rationales.items():
        if key not in valid_keys:
            continue
        text = _clean_text(value)
        if text:
            rationales[key] = text

    extras = []
    seen = set()
    for entry in raw.get("extras") or []:
        if len(extras) >= MAX_EXTRAS:
            break
        if not isinstance(entry, dict):
            continue
        metric = entry.get("metric")
        why = _clean_text(entry.get("why"))
        if not why or metric not in valid_keys:
            continue
        if metric in baseline_set or metric in seen:
            continue
        if not is_applicable(metric, profile):
            continue
        seen.add(metric)
        extras.append({"metric": metric, "why": why})

    if not summary and not rationales and not extras:
        return None

    return {"summary": summary, "rationales": rationales, "extras": extras}


def _format_profile(profile):
    """Render the dataset profile for the prompt, capping column lists."""
    if not profile:
        return "No dataset profile is available."

    lines = [f"Rows: {profile.get('rows', 'unknown')}", f"Columns: {profile.get('columns', 'unknown')}"]
    for kind in ("numerical", "categorical"):
        names = profile.get(kind) or []
        shown = names[:MAX_COLUMNS_IN_PROMPT]
        suffix = f" (+{len(names) - len(shown)} more)" if len(names) > len(shown) else ""
        lines.append(f"{kind.capitalize()} columns ({len(names)}): {', '.join(map(str, shown))}{suffix}")
    nulls = profile.get("columns_with_nulls")
    if nulls is not None:
        lines.append(f"Columns containing nulls: {nulls}")
    return "\n".join(lines)


def recommend_for_intent(intents, notes, profile, baseline, config):
    """Ask the LLM to tailor and extend a curated recommendation list.

    Returns the validated ``{"summary", "rationales", "extras"}`` dict, or
    None on any failure. Callers must treat None as "use the curated list
    unchanged" — this is an enhancement, never a dependency.
    """
    from aidrin.intent import DESCRIPTIONS, INTENTS

    if not _llm_available:
        return None

    try:
        catalog = "\n".join(f"  {key}: {text}" for key, text in sorted(DESCRIPTIONS.items()))
        labels = {entry["key"]: entry["label"] for entry in INTENTS}
        goals = ", ".join(labels.get(key, key) for key in intents) or "(not specified)"

        user_content = (
            f"Available checks:\n{catalog}\n\n"
            f"Dataset profile:\n{_format_profile(profile)}\n\n"
            f"User goals: {goals}\n"
            f"User notes: {notes or '(none)'}\n\n"
            f"Already selected: {', '.join(baseline) or '(none)'}"
        )

        client = openai.OpenAI(base_url=config["api_base"], api_key=config["api_key"])
        response = client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": RECOMMEND_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=3000,
            temperature=config.get("temperature", 0.5),
        )
        if not response.choices:
            return None
        reply = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.info("LLM recommendation failed: %s", e)
        return None

    return validate_recommendation(parse_recommendation(reply), baseline, profile)
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/unit/test_intent_llm_parsing.py -v`
Expected: PASS, no failures (around 18 tests).

- [ ] **Step 5: Verify the pure helpers do not need openai**

Run: `PYTHONPATH=. python -c "from web.llm import parse_recommendation; print(parse_recommendation('{\"summary\":\"ok\"}'))"`
Expected: `{'summary': 'ok'}`. The `openai` import in `web/llm.py` is already wrapped in try/except at module level, so this holds whether or not the package is installed.

- [ ] **Step 6: Lint and stage**

```bash
flake8 --config=tox.ini web/llm.py
git add web/llm.py tests/unit/test_intent_llm_parsing.py
# Authorised later only:
# git commit -m "Add LLM enhancement layer for intent recommendations"
```

---

## Task 4: The route blueprint

**Files:**
- Create: `web/routes/intent.py`
- Modify: `web/routes/__init__.py`
- Test: `tests/integration/test_intent_routes.py`

**Interfaces:**
- Consumes: `aidrin.intent.recommend_metrics`, `aidrin.intent.INTENT_KEYS`, `aidrin.intent.DISPLAY_NAMES`, `aidrin.intent.PANEL_BY_METRIC`, `aidrin.intent.PANEL_LABELS`, `web.llm.recommend_for_intent`, `web.routes.utils.generate_metric_cache_key`, `web.routes.utils.get_current_user_id`, `web.routes.utils.is_metric_cache_valid`.
- Produces: `intent_bp` (url_prefix `/intent`), routes `POST /intent/recommend` and `POST /intent/dismiss`, `NOTES_MAX = 500`, and the cache entry `user:{uid}:file:{name}:intent`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_intent_routes.py`:

```python
"""Integration tests for the intent recommendation routes.

The curated path must work with no LLM installed or configured, so these
tests run in every CI job. LLM-specific behaviour is monkeypatched rather
than gated on the optional dependency.
"""

import pytest

import web.routes.intent as intent_routes


def test_recommend_requires_intents_or_notes(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": [], "notes": ""})
    assert response.status_code == 400


def test_recommend_rejects_non_list_intents(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": "training"})
    assert response.status_code == 400


def test_recommend_works_without_any_llm(uploaded_client):
    """The curated half must not depend on openai being installed."""
    response = uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    assert response.status_code == 200
    data = response.get_json()
    assert data["llm_used"] is False
    assert data["intents"] == ["training"]
    metrics = [r["metric"] for r in data["recommendations"]]
    assert "completeness" in metrics
    assert all(r["source"] == "curated" for r in data["recommendations"])


def test_recommend_accepts_notes_only(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": [], "notes": "just curious"})
    assert response.status_code == 200
    assert response.get_json()["recommendations"] == []


def test_unknown_intents_are_filtered_out(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": ["training", "bogus"]})
    assert response.get_json()["intents"] == ["training"]


def test_recommendations_are_critical_first(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": ["training", "publishing"]})
    priorities = [r["priority"] for r in response.get_json()["recommendations"]]
    assert priorities == sorted(priorities, key=lambda p: 0 if p == "critical" else 1)


def test_every_recommendation_carries_a_panel_and_display_name(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": ["publishing"]})
    for rec in response.get_json()["recommendations"]:
        assert rec["display_name"]
        assert rec["panel"]
        assert rec["panel_label"]
        assert rec["why"]


def test_llm_enhancement_is_merged_when_available(uploaded_client, monkeypatch):
    monkeypatch.setattr(intent_routes, "_llm_config", lambda: {"model": "test-model"})
    monkeypatch.setattr(
        intent_routes,
        "_call_llm",
        lambda *a, **kw: {
            "summary": "Tailored summary.",
            "rationales": {"completeness": "Six columns have nulls."},
            "extras": [{"metric": "t_closeness", "why": "Because you said EU."}],
        },
    )
    response = uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    data = response.get_json()

    assert data["llm_used"] is True
    assert data["model"] == "test-model"
    assert data["summary"] == "Tailored summary."

    by_key = {r["metric"]: r for r in data["recommendations"]}
    assert by_key["completeness"]["why"] == "Six columns have nulls."
    assert by_key["completeness"]["source"] == "curated"
    assert by_key["t_closeness"]["source"] == "ai"
    assert by_key["t_closeness"]["priority"] == "recommended"


def test_llm_failure_degrades_to_the_curated_list(uploaded_client, monkeypatch):
    monkeypatch.setattr(intent_routes, "_llm_config", lambda: {"model": "test-model"})
    monkeypatch.setattr(intent_routes, "_call_llm", lambda *a, **kw: None)
    response = uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    data = response.get_json()
    assert data["llm_used"] is False
    assert any(r["metric"] == "completeness" for r in data["recommendations"])


def test_result_is_cached_and_llm_not_called_twice(uploaded_client, monkeypatch):
    calls = []

    def _fake(*args, **kwargs):
        calls.append(1)
        return {"summary": "once", "rationales": {}, "extras": []}

    monkeypatch.setattr(intent_routes, "_llm_config", lambda: {"model": "test-model"})
    monkeypatch.setattr(intent_routes, "_call_llm", _fake)

    uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    cached = uploaded_client.get("/cached-result/intent")

    assert cached.status_code == 200
    assert len(calls) == 1


def test_notes_are_truncated_in_the_session(uploaded_client):
    uploaded_client.post("/intent/recommend", json={"intents": ["training"], "notes": "x" * 5000})
    with uploaded_client.session_transaction() as sess:
        assert len(sess["intent"]["notes"]) == intent_routes.NOTES_MAX


def test_intent_is_stored_in_the_session(uploaded_client):
    uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    with uploaded_client.session_transaction() as sess:
        assert sess["intent"]["intents"] == ["training"]


def test_dismiss_marks_the_modal_as_handled(uploaded_client):
    response = uploaded_client.post("/intent/dismiss", json={})
    assert response.status_code == 200
    with uploaded_client.session_transaction() as sess:
        assert sess["intent"]["dismissed"] is True


def test_recommend_without_a_dataset_still_returns_advice(client):
    """No file loaded means no profile, but the curated list is unaffected."""
    response = client.post("/intent/recommend", json={"intents": ["training"]})
    assert response.status_code == 200
    assert response.get_json()["recommendations"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/integration/test_intent_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web.routes.intent'`

- [ ] **Step 3: Write the blueprint**

Create `web/routes/intent.py`:

```python
"""Flask routes for intent-based metric recommendations.

Registered unconditionally. The curated recommendation needs no LLM and no
network; web.llm is imported lazily inside the handler so this module never
hard-depends on the optional openai package.

Nothing here runs a metric or reads a dataset. The dataset profile is read
from the summary-statistics cache when warm and is None otherwise.
"""

import logging
import time

from flask import Blueprint, current_app, jsonify, request, session

from aidrin.intent import (
    DISPLAY_NAMES,
    INTENT_KEYS,
    INTENTS,
    PANEL_BY_METRIC,
    PANEL_LABELS,
    recommend_metrics,
)
from web.routes.utils import (
    generate_metric_cache_key,
    get_current_user_id,
    is_metric_cache_valid,
)

logger = logging.getLogger(__name__)

intent_bp = Blueprint("intent", __name__, url_prefix="/intent")

NOTES_MAX = 500
CACHE_TTL_SECONDS = 30 * 60
MAX_PROFILE_COLUMNS = 50


def _session_file_name():
    return session.get("uploaded_file_name") or session.get("globus_file_name") or ""


def _selected_keys():
    """Reproduce the HDF5 branch of /summary-statistics exactly.

    core.py:461-465 stores selected_keys as a list or a comma string, and the
    cache key sorts them. Diverging here would miss the cache on every HDF5
    dataset and fall through to a profile of None.
    """
    selected = session.get("selected_keys") or []
    if isinstance(selected, str):
        selected = [key.strip() for key in selected.split(",") if key.strip()]
    return selected


def _to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _columns_with_nulls(data):
    """Derive the null-column count; None when it cannot be established.

    /summary-statistics does not report this directly. summary_statistics is
    empty when a dataset has no numeric columns (core.py:507-508), so the
    figure is best-effort and the prompt omits the line when it is None.
    """
    records = _to_number(data.get("records_count"))
    if not records:
        return None

    count = 0
    seen = False
    for group in ("summary_statistics", "categorical_summary"):
        for stats in (data.get(group) or {}).values():
            if not isinstance(stats, dict):
                continue
            present = _to_number(stats.get("count"))
            if present is None:
                continue
            seen = True
            if present < records:
                count += 1
    return count if seen else None


def _build_profile():
    """Read a small profile from the warm summary-statistics cache.

    Returns None on a cache miss, in Globus mode, or when no file is loaded.
    Never reads the dataset: load_dataframe would materialise up to 1 GB
    synchronously inside this request, which is not acceptable for a feature
    that computes nothing.
    """
    file_name = _session_file_name()
    if not file_name or not session.get("uploaded_file_path"):
        return None

    cache_key = generate_metric_cache_key(file_name, "summarystats", selected_keys=_selected_keys())
    entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)
    if not entry or not is_metric_cache_valid(entry):
        return None

    data = entry.get("data") or {}
    if not data.get("success"):
        return None

    return {
        "rows": data.get("records_count"),
        "columns": data.get("features_count"),
        "numerical": list(data.get("numerical_features") or [])[:MAX_PROFILE_COLUMNS],
        "categorical": list(data.get("categorical_features") or [])[:MAX_PROFILE_COLUMNS],
        "columns_with_nulls": _columns_with_nulls(data),
    }


def _llm_config():
    """Return the session LLM config when the feature is usable, else None.

    Separated so tests can monkeypatch it without installing openai.
    """
    try:
        from web.llm import is_llm_available
    except Exception:
        return None
    if not is_llm_available():
        return None
    config = session.get("llm_config")
    if not config or not config.get("api_key"):
        return None
    return config


def _call_llm(intents, notes, profile, baseline, config):
    """Thin seam over web.llm.recommend_for_intent for monkeypatching."""
    from web.llm import recommend_for_intent

    return recommend_for_intent(intents, notes, profile, baseline, config)


def _merge(baseline, enhancement, profile):
    """Overlay LLM rationales on the curated list and append AI extras."""
    recommendations = [dict(entry) for entry in baseline]
    if not enhancement:
        return recommendations, ""

    rationales = enhancement.get("rationales") or {}
    for entry in recommendations:
        tailored = rationales.get(entry["metric"])
        if tailored:
            entry["why"] = tailored

    for extra in enhancement.get("extras") or []:
        metric = extra["metric"]
        recommendations.append({
            "metric": metric,
            "display_name": DISPLAY_NAMES[metric],
            "panel": PANEL_BY_METRIC[metric],
            "panel_label": PANEL_LABELS[PANEL_BY_METRIC[metric]],
            "priority": "recommended",
            "source": "ai",
            "reason_intents": [],
            "why": extra["why"],
        })

    return recommendations, enhancement.get("summary") or ""


def _store(payload):
    """Cache under the same convention as store_result, so /cached-result works."""
    file_name = _session_file_name()
    if not file_name:
        return
    key = f"user:{get_current_user_id()}:file:{file_name}:intent"
    current_app.TEMP_RESULTS_CACHE[key] = {
        "data": payload,
        "timestamp": time.time(),
        "expires_at": time.time() + CACHE_TTL_SECONDS,
    }


@intent_bp.route("/recommend", methods=["POST"])
def recommend():
    """Return which metrics the user should check, given what they plan to do."""
    body = request.get_json(silent=True) or {}

    raw_intents = body.get("intents", [])
    if not isinstance(raw_intents, list):
        return jsonify({"error": "intents must be a list"}), 400

    order = [entry["key"] for entry in INTENTS]
    chosen = {key for key in raw_intents if key in INTENT_KEYS}
    intents = [key for key in order if key in chosen]

    notes = (body.get("notes") or "").strip()[:NOTES_MAX]
    if not intents and not notes:
        return jsonify({"error": "Select at least one goal or describe your plan"}), 400

    profile = _build_profile()
    baseline = recommend_metrics(intents, profile)

    enhancement = None
    model = ""
    config = _llm_config()
    if config:
        model = config.get("model", "")
        enhancement = _call_llm(intents, notes, profile, [r["metric"] for r in baseline], config)

    recommendations, summary = _merge(baseline, enhancement, profile)

    payload = {
        "intents": intents,
        "notes": notes,
        "summary": summary,
        "llm_used": bool(enhancement),
        "model": model if enhancement else "",
        "recommendations": recommendations,
    }

    session["intent"] = {"intents": intents, "notes": notes, "dismissed": False}
    _store(payload)
    return jsonify(payload)


@intent_bp.route("/dismiss", methods=["POST"])
def dismiss():
    """Record that the user skipped the question, so the modal stops asking."""
    session["intent"] = {"intents": [], "notes": "", "dismissed": True}
    return jsonify({"success": True})
```

- [ ] **Step 4: Register the blueprint**

In `web/routes/__init__.py`, add the import beside the other unconditional ones and register it. The final file:

```python
from web.routes.admin import admin_bp
from web.routes.core import core_bp
from web.routes.custom import custom_bp
from web.routes.intent import intent_bp
from web.routes.metrics import metrics_bp


def register_blueprints(app):
    app.register_blueprint(admin_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(custom_bp)
    app.register_blueprint(intent_bp)
    app.register_blueprint(metrics_bp)

    # Globus Compute — optional, only if SDK is installed
    from web.globus import is_globus_available
    if is_globus_available():
        from web.routes.globus import globus_bp
        app.register_blueprint(globus_bp)

    # LLM explanations — optional, only if openai is installed
    from web.llm import is_llm_available
    if is_llm_available():
        from web.routes.llm import llm_bp
        app.register_blueprint(llm_bp)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/integration/test_intent_routes.py -v`
Expected: PASS, no failures (around 14 tests).

- [ ] **Step 6: Confirm nothing else broke**

Run: `PYTHONPATH=. pytest tests/ -q`
Expected: same pass count as before this task, plus the new tests.

- [ ] **Step 7: Lint and stage**

```bash
flake8 --config=tox.ini web/routes/intent.py web/routes/__init__.py
git add web/routes/intent.py web/routes/__init__.py tests/integration/test_intent_routes.py
# Authorised later only:
# git commit -m "Add intent recommendation routes"
```

---

## Task 5: Clear intent state on dataset switch

**Files:**
- Modify: `web/routes/core.py` (three call sites)
- Test: `tests/integration/test_intent_routes.py` (append)

**Interfaces:**
- Consumes: `session["intent"]` written by Task 4.
- Produces: nothing new. Three transitions now drop stale intent state.

**Why this is in scope:** this feature introduces `session["intent"]`, so it owns resetting it. Without these three lines, `/filter-file` leaves the cached recommendations in place while the user switches to a different HDF5 dataset — and because that cache key has no `selected_keys` component, the panel would restore advice computed for an entirely different set of columns. `/cached-result` does not check `is_metric_cache_valid` (`core.py:428-434`), so there is no TTL rescue.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_intent_routes.py`:

```python
# --------------------------------------------------------------------------
# Stale-state resets
# --------------------------------------------------------------------------


def test_new_upload_clears_intent(uploaded_client, sample_csv):
    uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    with uploaded_client.session_transaction() as sess:
        assert "intent" in sess

    with open(sample_csv, "rb") as handle:
        uploaded_client.post(
            "/inspector",
            data={"file": (handle, "second.csv"), "fileTypeSelector": ".csv"},
            content_type="multipart/form-data",
        )

    with uploaded_client.session_transaction() as sess:
        assert "intent" not in sess


def test_clear_file_clears_intent(uploaded_client):
    uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    uploaded_client.post("/clear")
    with uploaded_client.session_transaction() as sess:
        assert "intent" not in sess


def test_filter_file_clears_intent(uploaded_client):
    """HDF5 dataset switch must not leave advice for the previous columns."""
    uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    # /filter-file reads data.get("keys") (core.py:254). Posting the wrong field
    # name returns 400 before the pop is reached, so the payload must be "keys".
    response = uploaded_client.post("/filter-file", json={"keys": ["a"]})
    assert response.status_code == 200, response.get_data(as_text=True)
    with uploaded_client.session_transaction() as sess:
        assert "intent" not in sess
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/integration/test_intent_routes.py -k clears_intent -v`
Expected: `test_new_upload_clears_intent` and `test_filter_file_clears_intent` FAIL (`assert "intent" not in sess`). `test_clear_file_clears_intent` already PASSES, because `/clear` calls `session.clear()` — keep it as a regression guard.

- [ ] **Step 3: Add the three pops**

In `web/routes/core.py`, inside the `if file:` branch of `inspector()`, immediately after the existing `session.pop("selected_keys", None)` (around line 75):

```python
            session.pop("selected_keys", None)
            # This feature owns session["intent"], so a new dataset drops it.
            session.pop("intent", None)
```

In `filter_file()`, immediately after `session["minimize_preview"] = True` (around line 302):

```python
        session["selected_keys"] = keys_list
        session["minimize_preview"] = True
        # Recommendations were computed for the previous column selection.
        session.pop("intent", None)
```

In `clear_dataset_selection()`, immediately after `session.pop("minimize_preview", None)` (around line 322):

```python
        session.pop("selected_keys", None)
        session.pop("minimize_preview", None)
        session.pop("intent", None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/integration/test_intent_routes.py -v`
Expected: PASS, no failures (around 17 tests).

- [ ] **Step 5: Confirm the existing core-route tests still pass**

Run: `PYTHONPATH=. pytest tests/integration/test_core_routes.py tests/integration/test_inspector_upload.py -v`
Expected: PASS, unchanged.

- [ ] **Step 6: Lint and stage**

```bash
flake8 --config=tox.ini web/routes/core.py
git add web/routes/core.py tests/integration/test_intent_routes.py
# Authorised later only:
# git commit -m "Clear intent state when the dataset changes"
```

---

## Task 6: Templates

**Files:**
- Create: `web/templates/_components/intent_modal.html`
- Create: `web/templates/_panels/_intent.html`
- Modify: `web/templates/_components/sidebar.html`
- Modify: `web/templates/inspector.html`

**Interfaces:**
- Consumes: `uploaded_file_path` and `session["intent"]` in the template context (both already available — `core.py:157-181` renders `inspector.html`).
- Produces: DOM ids `intent-modal`, `intent-form`, `intent-notes`, `intent-submit`, `panel-intent`, `intent-summary`, `intent-cards`, `intent-change-form`, `intent-change-notes`; checkbox inputs named `intent` with the seven intent keys as values; `window.AIDRIN_INTENT_ASKED`.

Note the modal is gated **only** on a dataset being loaded, not on the LLM. This is deliberate: the curated list needs no key, and it also removes a bug the LLM gate would have created, since `saveLLMSettings()` (`inspector.js:7365`) sets `AIDRIN_LLM_ENABLED` without a reload.

- [ ] **Step 1: Create the modal**

Create `web/templates/_components/intent_modal.html`:

```html
<!-- Intent capture modal: opens once after a dataset loads -->
<div id="intent-modal" class="hidden fixed inset-0 z-[60] flex items-center justify-center bg-black/50" onclick="if(event.target===this)skipIntent()">
  <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-lg mx-4 p-6">
    <div class="flex items-center justify-between mb-2">
      <h3 class="text-lg font-semibold text-gray-900 dark:text-white">What are you preparing this data for?</h3>
      <button onclick="skipIntent()" class="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors" aria-label="Close">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
      </button>
    </div>

    <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
      Tell us your goal and we will suggest which readiness checks matter most. Select as many as apply. Nothing is run until you choose to run it.
    </p>

    <form id="intent-form" onsubmit="event.preventDefault()">
      <div class="space-y-2 mb-4">
        {% for option in intent_options %}
        <label class="flex items-start gap-2.5 p-2 rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50">
          <input type="checkbox" name="intent" value="{{ option.key }}" onchange="updateIntentSubmitState()"
                 class="mt-0.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700" />
          <span>
            <span class="block text-sm font-medium text-gray-900 dark:text-white">{{ option.label }}</span>
            <span class="block text-xs text-gray-500 dark:text-gray-400">{{ option.description }}</span>
          </span>
        </label>
        {% endfor %}
      </div>

      <div class="mb-4">
        <label for="intent-notes" class="block mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">Anything else we should know? (optional)</label>
        <textarea id="intent-notes" rows="2" maxlength="500" oninput="updateIntentSubmitState()"
                  placeholder="e.g. credit-risk model for EU deployment"
                  class="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg dark:border-gray-600 dark:bg-gray-700 dark:text-white focus:ring-blue-500 focus:border-blue-500"></textarea>
      </div>

      <div class="flex items-center justify-end gap-2">
        <button type="button" onclick="skipIntent()"
                class="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700">
          Skip
        </button>
        <button type="button" id="intent-submit" disabled onclick="submitIntent()"
                class="px-4 py-2 text-sm font-medium text-white bg-blue-700 rounded-lg hover:bg-blue-800 focus:ring-4 focus:ring-blue-300 dark:bg-blue-600 dark:hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed">
          Get recommendations
        </button>
      </div>

      <div id="intent-modal-status" class="mt-3 text-sm hidden"></div>
    </form>
  </div>
</div>
```

- [ ] **Step 2: Create the panel**

Create `web/templates/_panels/_intent.html`:

```html
<!-- Intent & Recommendations panel: which checks to run, and why -->
<div id="panel-intent" class="metric-panel hidden">
  <div class="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-sm p-5">
    <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">Intent &amp; Recommendations</h2>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
      Suggested readiness checks for what you plan to do with this dataset. Nothing here has been run.
    </p>

    <div id="intent-summary" class="mb-4"></div>
    <div id="intent-cards" class="space-y-3">
      <p class="text-sm text-gray-500 dark:text-gray-400">
        No goal selected yet. Use <em>Change goal</em> below to get recommendations.
      </p>
    </div>

    <details class="mt-6 border-t border-gray-200 dark:border-gray-700 pt-4">
      <summary class="text-sm font-medium cursor-pointer text-gray-700 dark:text-gray-300">Change goal</summary>
      <form id="intent-change-form" onsubmit="event.preventDefault()" class="mt-3">
        <div class="space-y-2 mb-3">
          {% for option in intent_options %}
          <label class="flex items-start gap-2.5 p-2 rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50">
            <input type="checkbox" name="intent" value="{{ option.key }}"
                   class="mt-0.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700" />
            <span>
              <span class="block text-sm font-medium text-gray-900 dark:text-white">{{ option.label }}</span>
              <span class="block text-xs text-gray-500 dark:text-gray-400">{{ option.description }}</span>
            </span>
          </label>
          {% endfor %}
        </div>
        <textarea id="intent-change-notes" rows="2" maxlength="500"
                  placeholder="Anything else we should know?"
                  class="w-full px-3 py-2 mb-3 text-sm border border-gray-300 rounded-lg dark:border-gray-600 dark:bg-gray-700 dark:text-white focus:ring-blue-500 focus:border-blue-500"></textarea>
        <button type="button" onclick="withSubmitGuard(this, () => submitIntent('change'));"
                class="px-4 py-2 text-sm font-medium text-white bg-blue-700 rounded-lg hover:bg-blue-800 dark:bg-blue-600 dark:hover:bg-blue-700">
          Update recommendations
        </button>
      </form>
    </details>
  </div>
</div>
```

- [ ] **Step 3: Pass the intent options from the route**

In `web/routes/core.py`, inside `inspector()`, add the import near the other local imports at the top of the function (beside `from web.llm import is_llm_available` at line 139) and pass the list to the template. Add to the `render_template("inspector.html", ...)` call at line 157:

```python
    from aidrin.intent import INTENTS
    ...
            intent_options=INTENTS,
            intent_asked=bool(session.get("intent")),
```

- [ ] **Step 4: Add the sidebar entry**

In `web/templates/_components/sidebar.html`, insert immediately **before** the Readiness Report button (before the `<!-- Readiness Report -->` comment):

```html
    <!-- Intent & Recommendations -->
    <button onclick="showPanel('intent')"
            class="sidebar-item flex items-center w-full p-2 mb-2 rounded-lg text-sm font-semibold transition-colors hover:bg-black/10 dark:hover:bg-white/10"
            style="color: var(--textColor);">
      <svg class="w-5 h-5 mr-2 shrink-0 text-gray-500 dark:text-gray-400" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z"/></svg>
      Intent &amp; Recommendations
    </button>
```

- [ ] **Step 5: Wire the includes**

In `web/templates/inspector.html`:

Add the modal include after the LLM settings block (after the `{% endif %}` closing the `llm_available` check, around line 30):

```html
  <!-- Intent capture modal (needs a dataset, not an LLM) -->
  {% if uploaded_file_path %}
    {% include '_components/intent_modal.html' %}
  {% endif %}
```

Add the panel include inside `panels-container`, immediately after the `_data_overview.html` include:

```html
          {% include '_panels/_intent.html' %}
```

Add the flag inside the existing `DOMContentLoaded` handler, beside `window.AIDRIN_LLM_ENABLED`:

```javascript
      window.AIDRIN_INTENT_ASKED = {{ 'true' if intent_asked else 'false' }};
```

- [ ] **Step 6: Verify the templates render**

Run: `PYTHONPATH=. pytest tests/integration/test_inspector.py tests/integration/test_pages.py -v`
Expected: PASS. A Jinja syntax error or an undefined variable surfaces here as a 500.

- [ ] **Step 7: Confirm the panel and modal are present after upload**

Run:

```bash
PYTHONPATH=. python3 -c "
from web import create_app
app = create_app(); app.config['TESTING'] = True
c = app.test_client()
import io
c.post('/inspector', data={'file': (io.BytesIO(b'a,b\n1,2\n'), 't.csv'), 'fileTypeSelector': '.csv'}, content_type='multipart/form-data')
html = c.get('/inspector').get_data(as_text=True)
print('modal:', 'intent-modal' in html)
print('panel:', 'panel-intent' in html)
print('sidebar:', 'showPanel(\'intent\')' in html)
print('flag:', 'AIDRIN_INTENT_ASKED' in html)
"
```

Expected: four `True` lines.

- [ ] **Step 8: Lint and stage**

```bash
flake8 --config=tox.ini web/routes/core.py
git add web/templates/_components/intent_modal.html web/templates/_panels/_intent.html web/templates/_components/sidebar.html web/templates/inspector.html web/routes/core.py
# Authorised later only:
# git commit -m "Add intent modal and recommendations panel"
```

---

## Task 7: Front-end behaviour

**Files:**
- Modify: `web/static/js/inspector.js`
- Modify: `tests/unit/test_inspector_js_security.py`

**Interfaces:**
- Consumes: the DOM ids from Task 6, `POST /intent/recommend`, `POST /intent/dismiss`, `GET /cached-result/intent`.
- Produces: `maybeShowIntentModal()`, `closeIntentModal()`, `updateIntentSubmitState()`, `submitIntent(source)`, `skipIntent()`, `renderIntentRecommendations(data)`, `_restoreIntentFromCache()`.

**Placement constraint:** `tests/unit/test_inspector_js_security.py` slices the file by source markers — `"function escapeHtml(str)"` → `"\n\n// ==================== FAIR Assessment"`, and `"function renderCategoricalPieCharts"` → `"\nfunction renderHdf5DatasetPicker"`. New functions must not land inside either window. **Append the new block at the end of the file**, after `disconnectLLM()`.

**Do not** add `intent` to `_panelCacheMap` (`inspector.js:456-465`). That map routes cached payloads into `renderWorkspaceResults()`, which expects metric-result shape and would throw on this payload.

- [ ] **Step 1: Write the failing security tests**

Append to `tests/unit/test_inspector_js_security.py`:

```python
def test_intent_renderer_escapes_llm_authored_text():
    """LLM output reaches innerHTML, so it must be escaped."""
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    required = [
        "${escapeHtml(rec.why)}",
        "${escapeHtml(rec.display_name)}",
        "${escapeHtml(rec.panel_label)}",
        "${escapeHtml(data.summary)}",
    ]
    for fragment in required:
        assert fragment in source, f"missing escape: {fragment!r}"

    forbidden = [
        "${rec.why}",
        "${rec.display_name}",
        "${data.summary}",
    ]
    for fragment in forbidden:
        assert fragment not in source, f"unescaped interpolation: {fragment!r}"


def test_intent_panel_link_uses_server_side_panel_vocabulary():
    """The jump control must never interpolate LLM-sourced text into onclick."""
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert "showPanel('${rec.panel}')" in source
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=. pytest tests/unit/test_inspector_js_security.py -v`
Expected: FAIL — `missing escape: '${escapeHtml(rec.why)}'`

- [ ] **Step 3: Append the JS block**

Append to the end of `web/static/js/inspector.js`:

```javascript
// ==================== Intent & Recommendations ====================

/**
 * Open the intent modal once per dataset, from the point where the summary is
 * genuinely ready. Never called before a dataset exists.
 */
function maybeShowIntentModal() {
  if (window.AIDRIN_INTENT_ASKED) return;
  const modal = document.getElementById("intent-modal");
  if (!modal) return;
  window.AIDRIN_INTENT_ASKED = true;
  modal.classList.remove("hidden");
}

function closeIntentModal() {
  const modal = document.getElementById("intent-modal");
  if (modal) modal.classList.add("hidden");
}

function _selectedIntents(formId) {
  const form = document.getElementById(formId);
  if (!form) return [];
  return Array.from(
    form.querySelectorAll('input[name="intent"]:checked'),
  ).map((el) => el.value);
}

/** Submit stays disabled until the user has actually answered something. */
function updateIntentSubmitState() {
  const button = document.getElementById("intent-submit");
  if (!button) return;
  const notes = (document.getElementById("intent-notes") || {}).value || "";
  button.disabled = _selectedIntents("intent-form").length === 0 && !notes.trim();
}

function skipIntent() {
  closeIntentModal();
  fetch("/intent/dismiss", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  }).catch(() => {});
}

/**
 * Ask the server which checks this dataset needs. `source` is "modal" or
 * "change", selecting which form to read.
 */
function submitIntent(source) {
  const fromChangeForm = source === "change";
  const formId = fromChangeForm ? "intent-change-form" : "intent-form";
  const notesId = fromChangeForm ? "intent-change-notes" : "intent-notes";
  const intents = _selectedIntents(formId);
  const notes = ((document.getElementById(notesId) || {}).value || "").trim();

  if (intents.length === 0 && !notes) return Promise.resolve();

  const status = document.getElementById("intent-modal-status");
  if (status && !fromChangeForm) {
    status.className = "mt-3 text-sm text-gray-500 dark:text-gray-400";
    status.textContent = "Working out what to suggest...";
  }

  return fetch("/intent/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intents: intents, notes: notes }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        if (status && !fromChangeForm) {
          status.className = "mt-3 text-sm text-yellow-700 dark:text-yellow-400";
          status.textContent = data.error;
        }
        return;
      }
      window.AIDRIN_INTENT_ASKED = true;
      renderIntentRecommendations(data);
      closeIntentModal();
      showPanel("intent");
    })
    .catch((err) => {
      if (status && !fromChangeForm) {
        status.className = "mt-3 text-sm text-yellow-700 dark:text-yellow-400";
        status.textContent = "Could not load recommendations: " + (err.message || err);
      }
      debugLog("Intent recommendation error:", err);
    });
}

function _intentPriorityBadge(priority) {
  const isCritical = priority === "critical";
  const classes = isCritical
    ? "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
    : "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300";
  const label = isCritical ? "Critical" : "Recommended";
  return `<span class="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full ${classes}">${label}</span>`;
}

function _intentCardHtml(rec) {
  const aiBadge =
    rec.source === "ai"
      ? '<span class="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">AI suggested</span>'
      : "";
  const reasons = (rec.reason_intents || []).length
    ? `<p class="text-xs text-gray-500 dark:text-gray-400 mt-1">For: ${escapeHtml(rec.reason_intents.join(", "))}</p>`
    : "";
  return `
    <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
      <div class="flex flex-wrap items-center gap-2 mb-1">
        <h4 class="text-sm font-semibold text-gray-900 dark:text-white">${escapeHtml(rec.display_name)}</h4>
        ${_intentPriorityBadge(rec.priority)}
        ${aiBadge}
        <button type="button" onclick="showPanel('${rec.panel}')"
                class="ml-auto text-xs font-medium text-blue-700 dark:text-blue-400 hover:underline">
          ${escapeHtml(rec.panel_label)} &rarr;
        </button>
      </div>
      <p class="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">${escapeHtml(rec.why)}</p>
      ${reasons}
    </div>`;
}

/** Render the recommendation cards, grouped by priority. */
function renderIntentRecommendations(data) {
  const summaryEl = document.getElementById("intent-summary");
  const cardsEl = document.getElementById("intent-cards");
  if (!cardsEl) return;

  if (summaryEl) {
    summaryEl.innerHTML = data.summary
      ? `<p class="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">${escapeHtml(data.summary)}</p>`
      : "";
  }

  const recs = data.recommendations || [];
  if (recs.length === 0) {
    cardsEl.innerHTML =
      '<p class="text-sm text-gray-500 dark:text-gray-400">No checks matched that goal for this dataset.</p>';
    return;
  }

  const critical = recs.filter((r) => r.priority === "critical");
  const rest = recs.filter((r) => r.priority !== "critical");
  let html = "";
  if (critical.length) {
    html += '<h3 class="text-sm font-semibold text-gray-900 dark:text-white">Check these first</h3>';
    html += critical.map(_intentCardHtml).join("");
  }
  if (rest.length) {
    html += '<h3 class="text-sm font-semibold text-gray-900 dark:text-white pt-2">Worth checking</h3>';
    html += rest.map(_intentCardHtml).join("");
  }
  cardsEl.innerHTML = html;
}

/**
 * Restore a previous recommendation when the panel is reopened.
 * Deliberately not routed through _panelCacheMap: that path feeds
 * renderWorkspaceResults(), which expects metric-result shape.
 */
function _restoreIntentFromCache() {
  return fetch("/cached-result/intent")
    .then((r) => (r.ok ? r.json() : null))
    .then((resp) => {
      if (resp && resp.data && resp.data.recommendations) {
        renderIntentRecommendations(resp.data);
      }
    })
    .catch(() => {});
}
```

- [ ] **Step 4: Wire the restore into `showPanel`**

In `showPanel` (`inspector.js:390`), after the existing `_restoreCachedResult(panelId);` call:

```javascript
  // Check for cached results and restore them
  _restoreCachedResult(panelId);

  if (panelId === "intent" && !_intentRestored) {
    _intentRestored = true;
    _restoreIntentFromCache();
  }
```

Declare the guard beside the other module-level state near the top of the file, next to `_readinessReportLoaded`:

```javascript
let _intentRestored = false;
```

And reset it in `initWorkspace()` alongside the readiness reset (`inspector.js:6826`), so a dataset switch refetches:

```javascript
  _readinessReportLoaded = false;
  _intentRestored = false;
```

- [ ] **Step 5: Wire the two trigger points**

In `loadDataOverview`, at the end of the `if (data.success) { ... }` branch (after `renderWorkspaceHistograms(...)`, around line 4699):

```javascript
      maybeShowIntentModal();
```

In `renderGlobusSummary` (`inspector.js:1624`), at the very end of the function — **after** the `if (data.error)` early return at 1629-1635, so the modal never opens over an error or a spinner:

```javascript
  maybeShowIntentModal();
```

- [ ] **Step 6: Run the security tests**

Run: `PYTHONPATH=. pytest tests/unit/test_inspector_js_security.py -v`
Expected: PASS, including the pre-existing marker-sliced tests — which confirms the new block did not land inside a slice window.

- [ ] **Step 7: Check JS syntax and formatting**

```bash
node --check web/static/js/inspector.js
npx --yes prettier@3 --check web/static/js
```

Expected: no output from `node --check`; Prettier reports all matched files use the correct style. If Prettier complains, run `npx --yes prettier@3 --write web/static/js/inspector.js` and confirm the diff touches only your new lines.

- [ ] **Step 8: Run the whole suite**

Run: `PYTHONPATH=. pytest tests/ -q`
Expected: all green.

- [ ] **Step 9: Stage**

```bash
git add web/static/js/inspector.js tests/unit/test_inspector_js_security.py
# Authorised later only:
# git commit -m "Add intent modal and recommendation rendering"
```

---

## Task 8: Manual verification

**Files:** none — this task changes nothing.

- [ ] **Step 1: Start the app**

```bash
flask --app 'web:create_app()' run --debug
```

No Redis or Celery worker is needed: this feature dispatches no tasks.

- [ ] **Step 2: Verify the no-LLM path**

Upload `demos/` sample `adult.csv` (or any CSV). Confirm:
- the modal appears **after** the summary statistics have rendered, not over the spinner
- ticking a goal enables "Get recommendations"; unticking everything disables it again
- submitting shows the Intent panel with cards, critical group first
- each card's panel link switches to the right panel
- the sidebar entry returns to the panel, and the cards are still there

- [ ] **Step 3: Verify the reset**

Upload a second file. Confirm the modal appears again for the new dataset and the Intent panel does not show the previous dataset's cards.

- [ ] **Step 4: Verify Skip is remembered**

Upload a third file, press Skip, then navigate between panels. Confirm the modal does not reappear.

- [ ] **Step 5: Verify the LLM path (needs a key)**

Configure a key in AI Explanation Settings **without reloading the page**, then upload a new file. Confirm the modal still appears — this is the first-run path that the earlier LLM-gated design would have broken. Submit and confirm the rationales are dataset-specific and any AI-suggested cards carry the purple badge.

- [ ] **Step 6: Verify graceful degradation**

Set an invalid API key, upload a file, and submit an intent. Confirm the panel still shows the curated list with generic descriptions rather than an error state.

- [ ] **Step 7: Final gate**

```bash
PYTHONPATH=. pytest tests/
flake8 --config=tox.ini aidrin/ web/ worker/
npx --yes prettier@3 --check web/static/css web/static/js
```

Expected: all three clean. Report the actual output; do not claim success without it.

---

## Notes for the executor

- **Nothing is committed.** Every task stages only. The commit lines are written out for when the user authorises them; at that point, branch off `develop` first.
- **If a test in Task 1 or 2 fails on a metric key**, the catalog is out of step with `METRIC_REGISTRY` — fix the catalog, never the assertion (AGENTS.md: do not weaken tests to make a change pass).
- **The editorial content of `INTENT_PROFILES` is a considered decision**, documented in the spec's "Editorial decisions behind the table". If you think a metric is in the wrong tier, raise it rather than silently changing it.
- **`differential_privacy` being in no profile is intentional**, and a test enforces it.
- **Deliberate deviation from the spec's testing section.** The spec proposed guarding LLM-dependent
  integration tests with `pytest.mark.skipif` so they show as skipped rather than silently passing
  when `openai` is absent. This plan does better: because `/intent/recommend` is always registered
  and the LLM is reached through the `_llm_config` / `_call_llm` seams, Task 4 monkeypatches those
  seams instead. Every test therefore runs in every CI job and no skip guard is needed. If you find
  yourself adding a `skipif` to `tests/integration/test_intent_routes.py`, something has gone wrong
  — the route should never require `openai`.
- **Two code blocks use four-backtick fences** (Task 3, steps 1 and 3). They contain literal triple
  backticks in Python strings, because the parser strips markdown code fences from LLM replies. Do
  not "normalise" those fences to three backticks; it truncates the block.
