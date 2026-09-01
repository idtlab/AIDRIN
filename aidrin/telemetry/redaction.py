"""What a metric result is allowed to contribute to a tracking server.

AIDRIN's whole purpose is finding PII and PHI, so its results are full of it:
matched SSNs and email addresses, duplicate-group cell values, flagged outlier
values with their locations, resolved file paths, and sensitive-attribute values
used as dictionary keys.  Every metric's ``except`` branch also stores
``str(exc)``, and pandas and numpy messages routinely quote column names and
offending values.

This module is therefore an **allowlist, not a denylist**.  A metric contributes
only the scalars named in :data:`HEADLINE`, reached by an explicit path.  A
metric with no entry contributes nothing.  Enumerating bad keys instead was
tried and rejected: it already missed ``normalized_value`` and ``resolved_path``
in ``file_reference_validation``, on a metric the skill advertises.

Two further rules, both load-bearing:

* A projection yields **numbers only**.  A string could carry a cell value.
* Non-finite numbers are dropped rather than logged.  Constant columns make
  skewness, kurtosis and correlation produce NaN, and MLflow renders a stored
  NaN as ``0`` — a readiness chart reading "correlation 0" for *undefined* is
  worse than a gap.
"""

import hashlib
import math
import re

# Registry category -> the dimension segment of a metric key.
#
# Keys are ``aidrin.<dimension>.<name>``, matching the ``aidrin.*`` tag prefix so
# everything AIDRIN emits shares one namespace.  (Metrics and tags are separate
# namespaces in MLflow, so a metric ``aidrin.quality.completeness`` does not
# collide with a tag ``aidrin.session_id``.)  The dimension lets a wide runs table
# be filtered to one readiness dimension, and it must agree with the metric's
# METRIC_REGISTRY category — a test enforces that, because a key renamed later
# orphans its history under the old name.
NAMESPACE = {
    "data-quality": "quality",
    "data-structure": "structure",
    "impact-of-data-on-AI": "impact",
    "fairness-and-bias": "fairness",
    "data-governance": "governance",
}

# metric key -> {mlflow metric key: path into the result dict}
#
# Paths are tuples so nested scores can be reached without any generic
# traversal: a generic flattener over column-keyed dicts would emit column names
# as metric keys, which both leaks them and collides after sanitisation
# (``Income (USD)`` and ``Income [USD]`` sanitise to the same key, and MLflow
# silently appends to the same series rather than erroring).
HEADLINE = {
    "completeness": {"aidrin.quality.completeness": ("Overall Completeness",)},
    "duplicity": {
        "aidrin.quality.duplicity": (
            "Duplicity scores",
            "Overall duplicity of the dataset",
        )
    },
    "outliers": {
        "aidrin.quality.outliers": ("Outlier scores", "Overall outlier score")
    },
    # The runner nests the score under a wrapper key that the metric module
    # itself does not show; paths are verified against real output by
    # TestDeclaredPathsResolveAgainstRealResults.
    "class_imbalance": {
        "aidrin.fairness.class_imbalance": (
            "Imbalance degree",
            "Imbalance Degree score",
        )
    },
    "k_anonymity": {"aidrin.governance.k_anonymity": ("k-Value",)},
    "l_diversity": {"aidrin.governance.l_diversity": ("l-Value",)},
    "t_closeness": {"aidrin.governance.t_closeness": ("t-Value",)},
    "entropy_risk": {"aidrin.governance.entropy_risk": ("Entropy-Value",)},
    "multiple_attribute_risk": {
        "aidrin.governance.multiple_attribute_risk": ("Dataset Risk Score",)
    },
    "max_pairwise_correlation": {
        "aidrin.structure.max_pairwise_correlation": ("Max Pairwise Correlation",)
    },
    "skewness": {"aidrin.structure.max_abs_skewness": ("Max Absolute Skewness",)},
    "kurtosis": {
        "aidrin.structure.max_abs_kurtosis": ("Max Absolute Excess Kurtosis",)
    },
    "constant_feature_count": {
        "aidrin.structure.constant_feature_count": ("Constant feature count",),
        "aidrin.structure.total_features": ("Total features",),
    },
    "variable_unit_validation": {
        "aidrin.structure.unit_coverage": ("coverage_score",),
        "aidrin.structure.unit_validity": ("validity_score",),
    },
    "feature_coverage_ratio": {
        "aidrin.quality.feature_coverage_ratio": ("Feature Coverage Ratio (%)",),
        "aidrin.quality.covered_features": ("Covered features",),
    },
    "temporal_completeness": {
        "aidrin.quality.temporal_completeness": ("Temporal Completeness (%)",),
        "aidrin.quality.present_intervals": ("Present intervals",),
    },
    "row_level_completeness": {
        "aidrin.quality.row_level_completeness": ("Row-Level Completeness (%)",),
        "aidrin.quality.complete_rows": ("Complete rows",),
    },
}

# Metrics whose headline numbers have to be computed rather than read out.
# Each returns {mlflow key: number}; none may return anything derived from a
# cell value, a column name, or an exception message.
_DERIVED = {}


def _derived(metric_key, *keys):
    """Register a computed projection, declaring the keys it may emit.

    The keys are declared here rather than in a second table so there is one
    place to change: a key added to the function but missing from a parallel
    list would silently escape the namespace check.
    """

    def register(fn):
        _DERIVED[metric_key] = (keys, fn)
        return fn

    return register


@_derived(
    "hipaa_compliance",
    "aidrin.governance.hipaa_flagged_columns",
    "aidrin.governance.hipaa_total_flags",
)
def _hipaa(result):
    """Counts only.

    ``detect_hipaa_identifiers`` returns ``{column: {"total_flags": int,
    "potential_types_detected": [...], "examples": [...]}}`` where ``examples``
    holds up to five **verbatim matched values** — SSNs, emails, phone numbers,
    medical record numbers.  Neither the column names nor the examples may leave
    this function.
    """
    if not isinstance(result, dict) or "Error" in result:
        return {}
    columns = [v for v in result.values() if isinstance(v, dict) and "total_flags" in v]
    # An empty result means the scan found nothing, which is a finding. Reporting
    # zero distinguishes it from a metric that never ran; only an error reports
    # nothing at all.
    return {
        "aidrin.governance.hipaa_flagged_columns": len(columns),
        "aidrin.governance.hipaa_total_flags": sum(
            c.get("total_flags", 0) for c in columns
        ),
    }


@_derived(
    "duplicity_by_features",
    "aidrin.quality.duplicity_by_features",
    "aidrin.quality.duplicate_rows",
)
def _duplicity_by_features(result):
    """Counts and the percentage only.

    ``Duplicate groups`` carries the actual joint cell values of each duplicated
    group, so it never leaves the machine.
    """
    if not isinstance(result, dict):
        return {}
    out = {}
    if "Duplicate percentage" in result:
        out["aidrin.quality.duplicity_by_features"] = result["Duplicate percentage"]
    if "Duplicate count" in result:
        out["aidrin.quality.duplicate_rows"] = result["Duplicate count"]
    return out


@_derived(
    "file_reference_validation",
    "aidrin.quality.invalid_file_references",
    "aidrin.quality.valid_file_references",
)
def _file_reference_validation(result):
    """Counts only — ``Invalid references`` carries dataset file paths."""
    if not isinstance(result, dict):
        return {}
    summary = result.get("Summary")
    if not isinstance(summary, dict):
        return {}
    out = {}
    for name, key in (
        ("aidrin.quality.invalid_file_references", "invalid_references"),
        ("aidrin.quality.valid_file_references", "valid_references"),
    ):
        if key in summary:
            out[name] = summary[key]
    return out


@_derived("single_attribute_risk", "aidrin.governance.max_single_attribute_risk")
def _single_attribute_risk(result):
    """The worst column's mean risk.

    The scores are keyed by evaluated column, so there is no single value to
    read out. The maximum is the comparable number, and unlike the per-column
    breakdown it carries no column name.
    """
    if not isinstance(result, dict):
        return {}
    stats = result.get("Descriptive statistics of the risk scores")
    if not isinstance(stats, dict):
        return {}
    means = [
        v["mean"] for v in stats.values()
        if isinstance(v, dict) and isinstance(v.get("mean"), (int, float))
    ]
    if not means:
        return {}
    return {"aidrin.governance.max_single_attribute_risk": max(means)}


def _extreme(mapping, reduce=max, transform=abs):
    """Reduce a column-keyed mapping of numbers to one value.

    Per-column results cannot become metric keys, because the keys would be
    column names. An aggregate over them is comparable across runs and carries
    no name.
    """
    values = [
        transform(v)
        for v in (mapping or {}).values()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    return reduce(values) if values else None


@_derived("correlations", "aidrin.impact.max_correlation")
def _correlations(result):
    """Strongest absolute correlation between any pair of the selected columns."""
    if not isinstance(result, dict):
        return {}
    value = _extreme(result.get("Correlation Scores"))
    return {} if value is None else {"aidrin.impact.max_correlation": value}


@_derived("feature_relevance", "aidrin.impact.max_target_correlation")
def _feature_relevance(result):
    """Strongest absolute correlation of any feature to the target."""
    if not isinstance(result, dict):
        return {}
    value = _extreme(result.get("Pearson Correlation to Target"))
    return {} if value is None else {"aidrin.impact.max_target_correlation": value}


@_derived("statistical_rates", "aidrin.fairness.max_statistical_disparity")
def _statistical_rates(result):
    """Largest disparity between groups.

    ``TSD scores`` is the total statistical disparity the metric already
    computes. ``Statistical Rates`` is nested group -> class -> rate, and its
    group names are sensitive-attribute values, so only the disparity is
    reported.
    """
    if not isinstance(result, dict):
        return {}
    value = _extreme(result.get("TSD scores"))
    if value is None:
        # Fall back to the spread across the per-class rates.
        rates = [
            rate
            for group in (result.get("Statistical Rates") or {}).values()
            if isinstance(group, dict)
            for rate in group.values()
            if isinstance(rate, (int, float)) and not isinstance(rate, bool)
        ]
        if not rates:
            return {}
        value = max(rates) - min(rates)
    return {"aidrin.fairness.max_statistical_disparity": value}


@_derived("representation_rate", "aidrin.fairness.max_representation_imbalance")
def _representation_rate(result):
    """Furthest any group ratio sits from parity, where 1.0 is parity."""
    if not isinstance(result, dict):
        return {}
    value = _extreme(result.get("Probability ratios"), transform=lambda v: abs(v - 1.0))
    return {} if value is None else {"aidrin.fairness.max_representation_imbalance": value}


@_derived("null_count_trend", "aidrin.quality.max_batch_null_count")
def _null_count_trend(result):
    """Worst batch's null count, for spotting a quality regression."""
    if not isinstance(result, dict):
        return {}
    counts = []
    for batch in (result.get("Null counts by batch") or {}).values():
        if isinstance(batch, dict):
            counts.extend(
                v for v in batch.values()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            )
        elif isinstance(batch, (int, float)) and not isinstance(batch, bool):
            counts.append(batch)
    return {"aidrin.quality.max_batch_null_count": max(counts)} if counts else {}


@_derived(
    "differential_privacy",
    "aidrin.governance.max_dp_mean_shift",
    "aidrin.governance.max_dp_variance_shift",
)
def _differential_privacy(result):
    """Largest relative shift a feature's mean took from added noise.

    The result keys embed column names (``Mean of feature age(before noise)``),
    so they are read but never emitted.
    """
    if not isinstance(result, dict):
        return {}
    shifts = {"Mean": [], "Variance": []}
    for key, before in result.items():
        if not (isinstance(key, str) and "(before noise)" in key):
            continue
        after = result.get(key.replace("(before noise)", "(after noise)"))
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            continue
        if not before:
            continue
        for kind in shifts:
            if key.startswith(kind):
                shifts[kind].append(abs(after - before) / abs(before))

    out = {}
    if shifts["Mean"]:
        out["aidrin.governance.max_dp_mean_shift"] = max(shifts["Mean"])
    if shifts["Variance"]:
        out["aidrin.governance.max_dp_variance_shift"] = max(shifts["Variance"])
    return out


@_derived(
    "outliers_custom",
    "aidrin.quality.max_custom_outlier_rate",
    "aidrin.quality.custom_outliers",
)
def _outliers_custom(result):
    """Worst rule's outlier rate, and the total flagged.

    Summaries are keyed by rule id, which users choose, so the ids are read but
    never emitted.
    """
    if not isinstance(result, dict):
        return {}
    summaries = [
        v for v in (result.get("Rule summaries") or {}).values() if isinstance(v, dict)
    ]
    if not summaries:
        return {}
    rates = [
        v["outlier_rate"] for v in summaries
        if isinstance(v.get("outlier_rate"), (int, float))
    ]
    counts = [
        v["outlier"] for v in summaries if isinstance(v.get("outlier"), (int, float))
    ]
    out = {}
    if rates:
        out["aidrin.quality.max_custom_outlier_rate"] = max(rates)
    if counts:
        out["aidrin.quality.custom_outliers"] = sum(counts)
    return out


# metric key -> path to the column-keyed mapping inside its result.
#
# These are logged on the metric run alongside its overall score, never rolled
# up to the assessment run: two datasets with different schemas would turn the
# assessment Compare view into a sparse grid, which is the one place where keys
# have to line up across runs.
PER_COLUMN = {
    "completeness": ("Completeness scores",),
    "outliers": ("Outlier scores",),
    "skewness": ("Skewness",),
    "kurtosis": ("Kurtosis",),
    "correlations": ("Correlation Scores",),
    "feature_relevance": ("Pearson Correlation to Target",),
    "representation_rate": ("Probability ratios",),
}

# Aggregates that live inside the per-column mapping rather than beside it.
_AGGREGATE_KEYS = {
    "overall outlier score",
    "overall duplicity of the dataset",
    "overall completeness",
}

# MLflow permits spaces in a key, but a pair name such as "age vs cholesterol"
# reads poorly in a chart legend and is awkward to quote in a search filter, so
# separators are normalised to underscores.
_KEY_CHARSET = re.compile(r"[^A-Za-z0-9_\-./]")
_KEY_RUNS = re.compile(r"_{2,}")
_MAX_KEY = 250


def _column_key(metric_key, column, taken):
    """A legal, unique MLflow key for one column of one metric.

    MLflow accepts alphanumerics, underscore, dash, dot, slash and space, and
    caps a key at 250 characters. Sanitising can make two distinct columns
    collide (``Income (USD)`` and ``Income [USD]``), and MLflow does not reject a
    repeated key: it appends another step to the same series, silently merging
    two columns into one chart. A short digest of the original name keeps them
    apart.
    """
    prefix = f"aidrin.column.{metric_key}."
    safe = _KEY_RUNS.sub("_", _KEY_CHARSET.sub("_", str(column))).strip("_")
    room = _MAX_KEY - len(prefix)
    key = prefix + safe[:room]

    if key in taken and taken[key] != column:
        digest = hashlib.sha256(str(column).encode("utf-8")).hexdigest()[:6]
        key = prefix + safe[: max(0, room - 7)] + "_" + digest
    taken[key] = column
    return key


def per_column(metric_key, result):
    """Per-column values for *metric_key*, keyed safely and uniquely.

    Returns an empty dict for a metric with no declared per-column mapping, and
    skips non-finite values for the same reason :func:`project` does: MLflow
    renders a stored NaN as ``0``.
    """
    path = PER_COLUMN.get(metric_key)
    if not path:
        return {}

    mapping = _walk(result, path)
    if not isinstance(mapping, dict):
        return {}

    out, taken = {}, {}
    for column, value in mapping.items():
        if str(column).strip().lower() in _AGGREGATE_KEYS:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        value = float(value)
        if not math.isfinite(value):
            continue
        out[_column_key(metric_key, column, taken)] = value
    return out


def _walk(result, path):
    """Follow *path* into *result*, returning None if it does not resolve."""
    node = result
    for step in path:
        if not isinstance(node, dict) or step not in node:
            return None
        node = node[step]
    return node


def project(metric_key, result):
    """Return the numbers *metric_key* is allowed to contribute.

    Always returns a dict; an undeclared metric, an unresolvable path, a
    non-numeric value and a non-finite value all yield nothing rather than an
    error, because a metric result is allowed to be an ``{"Error": ...}`` dict.
    """
    candidates = {}

    if metric_key in _DERIVED:
        try:
            candidates.update(_DERIVED[metric_key][1](result) or {})
        except Exception:
            return {}

    for mlflow_key, path in HEADLINE.get(metric_key, {}).items():
        value = _walk(result, path)
        if value is not None:
            candidates[mlflow_key] = value

    projected = {}
    for key, value in candidates.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        value = float(value)
        if not math.isfinite(value):
            continue
        projected[key] = value
    return projected


def skipped_keys(metric_key, result):
    """Declared keys that resolved to a non-finite number, for the skip tag."""
    skipped = []
    for mlflow_key, path in HEADLINE.get(metric_key, {}).items():
        value = _walk(result, path)
        if isinstance(value, float) and not math.isfinite(value):
            skipped.append(mlflow_key)
    return sorted(skipped)


# How each readiness dimension is written for people rather than for filters.
DIMENSION_LABELS = {
    "quality": "Data Quality",
    "structure": "Data Structure",
    "impact": "Impact of Data on AI",
    "fairness": "Fairness and Bias",
    "governance": "Data Governance",
}

# Only the names that title-casing gets wrong: "k_anonymity" would become
# "K Anonymity" and "hipaa_compliance" would become "Hipaa Compliance". Every
# other metric reads correctly from its key, so it is not listed here.
METRIC_LABELS = {
    "k_anonymity": "k-Anonymity",
    "l_diversity": "l-Diversity",
    "t_closeness": "t-Closeness",
    "hipaa_compliance": "HIPAA Compliance",
    "row_level_completeness": "Row-Level Completeness",
    "duplicity_by_features": "Duplicity by Features",
    "outliers_custom": "Custom Outliers",
}


def label_for(metric_key):
    """A human-readable label, as ``Pillar: Metric Name``.

    Used as a run description, so that a metric run says which readiness
    dimension it belongs to without the reader having to know the key scheme.
    A metric with no declared dimension (a custom one) gets its name alone.
    """
    name = METRIC_LABELS.get(metric_key) or str(metric_key).replace("_", " ").title()
    dimension = DIMENSION_LABELS.get(dimension_for(metric_key))
    return f"{dimension}: {name}" if dimension else name


def dimension_for(metric_key):
    """The readiness dimension a metric belongs to, or None if it declares none.

    Read from the metric's own declared keys rather than from METRIC_REGISTRY,
    which would make this module import ``aidrin.headless.api`` and close an
    import cycle. A custom metric declares nothing and so has no dimension.
    """
    for declared, mlflow_key in all_metric_keys():
        if declared == metric_key:
            parts = mlflow_key.split(".")
            if len(parts) == 3:
                return parts[1]
    return None


def all_metric_keys():
    """Every ``(metric_key, mlflow_key)`` this module can emit."""
    pairs = [
        (metric_key, mlflow_key)
        for metric_key, keys in HEADLINE.items()
        for mlflow_key in keys
    ]
    pairs += [
        (metric_key, mlflow_key)
        for metric_key, (keys, _fn) in _DERIVED.items()
        for mlflow_key in keys
    ]
    return sorted(pairs)


# ---------------------------------------------------------------------------
# Full-result archiving
# ---------------------------------------------------------------------------
#
# The projection above answers "what may become an MLflow *metric*", and is an
# allowlist because a metric key is compared across runs and must be trustworthy.
# This section answers a different question: "what may be archived as a JSON
# *artifact*", where the point is to keep the per-column detail that never
# becomes a headline score — skewness per column, correlation matrices, outlier
# proportions.
#
# That detail cannot be expressed as an allowlist without re-deriving every
# metric's schema, so redaction here is structural: keep numbers and the shape,
# remove anything that can carry a cell value.  It is weaker than the projection
# allowlist, which is why archiving is off unless explicitly enabled, and why the
# verbatim mode needs a second flag of its own.

# Keys whose contents are raw cell values wherever they appear.  Matched
# case-insensitively as substrings, so ``Invalid references`` also catches
# ``invalid_references_detail`` and similar.
_RAW_VALUE_KEYS = (
    "example",
    "invalid reference",
    "invalid_reference",
    "duplicate group",
    "feature values",
    "preview",
    "export_rows",
    "sample",
    "visualization",
    "graph interpretation",
    "plot",
)

# Keys whose *sub-keys* are cell values (a sensitive attribute's categories, a
# target's classes).  The mapping is replaced by its size.
_VALUE_KEYED = (
    "statistical rate",
    "representation rate",
    "demographic disparity",
    "class distribution",
)

# Keys whose string contents come from a fixed vocabulary rather than the data.
# Kept deliberately tiny: each entry is a promise that the metric can only emit
# values it defined itself.
_SAFE_VOCABULARY_KEYS = ("potential_types_detected",)

# Strings can always carry a cell value: exception messages quote them, and a
# base64 chart is megabytes of noise.  Descriptions are static prose, but keeping
# only "safe" strings would mean maintaining a list of them, so no strings pass.
_REDACTED = "<redacted>"


def _matches(key, needles):
    lowered = str(key).lower()
    return any(n in lowered for n in needles)


def _redact(node, depth=0):
    if depth > 12:
        return _REDACTED

    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            # A scalar under one of these names is a count, not the payload:
            # ``Summary.invalid_references`` is a number, ``Invalid references``
            # is the list of offending rows.  Only the payload is dropped.
            if _matches(key, _RAW_VALUE_KEYS) and not isinstance(
                value, (int, float, bool)
            ):
                continue
            if _matches(key, _SAFE_VOCABULARY_KEYS):
                out[key] = value
                continue
            if _matches(key, _VALUE_KEYED) and isinstance(value, dict):
                out[key] = {"__entries__": len(value)}
                continue
            out[key] = _redact(value, depth + 1)
        return out

    if isinstance(node, (list, tuple)):
        # A list of dicts is usually per-row detail; keep its length, not its rows.
        if any(isinstance(item, dict) for item in node):
            return {"__entries__": len(node)}
        return [_redact(item, depth + 1) for item in node if not isinstance(item, str)]

    if isinstance(node, str):
        return _REDACTED
    return node


def redact_result(metric_key, result):
    """Return *result* with anything that can carry a cell value removed.

    Structural rather than per-metric, so a metric added later is redacted
    without anyone remembering to declare it.  ``metric_key`` is accepted for
    symmetry with :func:`project` and for future per-metric exceptions.
    """
    try:
        return _redact(result)
    except Exception:
        return {"__redaction_failed__": True}
