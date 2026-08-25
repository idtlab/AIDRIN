"""Build view-model context and render readiness report PDF with WeasyPrint."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from flask import render_template
from markupsafe import Markup

from aidrin._version import __version__
from web.readiness.pdf_glossary import (
    FOOTNOTE_LABELS,
    READINESS_METRIC_GLOSSARY,
    _FEATURE_TYPE_ABBR,
    _STATUS_LABELS,
)

NEEDS_ATTENTION_TOP_N = 6
NEEDS_ATTENTION_MIN_N = 2
# Approximate printable lines per sub-category in a half-column PDF block.
NEEDS_ATTENTION_LINE_BUDGET = 10
_FAIR_PRINCIPLES = ("Findable", "Accessible", "Interoperable", "Reusable")


class SectionFootnotes:
    """Scoped footnote refs and definitions for one report section."""

    def __init__(self, registry: "FootnoteRegistry", scope: str) -> None:
        self._registry = registry
        self._scope = scope

    def ref(self, key: str | None) -> Markup:
        return self._registry.ref(key, self._scope)

    def entries(self) -> list[dict[str, Any]]:
        return self._registry.entries(self._scope)


class FootnoteRegistry:
    """Collect numbered footnote refs per section while the PDF template renders."""

    def __init__(self) -> None:
        self._scopes: dict[str, list[str]] = {}

    def section(self, scope: str) -> SectionFootnotes:
        return SectionFootnotes(self, scope)

    def ref(self, key: str | None, scope: str) -> Markup:
        if not key or key not in READINESS_METRIC_GLOSSARY:
            return Markup("")
        order = self._scopes.setdefault(scope, [])
        if key not in order:
            order.append(key)
        num = order.index(key) + 1
        return Markup(f'<sup class="footnote-ref">{num}</sup>')

    def entries(self, scope: str) -> list[dict[str, Any]]:
        return [
            {
                "number": idx,
                "term": FOOTNOTE_LABELS.get(key, key.replace("_", " ").title()),
                "definition": READINESS_METRIC_GLOSSARY[key],
            }
            for idx, key in enumerate(self._scopes.get(scope, []), start=1)
        ]


def _status_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.9:
        return "good"
    if score >= 0.7:
        return "warning"
    return "poor"


def fmt_pct(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "N/A"


def fmt_num(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


def fmt_bytes(value: int | float | None) -> str:
    if value is None:
        return "—"
    try:
        nbytes = float(value)
    except (TypeError, ValueError):
        return "—"
    if nbytes < 1024:
        return f"{int(nbytes)} B"
    if nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes / (1024 * 1024):.1f} MB"


def _e(text: Any) -> str:
    return escape("" if text is None else str(text))


def _na_row(primary: str, secondary: str | None = None, value: str | None = None) -> dict:
    return {"primary": Markup(primary), "secondary": Markup(secondary) if secondary else None, "value": value}


def _na_row_line_estimate(row: dict) -> float:
    """Rough vertical cost of one needs-attention list row in the PDF."""
    return 2.0 if row.get("secondary") else 1.0


def _cap_na_rows(
    rows: list[dict],
    *,
    max_rows: int = NEEDS_ATTENTION_TOP_N,
    line_budget: float = NEEDS_ATTENTION_LINE_BUDGET,
    min_rows: int = NEEDS_ATTENTION_MIN_N,
) -> tuple[list[dict], int]:
    """Trim rows so a needs-attention sub-category is less likely to span a full page."""
    if not rows:
        return [], 0

    kept: list[dict] = []
    used = 0.0
    for row in rows:
        est = _na_row_line_estimate(row)
        if kept and (used + est > line_budget or len(kept) >= max_rows):
            break
        kept.append(row)
        used += est

    if not kept:
        kept = [rows[0]]
        used = _na_row_line_estimate(rows[0])

    while len(kept) > min_rows and used > line_budget:
        removed = kept.pop()
        used -= _na_row_line_estimate(removed)

    return kept, max(0, len(rows) - len(kept))


def _na_block(
    title: str,
    glossary_key: str | None,
    context: str | None,
    rows: list[dict],
    *,
    tone: str = "default",
) -> dict:
    header_lines = 1.5 + (1.5 if context else 0.0)
    line_budget = max(float(NEEDS_ATTENTION_MIN_N), NEEDS_ATTENTION_LINE_BUDGET - header_lines)
    kept, more_count = _cap_na_rows(rows, line_budget=line_budget)
    return {
        "title": title,
        "glossary_key": glossary_key,
        "context": Markup(context) if context else None,
        "rows": kept,
        "more_count": more_count,
        "tone": tone,
    }


def _kpi_tiles(section: dict) -> list[dict]:
    tiles = []
    for kpi in section.get("kpis") or []:
        value = kpi.get("value")
        display = fmt_pct(value)
        kpi_id = kpi.get("id")
        if kpi_id == "label_balance" and kpi.get("raw_imbalance_degree") is not None:
            display = f"ID {fmt_num(kpi['raw_imbalance_degree'])}"
        elif kpi.get("raw_count") is not None:
            display = f"{kpi['raw_count']} flagged"
        elif kpi_id == "anonymity_k" and kpi.get("raw_k") is not None:
            display = f"k={kpi['raw_k']}"
        elif kpi_id == "diversity_l" and kpi.get("raw_l") is not None:
            display = f"l={kpi['raw_l']}"
        elif kpi_id == "distribution_t" and kpi.get("raw_t") is not None:
            display = f"t={fmt_num(kpi['raw_t'])}"
        elif kpi_id == "single_linkage_risk" and kpi.get("raw_worst_mean") is not None:
            display = f"{fmt_num(kpi['raw_worst_mean'])} risk"
        elif kpi_id == "linkage_risk" and kpi.get("raw_mean") is not None:
            display = f"{fmt_num(kpi['raw_mean'])} risk"
        elif kpi_id == "phi_exposure" and kpi.get("columns_flagged") is not None:
            display = "None" if kpi["columns_flagged"] == 0 else f"{kpi['columns_flagged']} col(s)"
        width = 0 if value is None else max(0, min(100, round(float(value) * 100)))
        tiles.append(
            {
                "id": kpi_id,
                "label": kpi.get("label", ""),
                "hint": kpi.get("hint", ""),
                "status": kpi.get("status") or _status_label(value),
                "display": display,
                "width_pct": width,
            }
        )
    return tiles


def _enrich_profile(profile: dict) -> dict:
    feat_type = profile.get("type") or ""
    return {
        **profile,
        "type_abbr": _FEATURE_TYPE_ABBR.get(
            feat_type, feat_type[:1].upper() if feat_type else "—"
        ),
        "status_label": _STATUS_LABELS.get(profile.get("status", ""), "—"),
    }


def _prepare_overview(overview: dict) -> dict:
    meta = overview.get("file_metadata") or {}
    profiles = overview.get("feature_profiles") or []
    profile_meta = overview.get("feature_profiles_meta") or {}
    status_counts = profile_meta.get("status_counts") or {}
    other_count = (meta.get("datetime_count") or 0) + (meta.get("boolean_count") or 0)
    return {
        "meta": meta,
        "profiles": [_enrich_profile(p) for p in profiles],
        "profile_meta": profile_meta,
        "other_count": other_count,
        "poor_count": status_counts.get("poor", sum(1 for p in profiles if p.get("status") == "poor")),
        "warn_count": status_counts.get(
            "warning", sum(1 for p in profiles if p.get("status") == "warning")
        ),
    }


def _prepare_data_quality(dq: dict) -> dict:
    na = dq.get("needs_attention") or {}
    incomplete = na.get("incomplete_features") or []
    outlier_feats = na.get("outlier_features") or []
    dup_rows = na.get("duplicate_rows") or 0
    blocks = []
    if incomplete:
        rows = [
            _na_row(_e(f.get("feature")), value=f"{fmt_pct(f.get('completeness'))} complete")
            for f in incomplete
        ]
        blocks.append(_na_block(f"Incomplete features ({len(incomplete)})", "completeness", None, rows))
    if outlier_feats:
        rows = [
            _na_row(_e(f.get("feature")), value=f"{fmt_pct(f.get('outlier_proportion'))} outliers")
            for f in outlier_feats
        ]
        blocks.append(
            _na_block(f"Features with outliers ({len(outlier_feats)})", "outlier_cleanliness", None, rows)
        )
    if dup_rows:
        blocks.append(
            {
                "title": "Duplicate rows",
                "glossary_key": "uniqueness",
                "context": None,
                "rows": [],
                "more_count": 0,
                "message": f"{fmt_pct(dup_rows)} of rows are exact duplicates.",
            }
        )
    scope = (dq.get("auto_selection") or {}).get("selection_criteria", {}).get("analysis_scope", {})
    return {
        "grade": dq.get("grade"),
        "grade_status": dq.get("grade_status"),
        "kpis": _kpi_tiles(dq),
        "auto_selection": scope,
        "needs_attention": blocks,
        "empty_message": "No data quality issues detected — all features complete, no duplicates, no outliers.",
    }


def _pair_rows(pairs: list[dict], fmt_score) -> list[dict]:
    return [
        _na_row(
            f"<span class='mono'>{_e(p.get('a'))}</span> ↔ <span class='mono'>{_e(p.get('b'))}</span>",
            value=f"|score| {fmt_score(p.get('score'))}",
        )
        for p in pairs
    ]


def _prepare_impact(impact: dict) -> dict:
    auto_sel = impact.get("auto_selection") or {}
    crit = auto_sel.get("selection_criteria") or {}
    col_crit = crit.get("columns_analyzed") or {}
    thresholds = crit.get("thresholds") or {}
    na = impact.get("needs_attention") or {}
    leakage = na.get("leakage_pairs") or impact.get("leakage_pairs") or []
    redundant = na.get("redundant_pairs") or impact.get("redundant_pairs") or []
    isolated = na.get("isolated_features") or impact.get("isolated_features") or []
    selected_cols = col_crit.get("selected") or []
    preview = ", ".join(selected_cols[:8]) + ("…" if len(selected_cols) > 8 else "")
    blocks = []
    if leakage:
        blocks.append(
            _na_block(
                f"Leakage risk (|score| ≥ 0.95) ({len(leakage)})",
                "leakage_risk_pairs",
                None,
                _pair_rows(leakage, fmt_num),
                tone="red",
            )
        )
    if redundant:
        blocks.append(
            _na_block(
                f"Redundant pairs (|score| ≥ 0.8) ({len(redundant)})",
                "redundant_pairs",
                None,
                _pair_rows(redundant, fmt_num),
                tone="amber",
            )
        )
    if isolated:
        rows = [_na_row(f"<span class='mono'>{_e(f)}</span>") for f in isolated]
        blocks.append(
            _na_block(
                f"Isolated features ({len(isolated)})",
                "isolated_features",
                None,
                rows,
                tone="amber",
            )
        )
    return {
        "grade": impact.get("grade"),
        "grade_status": impact.get("grade_status"),
        "kpis": _kpi_tiles(impact),
        "columns_analyzed": impact.get("columns_analyzed") or len(selected_cols),
        "columns_preview": preview or "none",
        "columns_rule": col_crit.get("rule", ""),
        "excluded_count": len(col_crit.get("excluded") or impact.get("columns_dropped") or []),
        "thresholds": thresholds,
        "needs_attention": blocks,
        "empty_message": "No redundancy, leakage risk, or isolated features detected.",
    }


def _prepare_fairness(fb: dict) -> dict:
    sel = fb.get("auto_selection") or {}
    criteria = sel.get("selection_criteria") or {}
    sens_crit = criteria.get("sensitive_attributes") or {}
    target_crit = criteria.get("target_column") or {}
    pos_crit = criteria.get("positive_class") or {}
    thresholds = criteria.get("thresholds") or {}
    na = fb.get("needs_attention") or {}
    blocks = []

    rep_imbalance = na.get("representation_imbalance") or []
    if rep_imbalance:
        rows = []
        for item in rep_imbalance:
            hint = ""
            pairs = item.get("flagged_pairs") or []
            if pairs:
                hint = (
                    f"Worst pair: {_e(pairs[0].get('pair'))} "
                    f"(ratio {fmt_num(pairs[0].get('ratio'))})"
                )
            rows.append(
                _na_row(
                    f"<span class='mono'>{_e(item.get('column'))}</span>",
                    hint,
                    f"max ratio {fmt_num(item.get('max_ratio'))}",
                )
            )
        blocks.append(
            _na_block(
                f"Representation imbalance ({len(rep_imbalance)})",
                "representation_imbalance",
                "Sensitive attributes with extreme category probability ratios",
                rows,
                tone="amber",
            )
        )

    minorities = na.get("minority_classes") or []
    if minorities:
        target_col = minorities[0].get("target_column") or target_crit.get("selected") or "target"
        rows = [
            _na_row(
                _e(m.get("class")),
                f"Class in <span class='mono'>{_e(target_col)}</span>",
                f"{fmt_pct(m.get('share'))} share",
            )
            for m in minorities
        ]
        blocks.append(
            _na_block(
                f"Minority classes ({len(minorities)})",
                "minority_classes",
                f"Target column: <span class='mono'>{_e(target_col)}</span>",
                rows,
                tone="amber",
            )
        )

    outcome_disp = na.get("outcome_disparities") or []
    if outcome_disp:
        sens_col = outcome_disp[0].get("sensitive_column") or sel.get("primary_sensitive") or "—"
        tgt_col = outcome_disp[0].get("target_column") or target_crit.get("selected") or "—"
        rows = [
            _na_row(
                f"<span class='mono'>{_e(d.get('target_column') or tgt_col)}</span> = {_e(d.get('class'))}",
                f"Outcome rates vary by sensitive <span class='mono'>{_e(d.get('sensitive_column') or sens_col)}</span>",
                f"TSD {fmt_num(d.get('tsd'))}",
            )
            for d in outcome_disp
        ]
        blocks.append(
            _na_block(
                f"Outcome-rate disparities ({len(outcome_disp)})",
                "outcome_disparities",
                f"Sensitive <span class='mono'>{_e(sens_col)}</span> × target <span class='mono'>{_e(tgt_col)}</span>",
                rows,
                tone="amber",
            )
        )

    cdd_disp = na.get("cdd_disparities") or []
    if cdd_disp:
        sens_col = cdd_disp[0].get("sensitive_column") or sel.get("primary_sensitive") or "—"
        tgt_col = cdd_disp[0].get("target_column") or target_crit.get("selected") or "—"
        pos_class = cdd_disp[0].get("positive_class") or pos_crit.get("selected") or "—"
        rows = [
            _na_row(
                f"<span class='mono'>{_e(d.get('sensitive_column') or sens_col)}</span> = {_e(d.get('group'))}",
                (
                    f"CDD vs target <span class='mono'>{_e(d.get('target_column') or tgt_col)}</span> "
                    f"(positive: {_e(d.get('positive_class', pos_class))})"
                ),
            )
            for d in cdd_disp
        ]
        blocks.append(
            _na_block(
                f"CDD flagged groups ({len(cdd_disp)})",
                "cdd_disparities",
                f"Sensitive <span class='mono'>{_e(sens_col)}</span> × target <span class='mono'>{_e(tgt_col)}</span>",
                rows,
                tone="red",
            )
        )

    return {
        "grade": fb.get("grade"),
        "grade_status": fb.get("grade_status"),
        "kpis": _kpi_tiles(fb),
        "sensitive_attributes": sens_crit,
        "target_column": target_crit,
        "positive_class": pos_crit,
        "primary_sensitive": sel.get("primary_sensitive"),
        "thresholds": thresholds,
        "needs_attention": blocks,
        "empty_message": "No fairness issues detected under the automated thresholds.",
    }


def _prepare_governance(gov: dict) -> dict:
    sel = gov.get("auto_selection") or {}
    criteria = sel.get("selection_criteria") or {}
    qi_crit = criteria.get("quasi_identifiers") or {}
    sens_crit = criteria.get("sensitive_attribute") or {}
    id_crit = criteria.get("id_column") or {}
    hipaa_crit = criteria.get("hipaa_scan_columns") or {}
    thresholds = criteria.get("thresholds") or {}
    na = gov.get("needs_attention") or {}
    blocks = []

    low_anon = na.get("low_anonymity") or []
    if low_anon:
        rows = []
        for item in low_anon:
            rows.append(
                _na_row(
                    f"{_e(item.get('metric'))}: k = {item.get('value')}",
                    _e(item.get("detail")) if item.get("detail") else None,
                    (
                        f"{item.get('singleton_count')} singleton group(s)"
                        if item.get("singleton_count") is not None
                        else None
                    ),
                )
            )
            if item.get("worst_single_qi"):
                wsq = item["worst_single_qi"]
                rows.append(
                    _na_row(
                        f"Highest single-QI risk: <span class='mono'>{_e(wsq.get('feature'))}</span>",
                        "May contribute to low k when combined with other quasi-identifiers",
                        f"risk {fmt_num(wsq.get('mean_risk'))}",
                    )
                )
        qi_list = low_anon[0].get("quasi_identifiers") or []
        ctx = (
            f"Quasi-identifiers: <span class='mono'>{_e(', '.join(qi_list))}</span>"
            if qi_list
            else None
        )
        blocks.append(
            _na_block(f"Low anonymity ({len(low_anon)})", "low_anonymity", ctx, rows, tone="red")
        )

    hipaa_phi = na.get("hipaa_phi") or []
    if hipaa_phi:
        rows = [
            _na_row(
                f"<span class='mono'>{_e(x.get('column'))}</span>",
                _e(", ".join(x.get("types") or []) or "Pattern match"),
                f"{x.get('total_flags')} flag(s)",
            )
            for x in hipaa_phi
        ]
        blocks.append(
            _na_block(
                f"HIPAA pattern matches ({len(hipaa_phi)})",
                "hipaa_phi",
                "Scanned text-like columns for HIPAA-style identifier patterns",
                rows,
                tone="red",
            )
        )

    linkage_na = na.get("high_linkage_risk") or []
    if linkage_na:
        rows = []
        for item in linkage_na:
            qis = item.get("quasi_identifiers") or item.get("features") or []
            feat = item.get("feature")
            label = (
                f"<span class='mono'>{_e(feat)}</span>"
                if feat
                else f"<span class='mono'>{_e(', '.join(qis))}</span>"
            )
            rows.append(
                _na_row(
                    f"{_e(item.get('metric'))}: {label}",
                    (
                        _e(item.get("detail"))
                        if item.get("detail")
                        else (
                            f"Quasi-identifiers: {_e(', '.join(qis))}" if qis else None
                        )
                    ),
                    f"risk {fmt_num(item.get('mean_risk'))}",
                )
            )
        blocks.append(
            _na_block(
                f"High linkage risk ({len(linkage_na)})",
                "high_linkage_risk",
                None,
                rows,
                tone="amber",
            )
        )

    attr_disc = na.get("attribute_disclosure") or []
    if attr_disc:
        rows = [
            _na_row(
                f"{_e(x.get('metric'))} = {fmt_num(x.get('value'))}",
                _e(x.get("detail")) if x.get("detail") else None,
            )
            for x in attr_disc
        ]
        sens = attr_disc[0].get("sensitive_attribute")
        ctx = f"Sensitive: <span class='mono'>{_e(sens)}</span>" if sens else None
        blocks.append(
            _na_block(
                f"Attribute disclosure risk ({len(attr_disc)})",
                "attribute_disclosure",
                ctx,
                rows,
                tone="amber",
            )
        )

    hipaa_selected = hipaa_crit.get("selected") or []
    return {
        "grade": gov.get("grade"),
        "grade_status": gov.get("grade_status"),
        "kpis": _kpi_tiles(gov),
        "quasi_identifiers": qi_crit,
        "sensitive_attribute": sens_crit,
        "id_column": id_crit,
        "hipaa_scan": hipaa_selected,
        "thresholds": thresholds,
        "small_sample_warning": gov.get("small_sample_warning"),
        "needs_attention": blocks,
        "empty_message": "No governance issues detected under the automated thresholds.",
    }


def _fair_check_failed(value: Any) -> bool:
    if value is False:
        return True
    s = str(value)
    return s in ("Fail", "No") or "CHECK FAILED" in s


def _fair_value_rows(obj: Any) -> list[dict[str, Any]]:
    """Flatten a FAIR principle detail object into printable table rows."""
    rows: list[dict[str, Any]] = []
    if not isinstance(obj, dict):
        return rows
    for key, val in obj.items():
        if isinstance(val, dict):
            rows.append({"label": key, "is_group": True})
            rows.extend(_fair_value_rows(val))
        else:
            failed = _fair_check_failed(val)
            rows.append(
                {
                    "label": key,
                    "is_group": False,
                    "found": not failed,
                    "status_label": "Missing" if failed else "Found",
                }
            )
    return rows


def _prepare_fair_compliance(fair_data: dict | None) -> dict | None:
    if not fair_data or fair_data.get("error"):
        return None
    checks = fair_data.get("FAIR Compliance Checks") or {}
    total_check = checks.get("Total Checks", "")
    match = re.search(r"(\d+)/(\d+)", str(total_check))
    total_passed = int(match.group(1)) if match else 0
    total_expected = int(match.group(2)) if match else 1
    total_pct = round((total_passed / total_expected) * 100) if total_expected else 0
    principles = []
    for principle in _FAIR_PRINCIPLES:
        check_str = checks.get(f"{principle} Checks", "0/0")
        m = re.search(r"(\d+)/(\d+)", str(check_str))
        passed = int(m.group(1)) if m else 0
        total = int(m.group(2)) if m else 1
        pct = round((passed / total) * 100) if total else 0
        detail = fair_data.get(principle)
        rows = _fair_value_rows(detail) if isinstance(detail, dict) else []
        principles.append(
            {
                "name": principle,
                "passed": passed,
                "total": total,
                "pct": pct,
                "check_str": check_str,
                "detail": detail,
                "rows": rows,
            }
        )
    return {
        "checks": checks,
        "total_passed": total_passed,
        "total_expected": total_expected,
        "total_pct": total_pct,
        "principles": principles,
    }


def _collect_glossary_keys(
    prepared: dict[str, dict], fair_data: dict | None
) -> list[dict[str, Any]]:
    keys = {
        "feature_profile",
        "feature_type_codes",
        "pct_missing",
        "n_unique",
        "pct_dominant",
        "profile_status",
        "overall_dq_grade",
        "analysis_scope",
        "overall_impact_grade",
        "overall_fairness_grade",
        "overall_governance_grade",
    }
    for section_key in ("data_quality", "impact", "fairness", "governance"):
        section = prepared.get(section_key) or {}
        for kpi in section.get("kpis") or []:
            if kpi.get("id"):
                keys.add(kpi["id"])
        for block in section.get("needs_attention") or []:
            if block.get("glossary_key"):
                keys.add(block["glossary_key"])
    glossary = []
    for key in sorted(keys):
        definition = READINESS_METRIC_GLOSSARY.get(key)
        if definition:
            glossary.append(
                {
                    "term": FOOTNOTE_LABELS.get(key, key.replace("_", " ").title()),
                    "definition": definition,
                }
            )
    if fair_data:
        glossary.append(
            {
                "term": "FAIR compliance",
                "definition": READINESS_METRIC_GLOSSARY["fair_compliance"],
            }
        )
    return glossary


def build_pdf_context(
    *,
    file_name: str,
    sections: dict[str, dict],
    fair_data: dict | None = None,
    include_details: bool = False,
    visualizations: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Assemble Jinja context for the readiness report PDF."""
    overview = _prepare_overview(sections.get("dataset-overview") or {})
    data_quality = _prepare_data_quality(sections.get("data-quality") or {})
    impact = _prepare_impact(sections.get("impact-on-ai") or {})
    fairness = _prepare_fairness(sections.get("fairness-bias") or {})
    governance = _prepare_governance(sections.get("data-governance") or {})
    fair_compliance = _prepare_fair_compliance(fair_data)
    prepared = {
        "data_quality": data_quality,
        "impact": impact,
        "fairness": fairness,
        "governance": governance,
    }
    glossary = _collect_glossary_keys(prepared, fair_data)
    section_details: dict[str, dict[str, Any] | None] = {}
    if include_details:
        from web.readiness.pdf_details import (
            build_pdf_section_details,
            prepare_fair_compliance_details,
        )

        section_details = build_pdf_section_details(sections, visualizations or {})
        section_details["fair"] = prepare_fair_compliance_details(fair_data)
    return {
        "file_name": file_name,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "app_version": __version__,
        "include_details": include_details,
        "overview": overview,
        "data_quality": data_quality,
        "impact": impact,
        "fairness": fairness,
        "governance": governance,
        "fair_compliance": fair_compliance,
        "section_details": section_details,
        "glossary": glossary,
        "fmt_pct": fmt_pct,
        "fmt_num": fmt_num,
        "fmt_bytes": fmt_bytes,
    }


def pdf_filename(file_name: str, *, full: bool = False) -> str:
    stem = re.sub(r"\.[^.]+$", "", file_name or "dataset")
    stem = re.sub(r"[^\w.-]", "_", stem) or "dataset"
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = "readiness-report-full" if full else "readiness-report"
    return f"{prefix}-{stem}-{date}.pdf"


def readiness_pdf_logo_uri(app) -> str:
    """Return a file URI for the AIDRIN logo used in readiness report PDFs."""
    images_dir = Path(app.root_path).resolve().parent / "aidrin" / "images"
    for name in ("logoNoBackground.png", "logo.png"):
        logo_path = images_dir / name
        if logo_path.is_file():
            return logo_path.as_uri()
    raise RuntimeError(f"AIDRIN logo not found under {images_dir}")


def _weasyprint():
    """Import WeasyPrint lazily and return its (HTML, CSS) classes.

    Kept as a separate module-level hook so PDF rendering can be exercised in
    tests without importing WeasyPrint or its native libraries.
    """
    try:
        from weasyprint import CSS, HTML
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "WeasyPrint could not be loaded. Install the package and its native "
            "dependencies (pango, cairo, gdk-pixbuf); see the installation docs."
        ) from exc
    return HTML, CSS


def _pdf_allowed_file_roots(app) -> list[Path]:
    """Local directories WeasyPrint may read while rendering a readiness PDF."""
    web_root = Path(app.root_path).resolve()
    return [
        web_root / "static",
        web_root.parent / "aidrin" / "images",
    ]


def _make_readiness_pdf_url_fetcher(allowed_roots: list[Path]):
    """Build a WeasyPrint URL fetcher that blocks remote and arbitrary file access.

    Uploaded dataset values can become HTML in the PDF; without this guard,
    WeasyPrint's default fetcher would resolve attacker-controlled http(s)/file
    URLs (SSRF / local file read) during rendering.
    """
    from urllib.parse import unquote, urlparse

    resolved_roots = [root.resolve() for root in allowed_roots]

    def _is_under_allowed_root(path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        for root in resolved_roots:
            try:
                if resolved == root or resolved.is_relative_to(root):
                    return True
            except ValueError:
                continue
        return False

    def url_fetcher(url, timeout=10, ssl_context=None):
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("data", "file"):
            raise ValueError(f"Blocked URL scheme for readiness PDF: {scheme or 'unknown'}")
        if scheme == "file":
            # urlparse leaves an empty host and path like /tmp/... on POSIX.
            file_path = Path(unquote(parsed.path))
            if parsed.netloc and parsed.netloc not in ("", "localhost"):
                raise ValueError(f"Blocked non-local file URL: {url}")
            if not _is_under_allowed_root(file_path):
                raise ValueError(f"Blocked file URL outside allowed roots: {url}")
        from weasyprint import default_url_fetcher

        return default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context)

    return url_fetcher


def render_readiness_report_pdf(app, context: dict[str, Any]) -> bytes:
    """Render PDF bytes from a prepared context dict."""
    HTML, CSS = _weasyprint()

    footnotes = FootnoteRegistry()
    render_context = {
        **context,
        "footnotes": footnotes,
        "logo_url": readiness_pdf_logo_uri(app),
    }
    html = render_template("readiness_report/pdf.html", **render_context)
    static_root = Path(app.root_path) / "static"
    css_path = static_root / "css" / "readiness_report_print.css"
    base_url = static_root.as_uri() + "/"
    url_fetcher = _make_readiness_pdf_url_fetcher(_pdf_allowed_file_roots(app))
    return HTML(string=html, base_url=base_url, url_fetcher=url_fetcher).write_pdf(
        stylesheets=[CSS(filename=str(css_path))]
    )
