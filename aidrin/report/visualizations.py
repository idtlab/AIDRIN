"""Deferred chart builders for readiness-report sections."""

from __future__ import annotations

from aidrin.file_handling.file_parser import read_file
from aidrin.report.fairness import (
    auto_select_fairness_columns,
    compute_class_imbalance,
)
from aidrin.report.governance import (
    GOV_DP_EPSILON,
    SYNTHETIC_ID_COL,
    auto_select_governance_columns,
)
from aidrin.report.impact import prune_columns_for_corr
from aidrin.report.overview import (
    build_feature_profiles,
    dataframe_for_overview_detail_charts,
    prepare_feature_profiles_for_display,
)
from aidrin.structured_data_metrics.add_noise import return_noisy_stats
from aidrin.structured_data_metrics.completeness import completeness
from aidrin.structured_data_metrics.correlation_score import calc_correlations
from aidrin.structured_data_metrics.outliers import outliers
from aidrin.structured_data_metrics.privacy_measure import (
    compute_entropy_risk,
    compute_k_anonymity,
    compute_l_diversity,
    compute_t_closeness,
    generate_multiple_attribute_MM_risk_scores_groupby,
)
from aidrin.structured_data_metrics.representation_rate import (
    create_representation_rate_vis,
)
from aidrin.structured_data_metrics.statistical_rate import calculate_statistical_rates


def build_dataset_overview_visualizations(file_info, *, render_overview_charts):
    """Build overview chart payloads using an injected chart renderer.

    ``render_overview_charts`` is ``(chart_df) -> dict`` so this package does
    not depend on Flask-side matplotlib helpers in ``web.routes.utils``.
    """
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]
    profiles, _ = build_feature_profiles(df)
    display_profiles, _ = prepare_feature_profiles_for_display(profiles)
    chart_df = dataframe_for_overview_detail_charts(df, display_profiles)
    return render_overview_charts(chart_df)


def build_data_quality_visualizations(file_info):
    compl = completeness(file_info, include_visualization=True)
    out = outliers(file_info, include_visualization=True)
    viz = {}
    if compl.get("Completeness Visualization"):
        viz["completeness"] = compl["Completeness Visualization"]
    if isinstance(out, dict) and out.get("Outliers Visualization"):
        viz["outliers"] = out["Outliers Visualization"]
    return viz


def build_impact_on_ai_visualizations(file_info):
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]
    kept, _ = prune_columns_for_corr(df)
    if len(kept) < 2:
        return {}
    corr = calc_correlations(kept, file_info, include_visualization=True)
    if isinstance(corr, dict) and "Message" in corr:
        return {}
    cat = corr.get("Correlations Analysis Categorical", {}) or {}
    num = corr.get("Correlations Analysis Numerical", {}) or {}
    viz = {}
    cat_img = cat.get("Correlations Analysis Categorical Visualization")
    num_img = num.get("Correlations Analysis Numerical Visualization")
    if cat_img:
        viz["categorical_correlation"] = cat_img
    if num_img:
        viz["numerical_correlation"] = num_img
    return viz


def build_fairness_bias_visualizations(file_info):
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]
    selection = auto_select_fairness_columns(df)
    sensitive_cols = selection["sensitive_columns"]
    target_col = selection["target_column"]
    primary_sensitive = selection["primary_sensitive"]
    viz = {}
    for col in sensitive_cols:
        try:
            vis = create_representation_rate_vis([col], file_info)
            if isinstance(vis, str):
                viz[f"representation_rate.{col}"] = vis
        except Exception:
            pass
    if target_col:
        ci_dict = compute_class_imbalance(df, target_col, "EU", include_visualization=True)
        img = ci_dict.get("Class Imbalance Visualization")
        if img:
            viz["class_imbalance"] = img
    if primary_sensitive and target_col:
        sr = calculate_statistical_rates(
            target_col, primary_sensitive, file_info, include_visualization=True,
        )
        if isinstance(sr, dict) and sr.get("Statistical Rate Visualization"):
            viz["statistical_rate"] = sr["Statistical Rate Visualization"]
    return viz


def build_data_governance_visualizations(file_info):
    """Build only chart payloads for governance (metrics already computed on initial load)."""
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]

    fairness_sel = auto_select_fairness_columns(df)
    selection = auto_select_governance_columns(
        df, fairness_target=fairness_sel.get("target_column")
    )
    qi = selection["quasi_identifiers"]
    mm_qis = selection["mm_quasi_identifiers"]
    sensitive = selection["sensitive_attribute"]
    id_col = selection["id_column"]
    id_synthetic = selection["id_synthetic"]
    dp_features = selection["dp_features"]

    work_df = df.copy()
    if id_synthetic:
        work_df[SYNTHETIC_ID_COL] = range(len(work_df))
        id_col = SYNTHETIC_ID_COL

    viz = {}
    if qi:
        k_res = compute_k_anonymity(qi, work_df, include_visualization=True)
        img = k_res.get("k-Anonymity Visualization")
        if img:
            viz["k_anonymity"] = img
        e_res = compute_entropy_risk(qi, work_df, include_visualization=True)
        img = e_res.get("Entropy Risk Visualization")
        if img:
            viz["entropy_risk"] = img
    if qi and sensitive:
        l_res = compute_l_diversity(qi, sensitive, work_df, include_visualization=True)
        img = l_res.get("l-Diversity Visualization")
        if img:
            viz["l_diversity"] = img
        t_res = compute_t_closeness(qi, sensitive, work_df, include_visualization=True)
        img = t_res.get("t-Closeness Visualization")
        if img:
            viz["t_closeness"] = img
    if mm_qis:
        m_res = generate_multiple_attribute_MM_risk_scores_groupby(
            work_df, id_col, mm_qis, include_visualization=True
        )
        img = m_res.get("Multiple attribute risk scoring Visualization")
        if img:
            viz["multiple_attribute_risk"] = img
    if dp_features:
        try:
            dp_res = return_noisy_stats(
                dp_features, GOV_DP_EPSILON, work_df,
                save_output=False, include_visualization=True,
            )
            img = dp_res.get("DP Statistics Visualization")
            if img:
                viz["differential_privacy"] = img
        except Exception:
            pass
    return viz
