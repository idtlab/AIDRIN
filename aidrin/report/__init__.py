"""AI Data Readiness Report builders and shared helpers (web + headless)."""

from aidrin.report.common import (
    READINESS_MAX_DETAIL_LIST_ITEMS,
    cap_detail_list,
    classify_feature_type,
    finite_kpi_values,
    grade_label,
)
from aidrin.report.data_quality import build_data_quality_section
from aidrin.report.fairness import build_fairness_bias_section
from aidrin.report.governance import build_data_governance_section
from aidrin.report.impact import build_impact_on_ai_section
from aidrin.report.overview import build_dataset_overview_section
from aidrin.report.registry import (
    SECTION_BUILDERS,
    SECTION_RESPONSE_KEYS,
    VIZ_BUILDERS,
    make_viz_builders,
)

__all__ = [
    "READINESS_MAX_DETAIL_LIST_ITEMS",
    "SECTION_BUILDERS",
    "SECTION_RESPONSE_KEYS",
    "VIZ_BUILDERS",
    "build_data_governance_section",
    "build_data_quality_section",
    "build_dataset_overview_section",
    "build_fairness_bias_section",
    "build_impact_on_ai_section",
    "cap_detail_list",
    "classify_feature_type",
    "finite_kpi_values",
    "grade_label",
    "make_viz_builders",
]
