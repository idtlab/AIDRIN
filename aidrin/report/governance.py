"""Data Governance section of the readiness report."""

from __future__ import annotations

import math

import pandas as pd

from aidrin.file_handling.file_parser import read_file
from aidrin.report.common import (
    READINESS_MAX_DETAIL_LIST_ITEMS,
    cap_detail_list,
    classify_feature_type,
    finite_kpi_values,
    grade_label,
)
from aidrin.report.fairness import (
    auto_select_fairness_columns,
    fairness_name_hint_score,
)
from aidrin.structured_data_metrics.add_noise import return_noisy_stats
from aidrin.structured_data_metrics.hipaa_compliance import detect_hipaa_identifiers
from aidrin.structured_data_metrics.privacy_measure import (
    compute_entropy_risk,
    compute_k_anonymity,
    compute_l_diversity,
    compute_t_closeness,
    generate_multiple_attribute_MM_risk_scores_groupby,
    generate_single_attribute_MM_risk_scores_groupby,
)

GOV_QI_MIN_UNIQUE = 2
GOV_QI_MAX_UNIQUE = 50
GOV_QI_MAX_COUNT = 4
GOV_ID_UNIQUE_RATIO = 0.9
GOV_NUMERIC_QI_MAX_UNIQUE = 20
GOV_MM_QI_MAX_UNIQUE = 100
GOV_MISSING_MAX = 0.20
GOV_SENSITIVE_MIN_UNIQUE = 2
GOV_SENSITIVE_MAX_UNIQUE = 30
GOV_HIPAA_MAX_COLUMNS = 40
GOV_HIPAA_MISSING_MAX = 0.50
GOV_DP_MAX_FEATURES = 2
GOV_DP_EPSILON = 0.1
GOV_SMALL_SAMPLE = 30
GOV_WORST_GROUPS_MAX = 5

GOV_K_GOOD = 5
GOV_K_WARNING = 2
GOV_L_GOOD = 3
GOV_L_WARNING = 2
GOV_T_GOOD = 0.10
GOV_T_WARNING = 0.20
GOV_MM_SINGLE_GOOD = 0.3
GOV_MM_SINGLE_WARNING = 0.6
GOV_MM_MULTI_GOOD = 0.5
GOV_MM_MULTI_WARNING = 0.8

GOV_QI_NAME_HINTS = (
    "zip", "postal", "gender", "sex", "age", "race", "ethnic", "city",
    "state", "country", "birth", "dob", "county", "region", "marital",
)
GOV_SENSITIVE_NAME_HINTS = (
    "diagnosis", "disease", "condition", "salary", "income", "religion",
    "health", "treatment", "medication", "outcome", "disability",
)
GOV_ID_NAME_HINTS = (
    "id", "uuid", "guid", "index", "record", "patient", "user", "member",
    "row", "case",
)
GOV_HIPAA_NAME_HINTS = (
    "name", "address", "email", "phone", "ssn", "medical", "account",
    "notes", "text", "comment",
)
GOV_DP_NAME_HINTS = (
    "age", "income", "salary", "score", "amount", "value", "rate", "count",
    "weight", "height",
)
GOV_HIPAA_SERIOUS_TYPES = frozenset({
    "US_SSN", "MEDICAL_IDS", "VALID_POSTAL_CODE",
})
SYNTHETIC_ID_COL = "__aidrin_row_index__"


def gov_name_hint_score(col_name, hints):
    return fairness_name_hint_score(col_name, hints)


def column_pct_missing(series, n_rows):
    if n_rows <= 0:
        return 1.0
    return float(series.isna().sum()) / n_rows


def column_entropy_norm(series):
    """Normalized Shannon entropy of value counts in [0, 1]."""
    vc = series.dropna().value_counts(normalize=True)
    if len(vc) <= 1:
        return 0.0
    ent = -sum(p * math.log2(p) for p in vc if p > 0)
    max_ent = math.log2(len(vc))
    return ent / max_ent if max_ent > 0 else 0.0


def k_anonymity_status(k_val):
    if k_val is None:
        return "unknown"
    if k_val >= GOV_K_GOOD:
        return "good"
    if k_val >= GOV_K_WARNING:
        return "warning"
    return "poor"


def l_diversity_status(l_val):
    if l_val is None:
        return "unknown"
    if l_val >= GOV_L_GOOD:
        return "good"
    if l_val >= GOV_L_WARNING:
        return "warning"
    return "poor"


def t_closeness_status(t_val):
    if t_val is None:
        return "unknown"
    if t_val <= GOV_T_GOOD:
        return "good"
    if t_val <= GOV_T_WARNING:
        return "warning"
    return "poor"


def mm_risk_status(mean_risk, good=GOV_MM_SINGLE_GOOD, warning=GOV_MM_SINGLE_WARNING):
    if mean_risk is None:
        return "unknown"
    if mean_risk < good:
        return "good"
    if mean_risk < warning:
        return "warning"
    return "poor"


def phi_exposure_status(detected_phi):
    if not detected_phi:
        return "good", 1.0
    serious = any(
        t in GOV_HIPAA_SERIOUS_TYPES
        for info in detected_phi.values()
        for t in (info.get("potential_types_detected") or [])
    )
    if serious:
        return "poor", 0.0
    return "warning", 0.5


def worst_equivalence_classes(df, quasi_identifiers, max_groups=GOV_WORST_GROUPS_MAX):
    """Return the smallest equivalence classes on *quasi_identifiers*."""
    if not quasi_identifiers:
        return [], 0

    data = df.replace("?", pd.NA)
    clean = data.dropna(subset=quasi_identifiers)
    if clean.empty:
        return [], 0

    counts = clean.groupby(quasi_identifiers, dropna=False).size()
    if counts.empty:
        return [], 0

    singleton_count = int((counts == 1).sum())
    worst_groups = []
    for keys, size in counts.nsmallest(max_groups).items():
        if len(quasi_identifiers) == 1:
            key_tuple = (keys,) if not isinstance(keys, tuple) else keys
        else:
            key_tuple = keys if isinstance(keys, tuple) else (keys,)
        qi_values = {
            qi: str(val) if pd.notna(val) else "?"
            for qi, val in zip(quasi_identifiers, key_tuple)
        }
        worst_groups.append({"size": int(size), "qi_values": qi_values})

    return worst_groups, singleton_count


def auto_select_governance_columns(df, fairness_target=None):
    """Pick columns for automated privacy and HIPAA checks in the readiness report."""
    n_rows = max(len(df), 1)
    excluded = []

    # --- Sensitive attribute (before QIs so it can be excluded) ------------
    sensitive_candidates = []
    for col in df.columns:
        feat_type = classify_feature_type(df[col])
        if feat_type not in ("categorical", "boolean"):
            continue
        nunique = df[col].nunique(dropna=True)
        pct_miss = column_pct_missing(df[col], n_rows)
        if nunique < GOV_SENSITIVE_MIN_UNIQUE:
            continue
        if nunique > GOV_SENSITIVE_MAX_UNIQUE:
            excluded.append({
                "feature": col, "role": "sensitive",
                "reason": f"high cardinality ({nunique} categories)",
            })
            continue
        if pct_miss > GOV_MISSING_MAX:
            excluded.append({
                "feature": col, "role": "sensitive",
                "reason": f"high missingness ({pct_miss:.0%})",
            })
            continue
        hint = gov_name_hint_score(col, GOV_SENSITIVE_NAME_HINTS)
        fairness_boost = 1 if fairness_target and col == fairness_target else 0
        sensitive_candidates.append({
            "feature": col,
            "nunique": int(nunique),
            "name_hint_score": hint + fairness_boost,
            "entropy": column_entropy_norm(df[col]),
        })

    sensitive_candidates.sort(
        key=lambda c: (-c["name_hint_score"], -c["entropy"], c["feature"])
    )
    sensitive_col = (
        sensitive_candidates[0]["feature"] if sensitive_candidates else None
    )

    # --- ID column -----------------------------------------------------------
    id_candidates = []
    for col in df.columns:
        if df[col].nunique(dropna=True) == n_rows and n_rows > 0:
            id_candidates.append({
                "feature": col,
                "name_hint_score": gov_name_hint_score(col, GOV_ID_NAME_HINTS),
            })
    id_candidates.sort(key=lambda c: (-c["name_hint_score"], c["feature"]))
    id_synthetic = not id_candidates
    id_col = id_candidates[0]["feature"] if id_candidates else SYNTHETIC_ID_COL

    # --- Quasi-identifiers ---------------------------------------------------
    qi_candidates = []
    for col in df.columns:
        if col == sensitive_col:
            continue
        if not id_synthetic and col == id_col:
            continue
        feat_type = classify_feature_type(df[col])
        if feat_type == "datetime":
            excluded.append({"feature": col, "role": "quasi-identifier", "reason": "datetime column"})
            continue
        nunique = df[col].nunique(dropna=True)
        pct_miss = column_pct_missing(df[col], n_rows)
        if nunique < GOV_QI_MIN_UNIQUE:
            excluded.append({"feature": col, "role": "quasi-identifier", "reason": "constant column"})
            continue
        if pct_miss > GOV_MISSING_MAX:
            excluded.append({
                "feature": col, "role": "quasi-identifier",
                "reason": f"high missingness ({pct_miss:.0%})",
            })
            continue
        if nunique / n_rows >= GOV_ID_UNIQUE_RATIO:
            excluded.append({"feature": col, "role": "quasi-identifier", "reason": "ID-like (near-unique values)"})
            continue
        if feat_type in ("categorical", "boolean"):
            if nunique > GOV_QI_MAX_UNIQUE:
                excluded.append({
                    "feature": col, "role": "quasi-identifier",
                    "reason": f"high cardinality ({nunique} categories)",
                })
                continue
        elif feat_type == "numerical":
            if nunique > GOV_NUMERIC_QI_MAX_UNIQUE:
                excluded.append({
                    "feature": col, "role": "quasi-identifier",
                    "reason": f"continuous numeric ({nunique} unique values)",
                })
                continue
        else:
            excluded.append({"feature": col, "role": "quasi-identifier", "reason": f"unsupported type ({feat_type})"})
            continue

        qi_candidates.append({
            "feature": col,
            "nunique": int(nunique),
            "feat_type": feat_type,
            "name_hint_score": gov_name_hint_score(col, GOV_QI_NAME_HINTS),
        })

    qi_candidates.sort(
        key=lambda c: (-c["name_hint_score"], c["nunique"], c["feature"])
    )
    quasi_identifiers = [c["feature"] for c in qi_candidates[:GOV_QI_MAX_COUNT]]
    for c in qi_candidates[GOV_QI_MAX_COUNT:]:
        excluded.append({"feature": c["feature"], "role": "quasi-identifier", "reason": "exceeded QI cap"})

    mm_quasi_identifiers = [
        c["feature"] for c in qi_candidates[:GOV_QI_MAX_COUNT]
        if c["feat_type"] in ("categorical", "boolean")
        and c["nunique"] <= GOV_MM_QI_MAX_UNIQUE
    ]

    # --- HIPAA scan columns --------------------------------------------------
    hipaa_candidates = []
    for col in df.columns:
        nunique = df[col].nunique(dropna=True)
        if nunique <= 1:
            continue
        pct_miss = column_pct_missing(df[col], n_rows)
        feat_type = classify_feature_type(df[col])
        is_text = feat_type in ("categorical",) or str(df[col].dtype) in ("object", "string")
        if is_text and pct_miss <= GOV_HIPAA_MISSING_MAX:
            avg_len = df[col].dropna().astype(str).str.len().mean()
            hipaa_candidates.append({
                "feature": col,
                "name_hint_score": gov_name_hint_score(col, GOV_HIPAA_NAME_HINTS),
                "avg_len": avg_len if pd.notna(avg_len) else 0,
            })

    hipaa_candidates.sort(
        key=lambda c: (-c["name_hint_score"], -c["avg_len"], c["feature"])
    )
    hipaa_scan_columns = [c["feature"] for c in hipaa_candidates[:GOV_HIPAA_MAX_COLUMNS]]
    if not hipaa_scan_columns:
        hipaa_scan_columns = [
            col for col in df.columns if df[col].nunique(dropna=True) > 1
        ][: GOV_HIPAA_MAX_COLUMNS]

    # --- DP numerical features -----------------------------------------------
    dp_candidates = []
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        nunique = df[col].nunique(dropna=True)
        if nunique <= 1:
            continue
        if nunique / n_rows >= GOV_ID_UNIQUE_RATIO:
            continue
        if column_pct_missing(df[col], n_rows) > GOV_MISSING_MAX:
            continue
        dp_candidates.append({
            "feature": col,
            "name_hint_score": gov_name_hint_score(col, GOV_DP_NAME_HINTS),
            "pct_missing": column_pct_missing(df[col], n_rows),
            "nunique": int(nunique),
        })
    dp_candidates.sort(
        key=lambda c: (-c["name_hint_score"], c["pct_missing"], c["nunique"], c["feature"])
    )
    dp_features = [c["feature"] for c in dp_candidates[:GOV_DP_MAX_FEATURES]]

    qi_excluded_raw = [e for e in excluded if e["role"] == "quasi-identifier"]
    sens_excluded_raw = [e for e in excluded if e["role"] == "sensitive"]
    qi_excluded, qi_excluded_meta = cap_detail_list(
        qi_excluded_raw, READINESS_MAX_DETAIL_LIST_ITEMS
    )
    sens_excluded, sens_excluded_meta = cap_detail_list(
        sens_excluded_raw, READINESS_MAX_DETAIL_LIST_ITEMS
    )

    return {
        "quasi_identifiers": quasi_identifiers,
        "mm_quasi_identifiers": mm_quasi_identifiers,
        "sensitive_attribute": sensitive_col,
        "id_column": id_col,
        "id_synthetic": id_synthetic,
        "hipaa_scan_columns": hipaa_scan_columns,
        "dp_features": dp_features,
        "dp_epsilon": GOV_DP_EPSILON,
        "selection_criteria": {
            "quasi_identifiers": {
                "rule": (
                    f"Categorical/boolean with {GOV_QI_MIN_UNIQUE}–{GOV_QI_MAX_UNIQUE} "
                    f"unique values; discrete numeric with {GOV_QI_MIN_UNIQUE}–"
                    f"{GOV_NUMERIC_QI_MAX_UNIQUE}; exclude ID-like, datetime, "
                    f"and >{GOV_MISSING_MAX:.0%} missing; prefer name hints; "
                    f"capped at {GOV_QI_MAX_COUNT}."
                ),
                "name_hints": list(GOV_QI_NAME_HINTS),
                "selected": quasi_identifiers,
                "excluded": qi_excluded,
                "excluded_meta": qi_excluded_meta,
            },
            "sensitive_attribute": {
                "rule": (
                    f"Categorical/boolean with {GOV_SENSITIVE_MIN_UNIQUE}–"
                    f"{GOV_SENSITIVE_MAX_UNIQUE} unique values, excluding QIs; "
                    "prefer sensitive name hints and fairness target when eligible."
                ),
                "name_hints": list(GOV_SENSITIVE_NAME_HINTS),
                "selected": sensitive_col,
                "excluded": sens_excluded,
                "excluded_meta": sens_excluded_meta,
            },
            "id_column": {
                "rule": (
                    "Exact-unique column preferred (name hints: id, uuid, patient, …); "
                    "otherwise synthetic row index for linkage-risk scoring only."
                ),
                "selected": id_col,
                "synthetic": id_synthetic,
            },
            "hipaa_scan_columns": {
                "rule": (
                    f"Text-like columns up to {GOV_HIPAA_MAX_COLUMNS}, prefer HIPAA "
                    "name hints; fallback to all non-constant columns."
                ),
                "name_hints": list(GOV_HIPAA_NAME_HINTS),
                "selected": hipaa_scan_columns,
            },
            "dp_features": {
                "rule": (
                    f"Up to {GOV_DP_MAX_FEATURES} numerical, non-ID-like columns "
                    f"(illustrative only, ε={GOV_DP_EPSILON})."
                ),
                "selected": dp_features,
                "epsilon": GOV_DP_EPSILON,
            },
            "thresholds": {
                "k_good": GOV_K_GOOD,
                "k_warning": GOV_K_WARNING,
                "l_good": GOV_L_GOOD,
                "l_warning": GOV_L_WARNING,
                "t_good": GOV_T_GOOD,
                "t_warning": GOV_T_WARNING,
                "mm_single_good": GOV_MM_SINGLE_GOOD,
                "mm_single_warning": GOV_MM_SINGLE_WARNING,
                "mm_multi_good": GOV_MM_MULTI_GOOD,
                "mm_multi_warning": GOV_MM_MULTI_WARNING,
                "small_sample_rows": GOV_SMALL_SAMPLE,
            },
        },
    }


def build_data_governance_section(file_info, include_visualizations=False):
    """Compute the Data Governance portion of the readiness report."""
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]

    n_rows = len(df)
    fairness_sel = auto_select_fairness_columns(df)
    selection = auto_select_governance_columns(
        df, fairness_target=fairness_sel.get("target_column")
    )
    qi = selection["quasi_identifiers"]
    mm_qis = selection["mm_quasi_identifiers"]
    sensitive = selection["sensitive_attribute"]
    id_col = selection["id_column"]
    id_synthetic = selection["id_synthetic"]

    work_df = df.copy()
    if id_synthetic:
        work_df[SYNTHETIC_ID_COL] = range(len(work_df))
        id_col = SYNTHETIC_ID_COL

    kpis = []
    needs_attention = {
        "low_anonymity": [],
        "hipaa_phi": [],
        "high_linkage_risk": [],
        "attribute_disclosure": [],
    }
    details = {}
    small_sample = n_rows < GOV_SMALL_SAMPLE

    # --- k-Anonymity ---------------------------------------------------------
    k_val = None
    if qi:
        k_res = compute_k_anonymity(qi, work_df, include_visualization=include_visualizations)
        if "Error" not in k_res:
            k_val = k_res.get("k-Value")
            if k_val is not None and k_val < GOV_K_WARNING:
                worst_groups, singleton_count = worst_equivalence_classes(work_df, qi)
                needs_attention["low_anonymity"].append({
                    "metric": "k-Anonymity",
                    "value": k_val,
                    "quasi_identifiers": list(qi),
                    "singleton_count": singleton_count,
                    "worst_groups": worst_groups,
                    "detail": (
                        f"Minimum group size {k_val} on quasi-identifiers: "
                        f"{', '.join(qi)}"
                    ),
                })
            details["k_anonymity"] = {
                "quasi_identifiers": qi,
                "k_value": k_val,
                "descriptive_statistics": k_res.get("descriptive_statistics"),
                "visualization": k_res.get("k-Anonymity Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            }
        else:
            details["k_anonymity"] = {"error": k_res.get("Error")}
    else:
        details["k_anonymity"] = {"error": "No eligible quasi-identifier columns found."}

    k_kpi = min(float(k_val) / GOV_K_GOOD, 1.0) if k_val is not None else None
    kpis.append({
        "id": "anonymity_k",
        "label": "Anonymity (k)",
        "value": k_kpi,
        "status": k_anonymity_status(k_val),
        "hint": f"k-Value ≥ {GOV_K_GOOD} good, ≥ {GOV_K_WARNING} warning (min group size on auto QIs).",
        "raw_k": k_val,
    })

    # --- l-Diversity ---------------------------------------------------------
    l_val = None
    if qi and sensitive:
        l_res = compute_l_diversity(qi, sensitive, work_df, include_visualization=include_visualizations)
        if "Error" not in l_res:
            l_val = l_res.get("l-Value")
            if l_val is not None and l_val < GOV_L_WARNING:
                needs_attention["attribute_disclosure"].append({
                    "metric": "l-Diversity",
                    "value": l_val,
                    "sensitive_attribute": sensitive,
                    "quasi_identifiers": list(qi),
                    "detail": (
                        f"Sensitive '{sensitive}' has only {l_val} distinct value(s) "
                        f"in some groups defined by ({', '.join(qi)})"
                    ),
                })
            details["l_diversity"] = {
                "quasi_identifiers": qi,
                "sensitive_attribute": sensitive,
                "l_value": l_val,
                "descriptive_statistics": l_res.get("descriptive_statistics"),
                "visualization": l_res.get("l-Diversity Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            }
        else:
            details["l_diversity"] = {"error": l_res.get("Error")}
    else:
        details["l_diversity"] = {
            "error": "Requires quasi-identifiers and a sensitive attribute.",
        }

    l_kpi = min(float(l_val) / GOV_L_GOOD, 1.0) if l_val is not None else None
    kpis.append({
        "id": "diversity_l",
        "label": "Attribute diversity (l)",
        "value": l_kpi,
        "status": l_diversity_status(l_val),
        "hint": f"l-Value ≥ {GOV_L_GOOD} good, ≥ {GOV_L_WARNING} warning (min distinct sensitive values per QI group).",
        "raw_l": l_val,
    })

    # --- t-Closeness ---------------------------------------------------------
    t_val = None
    if qi and sensitive:
        t_res = compute_t_closeness(qi, sensitive, work_df, include_visualization=include_visualizations)
        if "Error" not in t_res:
            t_val = t_res.get("t-Value")
            if t_val is not None and t_val > GOV_T_WARNING:
                needs_attention["attribute_disclosure"].append({
                    "metric": "t-Closeness",
                    "value": t_val,
                    "sensitive_attribute": sensitive,
                    "quasi_identifiers": list(qi),
                    "detail": (
                        f"Distribution of '{sensitive}' diverges from global "
                        f"(max TVD {t_val}) within groups of ({', '.join(qi)})"
                    ),
                })
            details["t_closeness"] = {
                "quasi_identifiers": qi,
                "sensitive_attribute": sensitive,
                "t_value": t_val,
                "descriptive_statistics": t_res.get("descriptive_statistics"),
                "visualization": t_res.get("t-Closeness Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            }
        else:
            details["t_closeness"] = {"error": t_res.get("Error")}
    else:
        details["t_closeness"] = {
            "error": "Requires quasi-identifiers and a sensitive attribute.",
        }

    t_kpi = max(0.0, 1.0 - float(t_val) / GOV_T_WARNING) if t_val is not None else None
    kpis.append({
        "id": "distribution_t",
        "label": "Distribution leakage (t)",
        "value": t_kpi,
        "status": t_closeness_status(t_val),
        "hint": f"Max TVD ≤ {GOV_T_GOOD} good, ≤ {GOV_T_WARNING} warning (lower is better).",
        "raw_t": t_val,
    })

    # --- Entropy risk --------------------------------------------------------
    if qi:
        e_res = compute_entropy_risk(qi, work_df, include_visualization=include_visualizations)
        if "Error" not in e_res:
            details["entropy_risk"] = {
                "quasi_identifiers": qi,
                "entropy_value": e_res.get("Entropy-Value"),
                "descriptive_statistics": e_res.get("descriptive_statistics"),
                "visualization": e_res.get("Entropy Risk Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            }
        else:
            details["entropy_risk"] = {"error": e_res.get("Error")}
    else:
        details["entropy_risk"] = {"error": "No eligible quasi-identifier columns found."}

    # --- Single-attribute MM risk ----------------------------------------------
    # One call with all QIs so dropna() is list-wise, matching the Privacy tab.
    # Charts are deferred; skip visualization here even when include_visualizations is set.
    worst_single_mean = None
    single_by_qi = {}
    if mm_qis:
        try:
            s_res = generate_single_attribute_MM_risk_scores_groupby(
                work_df, id_col, mm_qis, include_visualization=False
            )
        except Exception as exc:
            s_res = {"Error": str(exc)}
        if "Error" in s_res:
            for q in mm_qis:
                single_by_qi[q] = {"error": s_res["Error"]}
        else:
            stats_by_col = s_res.get("Descriptive statistics of the risk scores") or {}
            for q in mm_qis:
                stats = stats_by_col.get(q, {})
                mean_risk = stats.get("mean")
                if mean_risk is None:
                    single_by_qi[q] = {"error": "No risk score for this quasi-identifier."}
                    continue
                mean_risk = float(mean_risk)
                single_by_qi[q] = {"mean_risk": round(mean_risk, 4), "stats": stats}
                if worst_single_mean is None or mean_risk > worst_single_mean:
                    worst_single_mean = mean_risk
                if mean_risk >= GOV_MM_SINGLE_WARNING:
                    needs_attention["high_linkage_risk"].append({
                        "metric": "Single-attribute risk",
                        "feature": q,
                        "quasi_identifiers": [q],
                        "mean_risk": round(mean_risk, 4),
                        "detail": f"Quasi-identifier '{q}' — mean MM risk {mean_risk:.2f}",
                    })
        details["single_attribute_risk"] = {
            "id_column": id_col,
            "by_quasi_identifier": single_by_qi,
        }
        if needs_attention["low_anonymity"] and single_by_qi:
            worst_qi = None
            for q, info in single_by_qi.items():
                mr = info.get("mean_risk")
                if mr is not None and (worst_qi is None or mr > worst_qi[1]):
                    worst_qi = (q, mr)
            if worst_qi:
                needs_attention["low_anonymity"][0]["worst_single_qi"] = {
                    "feature": worst_qi[0],
                    "mean_risk": worst_qi[1],
                }
    else:
        details["single_attribute_risk"] = {
            "error": "No categorical quasi-identifiers eligible for MM risk scoring.",
        }

    single_kpi = (
        max(0.0, 1.0 - worst_single_mean) if worst_single_mean is not None else None
    )
    kpis.append({
        "id": "single_linkage_risk",
        "label": "Worst single-field risk",
        "value": single_kpi,
        "status": mm_risk_status(worst_single_mean),
        "hint": (
            f"1 − worst mean MM risk across QIs; good < {GOV_MM_SINGLE_GOOD}, "
            f"warning < {GOV_MM_SINGLE_WARNING}."
        ),
        "raw_worst_mean": round(worst_single_mean, 4) if worst_single_mean is not None else None,
    })

    # --- Multiple-attribute MM risk ------------------------------------------
    multi_mean = None
    if mm_qis:
        try:
            m_res = generate_multiple_attribute_MM_risk_scores_groupby(
                work_df, id_col, mm_qis, include_visualization=include_visualizations
            )
            if "Error" not in m_res:
                m_stats = m_res.get("Descriptive statistics of the risk scores") or {}
                multi_mean = m_stats.get("mean")
                if multi_mean is not None:
                    multi_mean = float(multi_mean)
                    if multi_mean >= GOV_MM_MULTI_WARNING:
                        needs_attention["high_linkage_risk"].append({
                            "metric": "Multiple-attribute risk",
                            "features": list(mm_qis),
                            "quasi_identifiers": list(mm_qis),
                            "mean_risk": round(multi_mean, 4),
                            "detail": (
                                f"Combined QIs ({', '.join(mm_qis)}) — "
                                f"mean MM risk {multi_mean:.2f}"
                            ),
                        })
                details["multiple_attribute_risk"] = {
                    "id_column": id_col,
                    "quasi_identifiers": mm_qis,
                    "mean_risk": round(multi_mean, 4) if multi_mean is not None else None,
                    "dataset_risk_score": m_res.get("Dataset Risk Score"),
                    "stats": m_stats,
                    "visualization": m_res.get("Multiple attribute risk scoring Visualization") if include_visualizations else None,
                    "visualization_deferred": not include_visualizations,
                }
            else:
                details["multiple_attribute_risk"] = {"error": m_res.get("Error")}
        except Exception as exc:
            details["multiple_attribute_risk"] = {"error": str(exc)}
    else:
        details["multiple_attribute_risk"] = {
            "error": "No categorical quasi-identifiers eligible for combined MM risk.",
        }

    multi_kpi = max(0.0, 1.0 - multi_mean) if multi_mean is not None else None
    kpis.append({
        "id": "linkage_risk",
        "label": "Combined linkage risk",
        "value": multi_kpi,
        "status": mm_risk_status(
            multi_mean, good=GOV_MM_MULTI_GOOD, warning=GOV_MM_MULTI_WARNING
        ),
        "hint": (
            f"1 − mean MM risk on combined QIs; good < {GOV_MM_MULTI_GOOD}, "
            f"warning < {GOV_MM_MULTI_WARNING}."
        ),
        "raw_mean": round(multi_mean, 4) if multi_mean is not None else None,
    })

    # --- HIPAA ---------------------------------------------------------------
    hipaa_cols = selection["hipaa_scan_columns"]
    detected_phi = {}
    if hipaa_cols:
        detected_phi = detect_hipaa_identifiers(work_df, hipaa_cols)
        for col, info in detected_phi.items():
            types = info.get("potential_types_detected") or []
            serious = [t for t in types if t in GOV_HIPAA_SERIOUS_TYPES]
            needs_attention["hipaa_phi"].append({
                "column": col,
                "total_flags": info.get("total_flags", 0),
                "types": types,
                "serious": bool(serious),
                "examples": info.get("examples") or [],
            })
        details["hipaa"] = {
            "columns_scanned": hipaa_cols,
            "detected": detected_phi,
        }
    else:
        details["hipaa"] = {"error": "No columns available to scan."}

    hipaa_status, hipaa_kpi = phi_exposure_status(detected_phi)
    kpis.append({
        "id": "phi_exposure",
        "label": "PHI exposure",
        "value": hipaa_kpi,
        "status": hipaa_status,
        "hint": "Pattern scan for HIPAA-like identifiers (SSN, medical IDs, postal codes, etc.). Not full Safe Harbor certification.",
        "columns_flagged": len(detected_phi),
    })

    # --- Differential privacy (illustrative) -----------------------------------
    dp_features = selection["dp_features"]
    if dp_features:
        try:
            dp_res = return_noisy_stats(
                dp_features, GOV_DP_EPSILON, work_df,
                save_output=False, include_visualization=include_visualizations,
            )
            if "Error" not in dp_res:
                details["differential_privacy"] = {
                    "features": dp_features,
                    "epsilon": GOV_DP_EPSILON,
                    "illustrative": True,
                    "visualization": dp_res.get("DP Statistics Visualization") if include_visualizations else None,
                    "visualization_deferred": not include_visualizations,
                    "summary": {
                        k: v for k, v in dp_res.items()
                        if k.endswith("(before noise)") or k.endswith("(after noise)")
                    },
                }
            else:
                details["differential_privacy"] = {"error": dp_res.get("Error")}
        except Exception as exc:
            details["differential_privacy"] = {"error": str(exc)}
    else:
        details["differential_privacy"] = {
            "error": "No eligible numerical columns for illustrative DP demo.",
        }

    present = finite_kpi_values(kpis)
    grade = sum(present) / len(present) if present else None

    return {
        "grade": grade,
        "grade_status": grade_label(grade),
        "small_sample_warning": small_sample,
        "auto_selection": selection,
        "kpis": kpis,
        "needs_attention": needs_attention,
        "details": details,
        "visualizations_deferred": not include_visualizations,
    }
