"""Section and visualization builder registries for the readiness report."""

from __future__ import annotations

from aidrin.report.data_quality import build_data_quality_section
from aidrin.report.fairness import build_fairness_bias_section
from aidrin.report.governance import build_data_governance_section
from aidrin.report.impact import build_impact_on_ai_section
from aidrin.report.overview import build_dataset_overview_section
from aidrin.report.visualizations import (
    build_data_governance_visualizations,
    build_data_quality_visualizations,
    build_dataset_overview_visualizations,
    build_fairness_bias_visualizations,
    build_impact_on_ai_visualizations,
)

SECTION_BUILDERS = {
    "dataset-overview": build_dataset_overview_section,
    "data-quality": build_data_quality_section,
    "impact-on-ai": build_impact_on_ai_section,
    "fairness-bias": build_fairness_bias_section,
    "data-governance": build_data_governance_section,
}

SECTION_RESPONSE_KEYS = {
    "dataset-overview": "dataset_overview",
    "data-quality": "data_quality",
    "impact-on-ai": "impact_on_ai",
    "fairness-bias": "fairness_bias",
    "data-governance": "data_governance",
}


def make_viz_builders(*, render_overview_charts=None):
    """Return visualization builders keyed by section slug.

    Overview charts need a Flask-side renderer; pass ``render_overview_charts``
    as ``(chart_df) -> dict``. Without it, overview viz returns an empty dict.
    """
    def overview_viz(file_info):
        if render_overview_charts is None:
            return {}
        return build_dataset_overview_visualizations(
            file_info, render_overview_charts=render_overview_charts
        )

    return {
        "dataset-overview": overview_viz,
        "data-quality": build_data_quality_visualizations,
        "impact-on-ai": build_impact_on_ai_visualizations,
        "fairness-bias": build_fairness_bias_visualizations,
        "data-governance": build_data_governance_visualizations,
    }


# Default registry without overview chart rendering (CLI/PDF can rebuild via factory).
VIZ_BUILDERS = make_viz_builders()
