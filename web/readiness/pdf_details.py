"""Prepare 'Show details' blocks for the full readiness report PDF."""

from __future__ import annotations

from html import escape
from typing import Any

_MAX_DETAIL_TABLE_ROWS = 50
_MAX_DETAIL_LIST_ITEMS = 50
_NUM_STAT_ORDER = (
    "count",
    "min",
    "25th percentile",
    "50th percentile",
    "mean",
    "75th percentile",
    "max",
    "std",
)
_VIZ_LABELS = {
    "completeness": "Completeness by feature",
    "outliers": "Outliers by feature",
    "numerical_correlation": "Numerical correlation",
    "categorical_correlation": "Categorical correlation (Theil's U)",
    "class_imbalance": "Class imbalance",
    "statistical_rate": "Statistical rate",
    "k_anonymity": "k-Anonymity",
    "l_diversity": "l-Diversity",
    "t_closeness": "t-Closeness",
    "entropy_risk": "Entropy risk",
    "multiple_attribute_risk": "Multiple-attribute linkage risk",
    "differential_privacy": "Differential privacy (illustrative)",
}


def _e(text: Any) -> str:
    return escape("" if text is None else str(text))


def _fmt_num(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


def _heading(text: str) -> dict[str, Any]:
    return {"type": "subheading", "text": text}


def _note(text: str) -> dict[str, Any]:
    return {"type": "note", "text": text}


def _table(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "table",
        "title": title,
        "headers": headers,
        "rows": rows,
        "note": note,
    }


def _list_block(title: str, entries: list[dict[str, str]]) -> dict[str, Any]:
    return {"type": "list", "title": title, "entries": entries}


def _chart_group(title: str, charts: list[dict[str, str]]) -> dict[str, Any] | None:
    if not charts:
        return None
    return {"type": "chart_group", "title": title, "charts": charts}


def _chart_wide(title: str, image_b64: str) -> dict[str, Any] | None:
    if not image_b64:
        return None
    return {"type": "chart_wide", "title": title, "image_b64": image_b64}


def _charts_from_mapping(
    mapping: dict[str, str] | None,
    *,
    label_fn=None,
) -> list[dict[str, str]]:
    if not mapping:
        return []
    charts = []
    for key, b64 in mapping.items():
        if not b64:
            continue
        if label_fn:
            label = label_fn(key)
        else:
            label = key.removesuffix("_light").replace("_", " ")
        charts.append({"label": label, "image_b64": b64})
    return charts


def _viz_chart(viz: dict[str, str] | None, key: str, title: str | None = None) -> dict[str, Any] | None:
    if not viz or not viz.get(key):
        return None
    return _chart_wide(title or _VIZ_LABELS.get(key, key.replace("_", " ").title()), viz[key])


def _section_blocks(blocks: list[dict[str, Any] | None], heading: str) -> dict[str, Any] | None:
    kept = [b for b in blocks if b]
    if not kept:
        return None
    return {"heading": heading, "blocks": kept}


def prepare_overview_details(section: dict, viz: dict[str, Any] | None) -> dict[str, Any] | None:
    blocks: list[dict[str, Any] | None] = []
    num_summary = section.get("numerical_summary") or {}
    num_meta = section.get("numerical_summary_meta") or {}
    features = list(num_summary.keys())[:_MAX_DETAIL_TABLE_ROWS]
    if features:
        all_stats = list((num_summary[features[0]] or {}).keys())
        stat_keys = [s for s in _NUM_STAT_ORDER if s in all_stats]
        stat_keys += [s for s in all_stats if s not in stat_keys]
        rows = []
        for feat in features:
            row = [feat]
            for stat in stat_keys:
                val = num_summary[feat].get(stat)
                if isinstance(val, float):
                    row.append(_fmt_num(val))
                elif val is None:
                    row.append("—")
                else:
                    row.append(str(val))
            rows.append(row)
        note = None
        total = num_meta.get("total") or len(num_summary)
        if total > len(features):
            note = f"Showing first {len(features)} of {total} numerical features."
        blocks.append(_table("Numerical summary statistics", ["Feature", *stat_keys], rows, note=note))

    profile_meta = section.get("feature_profiles_meta") or {}
    if profile_meta.get("truncated"):
        blocks.append(
            _note(
                "Distribution charts use the same prioritized features as the profile table "
                f"({profile_meta.get('shown', 0):,} of {profile_meta.get('total', 0):,})."
            )
        )

    cat_charts = (viz or {}).get("categorical_charts") or section.get("categorical_charts") or {}
    hist_charts = (viz or {}).get("histograms") or section.get("histograms") or {}
    cat_group = _chart_group("Categorical value distributions", _charts_from_mapping(cat_charts))
    hist_group = _chart_group(
        "Feature distributions (numerical)",
        _charts_from_mapping(hist_charts),
    )
    if cat_group:
        blocks.append(cat_group)
    if hist_group:
        blocks.append(hist_group)

    return _section_blocks(blocks, "Detailed statistics & distributions")


def prepare_data_quality_details(section: dict, viz: dict[str, Any] | None) -> dict[str, Any] | None:
    blocks: list[dict[str, Any] | None] = []
    det = section.get("details") or {}
    compl_b64 = (viz or {}).get("completeness") or (det.get("completeness") or {}).get("visualization")
    out_b64 = (viz or {}).get("outliers") or (det.get("outliers") or {}).get("visualization")
    if compl_b64:
        blocks.append(_chart_wide("Completeness by feature", compl_b64))
    elif (det.get("completeness") or {}).get("error"):
        blocks.append(_note(f"Completeness: {det['completeness']['error']}"))
    if out_b64:
        blocks.append(_chart_wide("Outliers by feature", out_b64))
    elif (det.get("outliers") or {}).get("error"):
        blocks.append(_note(f"Outliers: {det['outliers']['error']}"))
    return _section_blocks(blocks, "Detailed charts")


def prepare_impact_details(section: dict, viz: dict[str, Any] | None) -> dict[str, Any] | None:
    blocks: list[dict[str, Any] | None] = []
    top_pairs = section.get("top_pairs") or []
    if top_pairs:
        rows = [
            [p.get("a", ""), p.get("b", ""), _fmt_num(p.get("score"))]
            for p in top_pairs[:_MAX_DETAIL_TABLE_ROWS]
        ]
        blocks.append(_table("Most-related feature pairs", ["Feature A", "Feature B", "Score"], rows))

    det = section.get("details") or {}
    num_b64 = (viz or {}).get("numerical_correlation") or det.get("numerical_visualization")
    cat_b64 = (viz or {}).get("categorical_correlation") or det.get("categorical_visualization")
    method = det.get("numerical_method")
    num_title = f"Numerical correlation ({method})" if method else "Numerical correlation"
    if num_b64:
        blocks.append(_chart_wide(num_title, num_b64))
    if cat_b64:
        blocks.append(_chart_wide("Categorical correlation (Theil's U)", cat_b64))

    col_crit = ((section.get("auto_selection") or {}).get("selection_criteria") or {}).get(
        "columns_analyzed"
    ) or {}
    excluded = col_crit.get("excluded") or section.get("columns_dropped") or []
    if excluded:
        items = [
            {"primary": e.get("feature", ""), "secondary": e.get("reason", "")}
            for e in excluded[:_MAX_DETAIL_LIST_ITEMS]
        ]
        total = (col_crit.get("excluded_meta") or {}).get("total") or len(excluded)
        title = f"Excluded columns ({total})"
        if len(excluded) > len(items):
            items.append({"primary": f"+{len(excluded) - len(items)} more not shown", "secondary": ""})
        blocks.append(_list_block(title, items))

    return _section_blocks(blocks, "Detailed charts & tables")


def prepare_fairness_details(section: dict, viz: dict[str, Any] | None) -> dict[str, Any] | None:
    blocks: list[dict[str, Any] | None] = []
    det = section.get("details") or {}
    viz = viz or {}

    rep_charts = []
    for key, b64 in viz.items():
        if key.startswith("representation_rate.") and b64:
            col = key.split(".", 1)[1]
            rep_charts.append({"label": col, "image_b64": b64})
    rep_vis = (det.get("representation_rate") or {}).get("visualizations") or {}
    if not rep_charts:
        rep_charts = _charts_from_mapping(rep_vis)
    rep_group = _chart_group("Representation rate by sensitive attribute", rep_charts)
    if rep_group:
        blocks.append(rep_group)
    elif (det.get("representation_rate") or {}).get("error"):
        blocks.append(_note(f"Representation rate: {det['representation_rate']['error']}"))

    target = ((section.get("auto_selection") or {}).get("selection_criteria") or {}).get(
        "target_column"
    ) or {}
    target_name = target.get("selected") or "target"
    ci_b64 = viz.get("class_imbalance") or (det.get("class_imbalance") or {}).get("visualization")
    if ci_b64:
        blocks.append(_chart_wide(f"Class imbalance — {target_name}", ci_b64))
    elif (det.get("class_imbalance") or {}).get("error"):
        blocks.append(_note(f"Class imbalance: {det['class_imbalance']['error']}"))

    sr = det.get("statistical_rate") or {}
    sr_b64 = viz.get("statistical_rate") or sr.get("visualization")
    if sr_b64:
        blocks.append(
            _chart_wide(
                f"Statistical rate — {sr.get('sensitive', 'sensitive')} × {sr.get('target', target_name)}",
                sr_b64,
            )
        )
    elif sr.get("error"):
        blocks.append(_note(f"Statistical rate: {sr['error']}"))

    cdd = det.get("cdd") or {}
    disparities = cdd.get("disparities") or {}
    if disparities and not cdd.get("error"):
        rows = [[str(grp), str(info.get("disparity", ""))] for grp, info in disparities.items()]
        blocks.append(_table("Conditional demographic disparity (CDD)", ["Group", "Disparity"], rows))
    elif cdd.get("error"):
        blocks.append(_note(f"CDD: {cdd['error']}"))

    return _section_blocks(blocks, "Detailed charts & tables")


def prepare_governance_details(section: dict, viz: dict[str, Any] | None) -> dict[str, Any] | None:
    blocks: list[dict[str, Any] | None] = []
    det = section.get("details") or {}
    viz = viz or {}

    small_charts = []
    for key, title in _VIZ_LABELS.items():
        if key in ("k_anonymity", "l_diversity", "t_closeness", "entropy_risk", "differential_privacy"):
            b64 = viz.get(key) or (det.get(key) or {}).get("visualization")
            if b64:
                small_charts.append({"label": title, "image_b64": b64})
            elif (det.get(key) or {}).get("error"):
                blocks.append(_note(f"{title}: {det[key]['error']}"))
    mm_b64 = viz.get("multiple_attribute_risk") or (det.get("multiple_attribute_risk") or {}).get(
        "visualization"
    )
    if mm_b64:
        small_charts.append({"label": _VIZ_LABELS["multiple_attribute_risk"], "image_b64": mm_b64})
    mm_group = _chart_group("Privacy & linkage charts", small_charts)
    if mm_group:
        blocks.append(mm_group)

    single_risk = (det.get("single_attribute_risk") or {}).get("by_quasi_identifier") or {}
    if single_risk:
        rows = [
            [q, _fmt_num(v.get("mean_risk"))]
            for q, v in single_risk.items()
            if v.get("mean_risk") is not None
        ]
        if rows:
            blocks.append(
                _table(
                    "Single-attribute MM risk by quasi-identifier",
                    ["Quasi-identifier", "Mean risk"],
                    rows[:_MAX_DETAIL_TABLE_ROWS],
                )
            )

    hipaa_det = (det.get("hipaa") or {}).get("detected") or {}
    if hipaa_det:
        rows = [
            [
                col,
                ", ".join(info.get("potential_types_detected") or []),
                str(info.get("total_flags", "")),
            ]
            for col, info in hipaa_det.items()
        ]
        blocks.append(_table("HIPAA scan results", ["Column", "Types", "Flags"], rows[:_MAX_DETAIL_TABLE_ROWS]))

    qi_crit = ((section.get("auto_selection") or {}).get("selection_criteria") or {}).get(
        "quasi_identifiers"
    ) or {}
    qi_excluded = qi_crit.get("excluded") or []
    if qi_excluded:
        total = (qi_crit.get("excluded_meta") or {}).get("total") or len(qi_excluded)
        items = [
            {"primary": e.get("feature", ""), "secondary": e.get("reason", "")}
            for e in qi_excluded[:_MAX_DETAIL_LIST_ITEMS]
        ]
        if len(qi_excluded) > len(items):
            items.append({"primary": f"+{len(qi_excluded) - len(items)} more not shown", "secondary": ""})
        blocks.append(_list_block(f"Excluded quasi-identifier candidates ({total})", items))

    return _section_blocks(blocks, "Detailed charts & tables")


def build_pdf_section_details(
    sections: dict[str, dict],
    visualizations: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    """Return detail block trees keyed for the PDF template."""
    return {
        "overview": prepare_overview_details(
            sections.get("dataset-overview") or {},
            visualizations.get("dataset-overview"),
        ),
        "data_quality": prepare_data_quality_details(
            sections.get("data-quality") or {},
            visualizations.get("data-quality"),
        ),
        "impact": prepare_impact_details(
            sections.get("impact-on-ai") or {},
            visualizations.get("impact-on-ai"),
        ),
        "fairness": prepare_fairness_details(
            sections.get("fairness-bias") or {},
            visualizations.get("fairness-bias"),
        ),
        "governance": prepare_governance_details(
            sections.get("data-governance") or {},
            visualizations.get("data-governance"),
        ),
    }
