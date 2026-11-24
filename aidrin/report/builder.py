"""Orchestrate readiness-report section builders into one JSON payload."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Iterable, Mapping, Optional

from aidrin.report.overview import build_dataset_overview_section
from aidrin.report.registry import (
    SECTION_BUILDERS,
    SECTION_RESPONSE_KEYS,
)

logger = logging.getLogger(__name__)

SectionBuilder = Callable[..., dict[str, Any]]


def build_readiness_section(
    section: str,
    file_info,
    include_visualizations: bool = False,
    *,
    builders: Optional[Mapping[str, SectionBuilder]] = None,
    error_message: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Build one readiness-report section; return error dict on failure.

    Unknown *section* names return ``None``. Builder exceptions become
    ``{"error": "<Type>: <message>"}`` so headless callers can see the cause.
    Pass *error_message* to replace that detail (e.g. web-facing generic text).
    """
    registry = builders if builders is not None else SECTION_BUILDERS
    builder = registry.get(section)
    if builder is None:
        return None
    try:
        return builder(file_info, include_visualizations=include_visualizations)
    except Exception as e:
        logger.error("Readiness report — %s error: %s", section, e, exc_info=True)
        if error_message is not None:
            return {"error": error_message}
        return {"error": f"{type(e).__name__}: {e}"}


def build_readiness_report(
    file_info,
    *,
    include_visualizations: bool = False,
    fair_data: Optional[dict[str, Any]] = None,
    sections: Optional[Iterable[str]] = None,
    section_builders: Optional[Mapping[str, SectionBuilder]] = None,
    render_overview_charts=None,
    section_error_message: Optional[str] = None,
) -> dict[str, Any]:
    """Build the full readiness report JSON (no Flask session or cache).

    The response shape matches ``GET /readiness-report`` section keys
    (``dataset_overview``, ``data_quality``, …). Optional FAIR results are
    attached as ``fair_compliance`` when *fair_data* is provided.

    Parameters
    ----------
    file_info
        ``(file_path, file_name, file_type)`` tuple for ``read_file``.
    include_visualizations
        When true, section builders embed chart payloads where they support it.
    fair_data
        Optional FAIR compliance result dict (from ``calculate_fair_compliance``).
    sections
        Optional subset of section slugs; default is all registered sections.
    section_builders
        Optional override of ``SECTION_BUILDERS`` (e.g. web overview wrapper).
    render_overview_charts
        Callable ``(chart_df) -> dict`` for overview charts. When provided, the
        overview section builder is wired to use it whenever visualizations are
        requested.
    section_error_message
        Optional generic error text for failed sections (web uses this so
        exception detail stays in logs only).
    """
    builders = dict(section_builders if section_builders is not None else SECTION_BUILDERS)

    if render_overview_charts is not None:
        charts = render_overview_charts

        def _overview(file_info_, include_visualizations=False):
            return build_dataset_overview_section(
                file_info_,
                include_visualizations=include_visualizations,
                render_overview_charts=charts if include_visualizations else None,
            )

        builders["dataset-overview"] = _overview

    slugs = list(sections) if sections is not None else list(builders.keys())
    response: dict[str, Any] = {"success": True}

    for slug in slugs:
        start = time.time()
        data = build_readiness_section(
            slug,
            file_info,
            include_visualizations=include_visualizations,
            builders=builders,
            error_message=section_error_message,
        )
        elapsed = round(time.time() - start, 2)
        if data is None:
            data = {"error": f"Unknown section: {slug}"}
        if isinstance(data, dict):
            data = {**data, "build_time_seconds": elapsed}
        response_key = SECTION_RESPONSE_KEYS.get(slug, slug.replace("-", "_"))
        response[response_key] = data

    if fair_data is not None:
        response["fair_compliance"] = fair_data

    return response
