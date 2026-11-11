"""Headless readiness-report PDF rendering via packaged templates + WeasyPrint.

Builds section (and optional visualization) payloads without Redis/session
cache, then renders with the same ``aidrin.report.pdf`` pipeline as the web
export. Requires WeasyPrint and its native libraries (pango, cairo, gdk-pixbuf).
Does not import the ``web`` package.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from aidrin.headless.runners import _build_file_info, using_selected_keys
from aidrin.report.builder import build_readiness_section
from aidrin.report.charts import (
    categorical_distribution_charts,
    continuous_bars,
    summary_histograms,
)
from aidrin.report.registry import SECTION_BUILDERS, make_viz_builders


def _overview_chart_renderer(chart_df):
    """Attach overview chart images for full PDFs / JSON --viz."""
    return {
        "categorical_charts": categorical_distribution_charts(chart_df),
        "histograms": summary_histograms(chart_df, figsize=(7, 4.5)),
        "histogram_bars": continuous_bars(chart_df, figsize=(7, 4.5)),
    }


def _build_sections(file_info) -> tuple[dict[str, Any], dict[str, str]]:
    """Build slug-keyed section payloads; collect per-section error messages."""
    sections: dict[str, Any] = {}
    section_errors: dict[str, str] = {}
    for slug in SECTION_BUILDERS:
        data = build_readiness_section(slug, file_info, include_visualizations=False)
        if data is None:
            data = {"error": f"Unknown section: {slug}"}
        if isinstance(data, dict) and data.get("error"):
            section_errors[slug] = data["error"]
        sections[slug] = data
    return sections, section_errors


def _build_visualizations(file_info) -> dict[str, dict]:
    """Build on-demand chart payloads for full-mode PDF (including overview)."""
    builders = make_viz_builders(render_overview_charts=_overview_chart_renderer)
    visualizations: dict[str, dict] = {}
    for slug, builder in builders.items():
        try:
            visualizations[slug] = builder(file_info) or {}
        except Exception as e:
            visualizations[slug] = {"error": f"{type(e).__name__}: {e}"}
    return visualizations


def run_readiness_report_pdf(
    file_path: str,
    file_type: Optional[str] = None,
    file_name: Optional[str] = None,
    *,
    mode: str = "scorecard",
    fair_metadata: Optional[str] = None,
    fair_standard: str = "auto",
    fair_data: Optional[Dict[str, Any]] = None,
    sections: Optional[Dict[str, Any]] = None,
    visualizations: Optional[Dict[str, Any]] = None,
    section_errors: Optional[Dict[str, str]] = None,
    loader: Optional[str] = None,
    selected_keys: Optional[List[str]] = None,
    verbose: bool = False,
) -> bytes:
    """Render a readiness report PDF and return the bytes.

    Parameters
    ----------
    mode
        ``"scorecard"`` (default) or ``"full"`` (includes section detail charts).
    fair_metadata / fair_data
        Optional FAIR appendix. Pass *fair_data* to reuse a prior
        ``calculate_fair_compliance`` result; otherwise *fair_metadata* is scored.
    sections / visualizations / section_errors
        Optional precomputed slug-keyed payloads (for CLI "compute once"). When
        omitted, sections are built here; visualizations are built only for
        ``mode="full"``.

    Raises
    ------
    ValueError
        Unknown *mode*, or dataset/metadata path missing.
    RuntimeError
        WeasyPrint or logo asset unavailable (same message as the web export).
    """
    # Lazy imports keep the JSON headless path free of WeasyPrint.
    from aidrin.file_handling.custom_loader import using_custom_loader
    from aidrin.headless.api import (
        _log_progress,
        _normalize_list,
        calculate_fair_compliance,
    )
    from aidrin.report.pdf import build_pdf_context, render_readiness_report_pdf

    if mode not in ("scorecard", "full"):
        raise ValueError(f"mode must be 'scorecard' or 'full', got {mode!r}")
    if not os.path.exists(file_path):
        raise ValueError(f"File not found: {file_path}")

    include_details = mode == "full"
    file_info = _build_file_info(
        file_path,
        file_type,
        file_name,
        selected_keys=_normalize_list(selected_keys),
    )
    resolved_name = file_info[1]

    if fair_data is None and fair_metadata:
        _log_progress(f"Scoring FAIR metadata: {fair_metadata}", verbose)
        fair_data = calculate_fair_compliance(
            fair_metadata,
            fair_standard,
            strip_visualizations=True,
        )

    with using_custom_loader(loader):
        with using_selected_keys(_normalize_list(selected_keys)):
            if sections is None:
                _log_progress("Building readiness sections for PDF", verbose)
                t0 = time.time()
                sections, built_errors = _build_sections(file_info)
                if section_errors is None:
                    section_errors = built_errors
                _log_progress(
                    f"Sections built in {time.time() - t0:.2f}s",
                    verbose,
                )
            elif section_errors is None:
                section_errors = {
                    slug: data["error"]
                    for slug, data in sections.items()
                    if isinstance(data, dict) and data.get("error")
                }

            if include_details and visualizations is None:
                _log_progress("Building readiness visualizations for full PDF", verbose)
                t0 = time.time()
                visualizations = _build_visualizations(file_info)
                _log_progress(
                    f"Visualizations built in {time.time() - t0:.2f}s",
                    verbose,
                )

    if visualizations is None:
        visualizations = {}
    if section_errors is None:
        section_errors = {}

    _log_progress(f"Rendering readiness PDF ({mode})", verbose)
    t0 = time.time()
    context = build_pdf_context(
        file_name=resolved_name,
        sections=sections,
        fair_data=fair_data,
        include_details=include_details,
        visualizations=visualizations,
        section_errors=section_errors,
    )
    pdf_bytes = render_readiness_report_pdf(context)
    _log_progress(f"PDF rendered in {time.time() - t0:.2f}s", verbose)
    return pdf_bytes
