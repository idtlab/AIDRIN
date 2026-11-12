"""Data-quality section of the readiness report."""

from __future__ import annotations

from aidrin.report.common import finite_kpi_values, grade_label
from aidrin.structured_data_metrics.completeness import completeness
from aidrin.structured_data_metrics.duplicity import duplicity
from aidrin.structured_data_metrics.outliers import outliers


def build_data_quality_section(file_info, include_visualizations=False):
    """Compute the data-quality portion of the readiness report.

    Runs completeness, outliers, and duplicity (the same functions backing the
    Data Quality tab), then derives readiness-oriented KPIs (normalized so that
    higher is always better), an overall grade, and a "needs attention" list.

    Returns a JSON-serializable dict, or ``{"error": str}`` on failure.
    """
    # --- Completeness -----------------------------------------------------
    compl = completeness(file_info, include_visualization=include_visualizations)
    compl_scores = compl.get("Completeness scores", {}) or {}
    overall_completeness = compl.get("Overall Completeness")

    # --- Outliers ---------------------------------------------------------
    out = outliers(file_info, include_visualization=include_visualizations)
    out_scores_raw = out.get("Outlier scores", {}) if isinstance(out, dict) else {}
    overall_outlier = None
    out_scores = {}
    if isinstance(out_scores_raw, dict):
        overall_outlier = out_scores_raw.get("Overall outlier score")
        out_scores = {
            k: v for k, v in out_scores_raw.items() if k != "Overall outlier score"
        }
    outliers_error = out.get("Error") if isinstance(out, dict) else None

    # --- Duplicity --------------------------------------------------------
    dup = duplicity(file_info)
    overall_duplicity = (
        dup.get("Duplicity scores", {}).get("Overall duplicity of the dataset")
        if isinstance(dup, dict)
        else None
    )

    # --- Normalized KPIs (higher = better) --------------------------------
    completeness_kpi = overall_completeness
    uniqueness_kpi = (1 - overall_duplicity) if overall_duplicity is not None else None
    outlier_clean_kpi = (1 - overall_outlier) if overall_outlier is not None else None

    kpis = [
        {
            "id": "completeness",
            "label": "Completeness",
            "value": completeness_kpi,
            "status": grade_label(completeness_kpi),
            "hint": "Share of non-missing values across the dataset.",
        },
        {
            "id": "uniqueness",
            "label": "Uniqueness",
            "value": uniqueness_kpi,
            "status": grade_label(uniqueness_kpi),
            "hint": "1 − proportion of duplicate rows.",
        },
        {
            "id": "outlier_cleanliness",
            "label": "Outlier-cleanliness",
            "value": outlier_clean_kpi,
            "status": grade_label(outlier_clean_kpi),
            "hint": "1 − mean outlier proportion (IQR method) across numerical features.",
        },
    ]

    present = finite_kpi_values(kpis)
    grade = sum(present) / len(present) if present else None

    # --- Needs attention --------------------------------------------------
    incomplete = sorted(
        (
            {"feature": col, "completeness": score}
            for col, score in compl_scores.items()
            if isinstance(score, (int, float)) and score < 1.0
        ),
        key=lambda x: x["completeness"],
    )
    high_outliers = sorted(
        (
            {"feature": col, "outlier_proportion": score}
            for col, score in out_scores.items()
            if isinstance(score, (int, float)) and score > 0
        ),
        key=lambda x: x["outlier_proportion"],
        reverse=True,
    )

    return {
        "grade": grade,
        "grade_status": grade_label(grade),
        "auto_selection": {
            "selection_criteria": {
                "analysis_scope": {
                    "rule": (
                        "Completeness, outliers, and duplicity run on the full dataset "
                        "automatically — no column selection required."
                    ),
                    "selected": "all columns",
                },
            },
        },
        "kpis": kpis,
        "needs_attention": {
            "incomplete_features": incomplete,
            "outlier_features": high_outliers,
            "duplicate_rows": (
                overall_duplicity if overall_duplicity not in (None, 0) else 0
            ),
        },
        "details": {
            "completeness": {
                "overall": overall_completeness,
                "scores": compl_scores,
                "visualization": compl.get("Completeness Visualization") if include_visualizations else None,
                "visualization_deferred": not include_visualizations,
            },
            "outliers": {
                "overall": overall_outlier,
                "scores": out_scores,
                "visualization": out.get("Outliers Visualization") if include_visualizations and isinstance(out, dict) else None,
                "visualization_deferred": not include_visualizations,
                "error": outliers_error,
            },
            "duplicity": {"overall": overall_duplicity},
        },
        "visualizations_deferred": not include_visualizations,
    }
