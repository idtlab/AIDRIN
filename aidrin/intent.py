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

from typing import Any, Dict, List, Optional, Set, Tuple

CRITICAL = "critical"
RECOMMENDED = "recommended"

# Priority ordering, highest first. Used when several intents disagree.
_PRIORITY_RANK = {CRITICAL: 0, RECOMMENDED: 1}

# Profile file format (see recommendations_from_profile). Bump PROFILE_VERSION
# only for a breaking change to the file shape. Saved as the "profile_version"
# key (web/routes/intent.py's load_profile() also accepts a legacy "version"
# key as an alias on load). This is distinct from -- and never gated on --
# the "aidrin_version" also saved in the file, which just records which
# AIDRIN build produced it and is informational only.
PROFILE_VERSION = 1
MAX_PROFILE_NAME = 80


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

# Value for the goal lists' extra "Other / load a custom profile" checkbox
# (web/templates/_components/intent_modal.html and
# web/templates/_panels/_intent.html). Deliberately not a member of
# INTENT_KEYS: it is never a real goal, so /intent/recommend already ignores
# it (it only keeps keys that are in INTENT_KEYS), and the front end's
# _selectedIntents() filters it out before that request is even made.
CUSTOM_PROFILE_OPTION_VALUE = "__custom__"


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
    "variable_unit_validation",
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
    "variable_unit_validation": "Unit Metadata Audit",
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
    "variable_unit_validation": "Audit unit metadata for every logical variable and apply an optional canonical sidecar.",
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
    "variable_unit_validation": "variable-unit-validation",
    "fair_assessment": "fair-assessment",
}

# The `name` attribute of the checkbox that runs each metric, in the panel
# PANEL_BY_METRIC assigns it to. These do not match the metric keys above --
# they are the literal HTML checkbox names, scraped from the panel templates
# (grep `name="..."` in web/templates/_panels/*.html) rather than derived,
# since a guess here would be silently wrong. Guarded against drift by
# tests/unit/test_intent.py::test_checkbox_names_exist_in_their_panel_template.
# fair_assessment has no metric checkbox -- its panel is a metadata upload
# form -- so it maps to None.
CHECKBOX_BY_METRIC: Dict[str, Optional[str]] = {
    "completeness": "completeness",
    "row_level_completeness": "row level completeness",
    "feature_coverage_ratio": "feature coverage ratio",
    "temporal_completeness": "temporal completeness",
    "null_count_trend": "null count trend",
    "outliers": "outliers",
    "outliers_custom": "custom_outliers",
    "duplicity": "duplicity",
    "duplicity_by_features": "duplicate detection by features",
    "constant_feature_count": "constant feature count",
    "max_pairwise_correlation": "max pairwise correlation",
    "skewness": "skewness",
    "kurtosis": "kurtosis",
    "file_reference_validation": "file_reference_validation",
    "correlations": "correlations",
    "feature_relevance": "feature relevancy",
    "class_imbalance": "class imbalance",
    "statistical_rates": "statistical rate",
    "representation_rate": "representation rate",
    "conditional_demographic_disparity": "conditional demographic disparity",
    "k_anonymity": "k-anonymity",
    "l_diversity": "l-diversity",
    "t_closeness": "t-closeness",
    "entropy_risk": "entropy risk",
    "single_attribute_risk": "single attribute risk score",
    "multiple_attribute_risk": "multiple attribute risk score",
    "differential_privacy": "differential privacy",
    "hipaa_compliance": "hipaa identifier scan",
    "variable_unit_validation": "variable_unit_validation",
    "fair_assessment": None,
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
    "variable-unit-validation": "Unit Metadata Audit",
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


def _recommendation_sort_key(rec: Dict[str, Any]) -> Tuple[int, int, str, str]:
    """Shared ordering for recommend_metrics and recommendations_from_profile:
    critical first, then by how many intents agree (descending), then panel,
    then metric key, for determinism."""
    return (
        _PRIORITY_RANK[rec["priority"]],
        -len(rec["reason_intents"]),
        rec["panel"],
        rec["metric"],
    )


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
            "input_name": CHECKBOX_BY_METRIC[metric],
        }
        for metric, priority in best.items()
    ]

    results.sort(key=_recommendation_sort_key)
    return results


def recommendations_from_profile(
    profile: Any,
    dataset_profile: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """Turn a saved profile file into recommendation cards.

    Mirrors recommend_metrics's output shape exactly (same 9 keys, same
    ordering rule), with source="profile" and reason_intents=[] since a
    profile is an explicit list, not something intents agreed on.

    Never raises: a non-dict profile, missing keys, or critical/recommended
    being anything but a list all yield ([], [], []).
    """
    if not isinstance(profile, dict):
        return [], [], []

    critical_raw = profile.get(CRITICAL)
    recommended_raw = profile.get(RECOMMENDED)
    if not isinstance(critical_raw, list) or not isinstance(recommended_raw, list):
        return [], [], []

    valid_keys = all_metric_keys()
    dropped_unknown: Set[str] = set()
    dropped_inapplicable: Set[str] = set()
    best: Dict[str, str] = {}

    # Apply recommended first, then critical, so a metric listed in both
    # tiers resolves to critical (the later assignment wins).
    for priority, raw_list in ((RECOMMENDED, recommended_raw), (CRITICAL, critical_raw)):
        for metric in raw_list:
            if not isinstance(metric, str):
                continue
            if metric not in valid_keys:
                dropped_unknown.add(metric)
                continue
            if not is_applicable(metric, dataset_profile):
                dropped_inapplicable.add(metric)
                continue
            best[metric] = priority

    results = [
        {
            "metric": metric,
            "display_name": DISPLAY_NAMES[metric],
            "panel": PANEL_BY_METRIC[metric],
            "panel_label": PANEL_LABELS[PANEL_BY_METRIC[metric]],
            "priority": priority,
            "source": "profile",
            "reason_intents": [],
            "why": _fallback_why(metric),
            "input_name": CHECKBOX_BY_METRIC[metric],
        }
        for metric, priority in best.items()
    ]
    results.sort(key=_recommendation_sort_key)
    return results, sorted(dropped_unknown), sorted(dropped_inapplicable)
