"""Fairness & Bias section of the readiness report."""

from __future__ import annotations

from aidrin.file_handling.file_parser import read_file
from aidrin.report.common import (
    READINESS_MAX_DETAIL_LIST_ITEMS,
    cap_detail_list,
    finite_kpi_values,
    grade_label,
)
from aidrin.structured_data_metrics.class_imbalance import (
    calc_imbalance_degree,
    class_distribution_plot,
)
from aidrin.structured_data_metrics.conditional_demo_disp import (
    conditional_demographic_disparity,
)
from aidrin.structured_data_metrics.representation_rate import (
    calculate_representation_rate,
    create_representation_rate_vis,
)
from aidrin.structured_data_metrics.statistical_rate import calculate_statistical_rates

# Fairness & Bias tuning constants
FAIRNESS_SENSITIVE_MIN_UNIQUE = 2
FAIRNESS_SENSITIVE_MAX_UNIQUE = 30
FAIRNESS_MAX_SENSITIVE_COLS = 5
FAIRNESS_ID_UNIQUE_RATIO = 0.9
FAIRNESS_TARGET_MAX_UNIQUE = 30
FAIRNESS_REP_RATIO_FLAG = 3.0       # probability ratio at/above which representation is flagged
FAIRNESS_MINORITY_SHARE = 0.05      # class share below which a label is "minority"
FAIRNESS_IMBALANCE_GOOD = 0.5       # imbalance degree below this → good
FAIRNESS_IMBALANCE_WARNING = 1.0    # below this → warning, else poor
FAIRNESS_TSD_FLAG = 0.15            # TSD above this → outcome-rate disparity flagged
FAIRNESS_SENSITIVE_NAME_HINTS = (
    "gender", "sex", "race", "ethnic", "age", "religion", "marital",
    "disability", "national", "origin", "minority",
)
FAIRNESS_TARGET_NAME_HINTS = (
    "label", "target", "class", "outcome", "decision", "y", "income",
)


def fairness_name_hint_score(col_name, hints):
    """Return a higher score when *col_name* matches an earlier hint substring."""
    lower = col_name.lower()
    best = 0
    for i, hint in enumerate(hints):
        if hint in lower:
            best = max(best, len(hints) - i)
    return best


def auto_select_fairness_columns(df):
    """Pick sensitive attributes and a target column for automated fairness checks.

    Returns a dict with selected columns, exclusion reasons, and the
    auto-selected positive class (mode of the target) for CDD.
    """
    n_rows = max(len(df), 1)
    cat_cols = list(df.select_dtypes(include=["object", "string", "category"]).columns)

    sensitive_candidates = []
    excluded_sensitive = []

    for col in cat_cols:
        nunique = df[col].nunique(dropna=True)
        if nunique < FAIRNESS_SENSITIVE_MIN_UNIQUE:
            excluded_sensitive.append({"feature": col, "reason": "constant column"})
        elif nunique > FAIRNESS_SENSITIVE_MAX_UNIQUE:
            excluded_sensitive.append({
                "feature": col,
                "reason": (
                    f"high cardinality ({nunique} categories, "
                    f"max {FAIRNESS_SENSITIVE_MAX_UNIQUE})"
                ),
            })
        elif nunique / n_rows >= FAIRNESS_ID_UNIQUE_RATIO:
            excluded_sensitive.append({"feature": col, "reason": "ID-like (near-unique values)"})
        else:
            sensitive_candidates.append({
                "feature": col,
                "nunique": int(nunique),
                "name_hint_score": fairness_name_hint_score(col, FAIRNESS_SENSITIVE_NAME_HINTS),
            })

    sensitive_candidates.sort(
        key=lambda c: (-c["name_hint_score"], c["nunique"], c["feature"])
    )
    selected_sensitive = [
        c["feature"] for c in sensitive_candidates[:FAIRNESS_MAX_SENSITIVE_COLS]
    ]
    for c in sensitive_candidates[FAIRNESS_MAX_SENSITIVE_COLS:]:
        excluded_sensitive.append({
            "feature": c["feature"],
            "reason": "exceeded sensitive-column cap",
        })

    # Target: low-cardinality columns (2–30 unique), prefer name hints; exclude sensitives
    target_candidates = []
    sensitive_set = set(selected_sensitive)
    for col in df.columns:
        if col in sensitive_set:
            continue
        nunique = df[col].nunique(dropna=True)
        if FAIRNESS_SENSITIVE_MIN_UNIQUE <= nunique <= FAIRNESS_TARGET_MAX_UNIQUE:
            target_candidates.append({
                "feature": col,
                "nunique": int(nunique),
                "name_hint_score": fairness_name_hint_score(col, FAIRNESS_TARGET_NAME_HINTS),
            })

    target_candidates.sort(
        key=lambda c: (-c["name_hint_score"], c["nunique"], c["feature"])
    )
    target_col = target_candidates[0]["feature"] if target_candidates else None
    target_reason = None
    if target_col:
        tc = target_candidates[0]
        if tc["name_hint_score"] > 0:
            target_reason = "matched target name hint"
        elif tc == target_candidates[-1] and len(target_candidates) == 1:
            target_reason = "only eligible low-cardinality column"
        else:
            target_reason = "lowest-cardinality eligible column (after name-hint priority)"

    positive_class = None
    positive_reason = None
    if target_col is not None:
        target_series = df[target_col].dropna()
        if len(target_series) > 0:
            positive_class = target_series.mode().iloc[0]
            positive_reason = "most frequent class in auto-selected target"

    primary_sensitive = selected_sensitive[0] if selected_sensitive else None

    excluded_capped, excluded_meta = cap_detail_list(
        excluded_sensitive, READINESS_MAX_DETAIL_LIST_ITEMS
    )

    return {
        "sensitive_columns": selected_sensitive,
        "primary_sensitive": primary_sensitive,
        "target_column": target_col,
        "positive_class": positive_class,
        "selection_criteria": {
            "sensitive_attributes": {
                "rule": (
                    f"Categorical columns with {FAIRNESS_SENSITIVE_MIN_UNIQUE}–"
                    f"{FAIRNESS_SENSITIVE_MAX_UNIQUE} unique values, excluding "
                    "ID-like columns; prefer name hints "
                    f"{list(FAIRNESS_SENSITIVE_NAME_HINTS)}; "
                    f"capped at {FAIRNESS_MAX_SENSITIVE_COLS}."
                ),
                "name_hints": list(FAIRNESS_SENSITIVE_NAME_HINTS),
                "selected": selected_sensitive,
                "excluded": excluded_capped,
                "excluded_meta": excluded_meta,
            },
            "target_column": {
                "rule": (
                    f"Columns with {FAIRNESS_SENSITIVE_MIN_UNIQUE}–{FAIRNESS_TARGET_MAX_UNIQUE} "
                    "unique values, excluding auto-selected sensitive columns; "
                    "prefer name hints "
                    f"{list(FAIRNESS_TARGET_NAME_HINTS)}."
                ),
                "name_hints": list(FAIRNESS_TARGET_NAME_HINTS),
                "selected": target_col,
                "reason": target_reason,
            },
            "positive_class": {
                "rule": "Most frequent value in the auto-selected target (used for CDD only).",
                "selected": str(positive_class) if positive_class is not None else None,
                "reason": positive_reason,
            },
            "thresholds": {
                "representation_ratio_flag": FAIRNESS_REP_RATIO_FLAG,
                "minority_class_share": FAIRNESS_MINORITY_SHARE,
                "imbalance_degree_good": FAIRNESS_IMBALANCE_GOOD,
                "imbalance_degree_warning": FAIRNESS_IMBALANCE_WARNING,
                "tsd_disparity_flag": FAIRNESS_TSD_FLAG,
            },
        },
    }


def parse_representation_flags(ratios_dict):
    """Extract per-column max probability ratio and flag extreme imbalance."""
    by_column = {}
    if not isinstance(ratios_dict, dict) or "Error" in ratios_dict:
        return [], None, ratios_dict.get("Error") if isinstance(ratios_dict, dict) else None

    for key, ratio in ratios_dict.items():
        if not isinstance(ratio, (int, float)) or "Column: '" not in key:
            continue
        # Key format: Column: 'col', Probability ratio for 'A' to 'B'
        try:
            col_part = key.split("Column: '", 1)[1]
            col = col_part.split("',", 1)[0]
        except IndexError:
            continue
        entry = by_column.setdefault(col, {"column": col, "max_ratio": 0.0, "flagged_pairs": []})
        r = float(ratio)
        if r > entry["max_ratio"]:
            entry["max_ratio"] = round(r, 3)
        if r >= FAIRNESS_REP_RATIO_FLAG:
            pair_part = key.split("Probability ratio for ", 1)[-1]
            entry["flagged_pairs"].append({"pair": pair_part, "ratio": round(r, 3)})

    summaries = sorted(by_column.values(), key=lambda x: x["max_ratio"], reverse=True)
    worst = summaries[0]["max_ratio"] if summaries else None
    rep_balance_kpi = min(1.0, 1.0 / worst) if worst and worst > 0 else None
    return summaries, rep_balance_kpi, None


def imbalance_status(id_score):
    if id_score is None:
        return "unknown"
    if id_score < FAIRNESS_IMBALANCE_GOOD:
        return "good"
    if id_score < FAIRNESS_IMBALANCE_WARNING:
        return "warning"
    return "poor"


def compute_class_imbalance(file, classes, dist_metric, include_visualization=True):
    """Compute class-imbalance scores and optional distribution visualization."""
    ci_dict = {}
    try:
        if include_visualization:
            ci_dict["Class Imbalance Visualization"] = class_distribution_plot(file, classes)
        ci_dict["Description"] = (
            "The chart displays the distribution of classes within the "
            "specified feature, providing a visual representation of the "
            "relative proportions of each class."
        )
        imbalance_result = calc_imbalance_degree(file, classes, dist_metric=dist_metric)
        if "Error" in imbalance_result:
            ci_dict["Error"] = imbalance_result["Error"]
            ci_dict["ErrorType"] = imbalance_result.get("ErrorType", "Processing Error")
            ci_dict["Class Imbalance Visualization"] = ""
            ci_dict["Description"] = f"Error: {imbalance_result['Error']}"
        else:
            ci_dict["Imbalance degree"] = imbalance_result
    except Exception as e:
        ci_dict["Error"] = str(e)
        ci_dict["ErrorType"] = "Processing Error"
        ci_dict["Class Imbalance Visualization"] = ""
        ci_dict["Description"] = f"Error: {str(e)}"
    return ci_dict


def build_fairness_bias_section(file_info, include_visualizations=False):
    """Compute the Fairness & Bias portion of the readiness report.

    Auto-selects sensitive attributes and a target, then runs representation
    rate, class imbalance, statistical rate, and conditional demographic
    disparity using the same functions as the Fairness & Bias tab.
    """
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]

    selection = auto_select_fairness_columns(df)
    sensitive_cols = selection["sensitive_columns"]
    target_col = selection["target_column"]
    primary_sensitive = selection["primary_sensitive"]
    positive_class = selection["positive_class"]

    kpis = []
    needs_attention = {
        "representation_imbalance": [],
        "minority_classes": [],
        "outcome_disparities": [],
        "cdd_disparities": [],
    }
    details = {}

    # --- Representation Rate (all selected sensitive columns) ---------------
    rep_error = None
    rep_balance_kpi = None
    if sensitive_cols:
        ratios = calculate_representation_rate(sensitive_cols, file_info)
        rep_summaries, rep_balance_kpi, rep_error = parse_representation_flags(ratios)
        needs_attention["representation_imbalance"] = [
            s for s in rep_summaries if s["max_ratio"] >= FAIRNESS_REP_RATIO_FLAG
        ]
        rep_visualizations = {}
        if include_visualizations:
            for col in sensitive_cols:
                try:
                    vis = create_representation_rate_vis([col], file_info)
                    if isinstance(vis, str):
                        rep_visualizations[col] = vis
                except Exception:
                    pass
        details["representation_rate"] = {
            "ratios": ratios if not rep_error else None,
            "summaries": rep_summaries,
            "visualizations": rep_visualizations,
            "visualizations_deferred": not include_visualizations,
            "error": rep_error,
        }
    else:
        details["representation_rate"] = {
            "error": "No eligible sensitive-attribute columns found.",
        }

    kpis.append({
        "id": "representation_balance",
        "label": "Representation balance",
        "value": rep_balance_kpi,
        "status": grade_label(rep_balance_kpi),
        "hint": (
            f"1 / worst group probability ratio "
            f"(flagged when ratio ≥ {FAIRNESS_REP_RATIO_FLAG})."
        ),
    })

    # --- Class Imbalance (auto target) --------------------------------------
    imbalance_degree = None
    if target_col:
        ci_dict = compute_class_imbalance(
            df, target_col, "EU", include_visualization=include_visualizations
        )
        if "Error" in ci_dict:
            details["class_imbalance"] = {"error": ci_dict["Error"]}
        else:
            imb = ci_dict.get("Imbalance degree") or {}
            imbalance_degree = imb.get("Imbalance Degree score")
            details["class_imbalance"] = {
                "visualization": (
                    ci_dict.get("Class Imbalance Visualization")
                    if include_visualizations else None
                ),
                "visualization_deferred": not include_visualizations,
                "imbalance_degree": imbalance_degree,
            }
            # Minority classes
            vc = df[target_col].value_counts(normalize=True, dropna=True)
            for cls, share in vc.items():
                if share < FAIRNESS_MINORITY_SHARE:
                    needs_attention["minority_classes"].append({
                        "target_column": target_col,
                        "class": str(cls),
                        "share": round(float(share), 4),
                    })
    else:
        details["class_imbalance"] = {"error": "No eligible target column found."}

    label_balance_kpi = (
        max(0.0, 1.0 - min(float(imbalance_degree) / 2.0, 1.0))
        if imbalance_degree is not None
        else None
    )
    kpis.append({
        "id": "label_balance",
        "label": "Label balance",
        "value": label_balance_kpi,
        "status": imbalance_status(imbalance_degree),
        "hint": (
            f"Derived from Imbalance Degree (EU); 0 = balanced. "
            f"Good < {FAIRNESS_IMBALANCE_GOOD}, warning < {FAIRNESS_IMBALANCE_WARNING}."
        ),
        "raw_imbalance_degree": imbalance_degree,
    })

    # --- Statistical Rate (primary sensitive + target) ----------------------
    disparity_kpi = None
    if primary_sensitive and target_col:
        sr = calculate_statistical_rates(
            target_col, primary_sensitive, file_info,
            include_visualization=include_visualizations,
        )
        if isinstance(sr, dict) and "Error" in sr:
            details["statistical_rate"] = {"error": sr["Error"]}
        else:
            tsd_scores = sr.get("TSD scores") or {}
            flagged = [
                {
                    "target_column": target_col,
                    "sensitive_column": primary_sensitive,
                    "class": str(cls),
                    "tsd": round(float(score), 4),
                }
                for cls, score in tsd_scores.items()
                if isinstance(score, (int, float)) and float(score) >= FAIRNESS_TSD_FLAG
            ]
            flagged.sort(key=lambda x: x["tsd"], reverse=True)
            needs_attention["outcome_disparities"] = flagged
            max_tsd = max(
                (float(v) for v in tsd_scores.values() if isinstance(v, (int, float))),
                default=None,
            )
            disparity_kpi = max(0.0, 1.0 - min(max_tsd, 1.0)) if max_tsd is not None else None
            details["statistical_rate"] = {
                "sensitive": primary_sensitive,
                "target": target_col,
                "tsd_scores": tsd_scores,
                "visualization": (
                    sr.get("Statistical Rate Visualization")
                    if include_visualizations else None
                ),
                "visualization_deferred": not include_visualizations,
            }
    else:
        details["statistical_rate"] = {
            "error": "Requires both a sensitive attribute and a target column.",
        }

    kpis.append({
        "id": "outcome_parity",
        "label": "Outcome parity",
        "value": disparity_kpi,
        "status": grade_label(disparity_kpi),
        "hint": (
            f"1 − max TSD across classes (flagged when TSD ≥ {FAIRNESS_TSD_FLAG}). "
            "Uses primary sensitive attribute."
        ),
    })

    # --- Conditional Demographic Disparity ----------------------------------
    if primary_sensitive and target_col and positive_class is not None:
        try:
            cdd = conditional_demographic_disparity(
                df[target_col].tolist(),
                df[primary_sensitive].tolist(),
                positive_class,
            )
            if isinstance(cdd, dict) and "Error" in cdd:
                details["cdd"] = {"error": cdd["Error"]}
            else:
                disparities = (cdd or {}).get("Disparities") or {}
                cdd_flagged = [
                    {
                        "sensitive_column": primary_sensitive,
                        "target_column": target_col,
                        "positive_class": str(positive_class),
                        "group": str(grp),
                        "disparity": info.get("disparity"),
                    }
                    for grp, info in disparities.items()
                    if str(info.get("disparity", "")).lower() == "true"
                ]
                needs_attention["cdd_disparities"] = cdd_flagged
                details["cdd"] = {
                    "sensitive": primary_sensitive,
                    "target": target_col,
                    "positive_class": str(positive_class),
                    "disparities": disparities,
                }
        except Exception as e:
            details["cdd"] = {"error": str(e)}
    else:
        details["cdd"] = {
            "error": "Requires sensitive attribute, target, and auto-positive class.",
        }

    present = finite_kpi_values(kpis)
    grade = sum(present) / len(present) if present else None

    return {
        "grade": grade,
        "grade_status": grade_label(grade),
        "auto_selection": selection,
        "kpis": kpis,
        "needs_attention": needs_attention,
        "details": details,
        "visualizations_deferred": not include_visualizations,
    }
