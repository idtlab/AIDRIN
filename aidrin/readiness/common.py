"""Shared helpers and constants for readiness report section builders."""

from __future__ import annotations

import math

# Cap for excluded/dropped detail lists in report JSON (Impact, Fairness, Governance, …).
READINESS_MAX_DETAIL_LIST_ITEMS = 50


def grade_label(score):
    """Map a 0–1 readiness score to a coarse status label."""
    try:
        if score is None or not math.isfinite(float(score)):
            return "unknown"
    except (TypeError, ValueError):
        return "unknown"
    if score >= 0.9:
        return "good"
    if score >= 0.7:
        return "warning"
    return "poor"


def finite_kpi_values(kpis):
    """Return finite numeric KPI values (exclude None / NaN / Inf)."""
    present = []
    for kpi in kpis:
        value = kpi.get("value") if isinstance(kpi, dict) else None
        try:
            if value is not None and math.isfinite(float(value)):
                present.append(value)
        except (TypeError, ValueError):
            continue
    return present


def cap_detail_list(items, max_items):
    """Return a capped list plus metadata for UI/PDF truncation notes."""
    total = len(items)
    if total <= max_items:
        return items, {"total": total, "shown": total, "truncated": False}
    return items[:max_items], {
        "total": total,
        "shown": max_items,
        "truncated": True,
    }

