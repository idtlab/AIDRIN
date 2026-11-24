"""Impact-on-AI section of the readiness report."""

from __future__ import annotations

import pandas as pd

from aidrin.file_handling.file_parser import read_file
from aidrin.report.common import (
    READINESS_MAX_DETAIL_LIST_ITEMS,
    cap_detail_list,
    classify_feature_type,
    finite_kpi_values,
    grade_label,
)
from aidrin.structured_data_metrics.correlation_score import calc_correlations

# Impact-on-AI tuning constants
CORR_MAX_COLUMNS = 25          # cap analysed columns to keep heatmaps readable
CORR_HIGH_CARD_MAX = 50        # drop categorical columns with more unique values
CORR_ID_UNIQUE_RATIO = 0.9     # drop categorical columns that look like IDs
CORR_REDUNDANT_THRESHOLD = 0.8  # |score| at/above which a pair is "redundant"
CORR_LEAKAGE_THRESHOLD = 0.95  # |score| at/above which a pair is "leakage risk"
CORR_ISOLATED_THRESHOLD = 0.1  # max |score| below which a feature is "isolated"


def is_integer_like_numeric(series):
    """True for integer dtypes or float columns whose non-null values are whole numbers."""
    if pd.api.types.is_integer_dtype(series):
        return True
    if not pd.api.types.is_float_dtype(series):
        return False
    non_null = series.dropna()
    if len(non_null) == 0:
        return False
    return bool((non_null % 1 == 0).all())


def prune_columns_for_corr(df):
    """Select columns worth feeding into the all-pairs correlation analysis.

    Drops columns that are useless or pathological for correlation: constants,
    datetimes, ID-like columns (near-unique integer numerics or categoricals),
    and high-cardinality categoricals. Continuous floats stay even when nearly
    unique. Aligns datetime / ID exclusions with
    ``auto_select_governance_columns``. The result is capped at
    ``CORR_MAX_COLUMNS`` (numerical prioritized) to keep the computation and
    heatmaps tractable.

    Returns ``(kept_columns, dropped)`` where *dropped* is a list of
    ``{"feature": str, "reason": str}``.
    """
    n_rows = max(len(df), 1)
    numeric_cols = list(df.select_dtypes(exclude=["object", "string", "category"]).columns)
    categorical_cols = list(df.select_dtypes(include=["object", "string", "category"]).columns)

    kept_numeric = []
    kept_categorical = []
    dropped = []

    for col in numeric_cols:
        series = df[col]
        if classify_feature_type(series) == "datetime":
            dropped.append({"feature": col, "reason": "datetime column"})
            continue
        nunique = series.nunique(dropna=True)
        if nunique <= 1:
            dropped.append({"feature": col, "reason": "constant column"})
        elif (
            nunique / n_rows >= CORR_ID_UNIQUE_RATIO
            and is_integer_like_numeric(series)
        ):
            dropped.append({"feature": col, "reason": "ID-like (near-unique values)"})
        else:
            kept_numeric.append(col)

    for col in categorical_cols:
        nunique = df[col].nunique(dropna=True)
        if nunique <= 1:
            dropped.append({"feature": col, "reason": "constant column"})
        elif nunique / n_rows >= CORR_ID_UNIQUE_RATIO:
            dropped.append({"feature": col, "reason": "ID-like (near-unique values)"})
        elif nunique > CORR_HIGH_CARD_MAX:
            dropped.append({"feature": col, "reason": f"high cardinality ({nunique} categories)"})
        else:
            kept_categorical.append(col)

    # Cap total columns, prioritizing numerical features
    kept = kept_numeric + kept_categorical
    if len(kept) > CORR_MAX_COLUMNS:
        for col in kept[CORR_MAX_COLUMNS:]:
            dropped.append({"feature": col, "reason": "exceeded column cap"})
        kept = kept[:CORR_MAX_COLUMNS]

    return kept, dropped


def pairwise_signals(scores, columns=None):
    """Derive readiness signals from a flat ``{"a vs b": score}`` mapping.

    Collapses the symmetric/asymmetric directional entries into one record per
    unordered pair (keeping the largest-magnitude score), then classifies pairs
    as redundant or leakage-risk and flags features that are not meaningfully
    related to anything else ("isolated").

    *columns* should be the kept analysis columns. Connectivity is seeded to
    ``0.0`` for each so columns that never appear in a scored pair (e.g. a lone
    numeric when ``calc_correlations`` emits no cross-type pairs) still count as
    isolated rather than informative.
    """
    pair_max = {}
    for key, val in scores.items():
        if " vs " not in key or not isinstance(val, (int, float)):
            continue
        a, b = key.split(" vs ", 1)
        if a == b:
            continue
        ukey = tuple(sorted([a, b]))
        abs_score = abs(val)
        if ukey not in pair_max or abs_score > pair_max[ukey]["abs_score"]:
            pair_max[ukey] = {
                "a": ukey[0],
                "b": ukey[1],
                "score": round(float(val), 3),
                "abs_score": abs_score,
            }

    pairs = list(pair_max.values())
    pairs.sort(key=lambda p: p["abs_score"], reverse=True)

    leakage = [
        {"a": p["a"], "b": p["b"], "score": p["score"]}
        for p in pairs
        if p["abs_score"] >= CORR_LEAKAGE_THRESHOLD
    ]
    redundant = [
        {"a": p["a"], "b": p["b"], "score": p["score"]}
        for p in pairs
        if CORR_REDUNDANT_THRESHOLD <= p["abs_score"] < CORR_LEAKAGE_THRESHOLD
    ]
    top = [{"a": p["a"], "b": p["b"], "score": p["score"]} for p in pairs[:8]]

    # Per-feature connectivity: the strongest relationship each feature has.
    # Seed kept columns at 0.0 so unpaired columns are treated as isolated.
    connectivity = {str(col): 0.0 for col in (columns or [])}
    for p in pairs:
        connectivity[p["a"]] = max(connectivity.get(p["a"], 0.0), p["abs_score"])
        connectivity[p["b"]] = max(connectivity.get(p["b"], 0.0), p["abs_score"])
    isolated = sorted(
        f for f, c in connectivity.items() if c < CORR_ISOLATED_THRESHOLD
    )

    return {
        "redundant": redundant,
        "leakage": leakage,
        "top": top,
        "isolated": isolated,
    }


def build_impact_on_ai_section(file_info, include_visualizations=False):
    """Compute the Impact-on-AI portion of the readiness report.

    Runs an automated, non-interactive all-pairs correlation analysis (numerical
    via vectorized pandas correlation, categorical via Theil's U) over a pruned,
    capped set of columns, then derives redundancy / leakage / isolation signals.

    Returns a JSON-serializable dict, or ``{"error": str}`` on failure.
    """
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]

    kept, dropped = prune_columns_for_corr(df)
    dropped_capped, dropped_meta = cap_detail_list(
        dropped, READINESS_MAX_DETAIL_LIST_ITEMS
    )
    if len(kept) < 2:
        return {
            "error": "Not enough usable columns for correlation analysis after pruning.",
            "columns_analyzed": len(kept),
            "columns_dropped": dropped_capped,
        }

    corr = calc_correlations(kept, file_info, include_visualization=include_visualizations)
    if isinstance(corr, dict) and "Message" in corr:
        return {"error": corr["Message"], "columns_dropped": dropped_capped}

    scores = corr.get("Correlation Scores", {}) if isinstance(corr, dict) else {}
    signals = pairwise_signals(scores, columns=kept)
    cat = corr.get("Correlations Analysis Categorical", {}) or {}
    num = corr.get("Correlations Analysis Numerical", {}) or {}

    leakage_pairs = signals["leakage"]
    redundant_pairs = signals["redundant"]
    isolated_features = signals["isolated"]
    top_pairs = signals["top"]
    n_kept = len(kept)

    leakage_kpi = 1.0 if not leakage_pairs else max(0.0, 1.0 - len(leakage_pairs) / 5.0)
    redundancy_kpi = max(0.0, 1.0 - min(len(redundant_pairs) / 10.0, 1.0))
    informativeness_kpi = (
        max(0.0, 1.0 - len(isolated_features) / n_kept) if n_kept else None
    )

    kpis = [
        {
            "id": "leakage_safety",
            "label": "Leakage safety",
            "value": leakage_kpi,
            "status": "good" if not leakage_pairs else ("warning" if len(leakage_pairs) < 3 else "poor"),
            "hint": (
                f"No pairs with |score| ≥ {CORR_LEAKAGE_THRESHOLD}; "
                f"{len(leakage_pairs)} leakage-risk pair(s) found."
            ),
            "raw_count": len(leakage_pairs),
        },
        {
            "id": "redundancy",
            "label": "Redundancy",
            "value": redundancy_kpi,
            "status": grade_label(redundancy_kpi),
            "hint": (
                f"1 − min(redundant pairs / 10, 1); "
                f"{len(redundant_pairs)} pair(s) with |score| ≥ {CORR_REDUNDANT_THRESHOLD}."
            ),
            "raw_count": len(redundant_pairs),
        },
        {
            "id": "informativeness",
            "label": "Informativeness",
            "value": informativeness_kpi,
            "status": grade_label(informativeness_kpi),
            "hint": (
                f"Share of analyzed features with a strong relationship "
                f"(max |score| ≥ {CORR_ISOLATED_THRESHOLD})."
            ),
            "raw_count": len(isolated_features),
        },
    ]

    present = finite_kpi_values(kpis)
    grade = sum(present) / len(present) if present else None

    return {
        "grade": grade,
        "grade_status": grade_label(grade),
        "columns_analyzed": n_kept,
        "auto_selection": {
            "columns_selected": kept,
            "selection_criteria": {
                "columns_analyzed": {
                    "rule": (
                        f"Prune constants, datetime columns, ID-like integer "
                        f"numerics and categoricals (unique ratio ≥ "
                        f"{CORR_ID_UNIQUE_RATIO}), and high-cardinality "
                        f"categoricals (>{CORR_HIGH_CARD_MAX} categories); "
                        f"cap at {CORR_MAX_COLUMNS} columns "
                        "(numerical prioritized)."
                    ),
                    "selected": kept,
                    "excluded": dropped_capped,
                    "excluded_meta": dropped_meta,
                },
                "thresholds": {
                    "redundant_threshold": CORR_REDUNDANT_THRESHOLD,
                    "leakage_threshold": CORR_LEAKAGE_THRESHOLD,
                    "isolated_threshold": CORR_ISOLATED_THRESHOLD,
                },
            },
        },
        "kpis": kpis,
        "needs_attention": {
            "leakage_pairs": leakage_pairs,
            "redundant_pairs": redundant_pairs,
            "isolated_features": isolated_features,
        },
        "top_pairs": top_pairs,
        "columns_dropped": dropped_capped,
        "redundant_pairs": redundant_pairs,
        "leakage_pairs": leakage_pairs,
        "isolated_features": isolated_features,
        "details": {
            "categorical_visualization": cat.get(
                "Correlations Analysis Categorical Visualization"
            ) if include_visualizations else None,
            "numerical_visualization": num.get(
                "Correlations Analysis Numerical Visualization"
            ) if include_visualizations else None,
            "numerical_method": num.get("Method"),
            "visualizations_deferred": not include_visualizations,
        },
        "visualizations_deferred": not include_visualizations,
    }
