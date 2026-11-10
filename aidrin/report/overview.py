"""Dataset-overview section of the readiness report."""

from __future__ import annotations

import os

import pandas as pd

from aidrin.file_handling.file_parser import read_file
from aidrin.report.common import classify_feature_type

# Dataset-overview readiness thresholds (per-feature profile)
OVERVIEW_MISSING_WARNING = 0.05
OVERVIEW_MISSING_POOR = 0.20
OVERVIEW_DOMINANT_WARNING = 0.95
OVERVIEW_HIGH_CARDINALITY = 50
OVERVIEW_ID_UNIQUE_RATIO = 0.9
OVERVIEW_CAT_TOP_N = 5
OVERVIEW_MAX_FEATURE_PROFILES = 500
OVERVIEW_MAX_NUMERICAL_SUMMARY_COLS = 500
OVERVIEW_MAX_CATEGORICAL_DIST_COLS = 50
PROFILE_STATUS_RANK = {"poor": 0, "warning": 1, "good": 2}


def build_numerical_summary_for_overview(num_df):
    """Build describe() summary for overview details, capped on wide datasets."""
    if num_df.empty:
        return {}, {"total": 0, "shown": 0, "truncated": False}

    total = len(num_df.columns)
    cols = num_df.columns
    truncated = total > OVERVIEW_MAX_NUMERICAL_SUMMARY_COLS
    if truncated:
        cols = cols[:OVERVIEW_MAX_NUMERICAL_SUMMARY_COLS]

    numerical_summary = num_df[cols].describe().to_dict()
    for v in numerical_summary.values():
        for old_key in list(v.keys()):
            if old_key in ["25%", "50%", "75%"]:
                new_key = old_key.replace("%", "th percentile")
                v[new_key] = float(v.pop(old_key))
        for stat_key, stat_val in list(v.items()):
            if stat_val is not None and not isinstance(stat_val, str):
                v[stat_key] = float(stat_val)

    return numerical_summary, {
        "total": total,
        "shown": len(cols),
        "truncated": truncated,
    }


def feature_readiness_status(pct_missing, n_unique, n_rows, feat_type, pct_dominant):
    """Derive a per-feature readiness status from profile statistics."""
    if n_unique <= 1:
        return "poor"
    if pct_missing is not None and pct_missing > OVERVIEW_MISSING_POOR:
        return "poor"
    if n_rows > 0 and n_unique / n_rows >= OVERVIEW_ID_UNIQUE_RATIO:
        return "poor"
    if pct_missing is not None and pct_missing > OVERVIEW_MISSING_WARNING:
        return "warning"
    if feat_type == "categorical" and n_unique > OVERVIEW_HIGH_CARDINALITY:
        return "warning"
    if pct_dominant is not None and pct_dominant > OVERVIEW_DOMINANT_WARNING:
        return "warning"
    return "good"


def feature_summary(series, feat_type, n_unique):
    """Build a compact, type-specific summary string for one feature."""
    non_null = series.dropna()
    if len(non_null) == 0:
        return "all missing"

    if feat_type == "numerical":
        mean = non_null.mean()
        std = non_null.std()
        if pd.notna(std) and std > 0:
            return f"mean {mean:.2g}, std {std:.2g}"
        return f"min {non_null.min():.2g} – max {non_null.max():.2g}"

    if feat_type == "categorical":
        vc = non_null.value_counts(normalize=True)
        top_val = vc.index[0]
        top_pct = vc.iloc[0] * 100
        return f"{top_val} ({top_pct:.0f}%), {n_unique} categories"

    if feat_type == "datetime":
        return f"{non_null.min()} – {non_null.max()}"

    if feat_type == "boolean":
        true_pct = (non_null.astype(bool)).mean() * 100
        return f"True {true_pct:.0f}%, False {100 - true_pct:.0f}%"

    return f"{n_unique} unique values"


def build_feature_profiles(df):
    """Compute a per-column readiness profile for every feature in *df*."""
    n_rows = len(df)
    profiles = []
    type_counts = {"numerical": 0, "categorical": 0, "datetime": 0, "boolean": 0}

    for col in df.columns:
        series = df[col]
        feat_type = classify_feature_type(series)
        type_counts[feat_type] = type_counts.get(feat_type, 0) + 1

        n_missing = int(series.isnull().sum())
        pct_missing = round(n_missing / n_rows, 4) if n_rows else 0.0
        n_unique = int(series.nunique(dropna=True))

        pct_dominant = None
        non_null = series.dropna()
        if len(non_null) > 0:
            pct_dominant = round(
                float(non_null.value_counts(normalize=True).iloc[0]), 4
            )

        profiles.append({
            "feature": str(col),
            "type": feat_type,
            "dtype": str(series.dtype),
            "pct_missing": pct_missing,
            "n_unique": n_unique,
            "pct_dominant": pct_dominant,
            "status": feature_readiness_status(
                pct_missing, n_unique, n_rows, feat_type, pct_dominant
            ),
            "summary": feature_summary(series, feat_type, n_unique),
        })

    return profiles, type_counts


def prepare_feature_profiles_for_display(
    profiles, max_profiles=OVERVIEW_MAX_FEATURE_PROFILES
):
    """Cap profile rows for the report table, prioritizing poor then warning then good."""
    status_counts = {"poor": 0, "warning": 0, "good": 0}
    for profile in profiles:
        status = profile.get("status", "good")
        if status in status_counts:
            status_counts[status] += 1

    total = len(profiles)
    meta = {
        "total": total,
        "shown": total,
        "max": max_profiles,
        "truncated": False,
        "status_counts": status_counts,
    }
    if total <= max_profiles:
        return profiles, meta

    ranked = sorted(
        enumerate(profiles),
        key=lambda item: (
            PROFILE_STATUS_RANK.get(item[1].get("status"), 99),
            item[0],
        ),
    )
    meta["shown"] = max_profiles
    meta["truncated"] = True
    return [profile for _, profile in ranked[:max_profiles]], meta


def dataframe_for_overview_detail_charts(df, display_profiles):
    """Subset *df* to capped profile-table features for overview detail charts."""
    cols = [p["feature"] for p in display_profiles if p["feature"] in df.columns]
    if not cols:
        return df.iloc[:, :0]
    return df[cols]


def build_categorical_distributions(df, top_n=OVERVIEW_CAT_TOP_N, max_columns=None):
    """Top-*n* value counts (with percentages) for each categorical column."""
    distributions = {}
    cat_cols = [
        col for col in df.columns if classify_feature_type(df[col]) == "categorical"
    ]
    total_cat = len(cat_cols)
    truncated = False
    if max_columns is not None and total_cat > max_columns:
        cat_cols = cat_cols[:max_columns]
        truncated = True
    for col in cat_cols:
        vc = df[col].value_counts(dropna=True)
        total = len(df[col].dropna())
        if total == 0:
            distributions[str(col)] = []
            continue
        entries = []
        for val, count in vc.head(top_n).items():
            entries.append({
                "value": str(val),
                "count": int(count),
                "pct": round(float(count) / total, 4),
            })
        distributions[str(col)] = entries
    meta = {
        "total": total_cat,
        "shown": len(cat_cols),
        "truncated": truncated,
    }
    return distributions, meta


def build_dataset_overview_section(
    file_info,
    include_visualizations=False,
    *,
    render_overview_charts=None,
):
    """Build the dataset-overview portion of the readiness report.

    Returns file metadata, per-feature readiness profiles, numerical describe()
    summary, categorical top-value distributions, and optional chart images.

    Chart rendering stays outside this package (Flask ``web.routes.utils`` today)
    so ``aidrin`` does not depend on ``web``. Pass ``render_overview_charts`` as a
    callable ``(chart_df) -> dict`` when ``include_visualizations`` is true.
    """
    file_path, file_name, file_type = file_info
    df = read_file(file_info)
    if hasattr(df, "columns"):
        df.columns = [str(c) for c in df.columns]

    n_rows = len(df)
    profiles, type_counts = build_feature_profiles(df)
    display_profiles, profile_meta = prepare_feature_profiles_for_display(profiles)

    file_size_bytes = None
    if file_path and os.path.exists(file_path):
        try:
            file_size_bytes = os.path.getsize(file_path)
        except OSError:
            pass

    memory_bytes = int(df.memory_usage(deep=True).sum())

    numerical_summary, numerical_summary_meta = build_numerical_summary_for_overview(
        df.select_dtypes(include="number")
    )
    categorical_distributions, categorical_distributions_meta = (
        build_categorical_distributions(
            df, max_columns=OVERVIEW_MAX_CATEGORICAL_DIST_COLS
        )
    )

    overview = {
        "file_metadata": {
            "file_name": file_name,
            "file_type": file_type,
            "file_size_bytes": file_size_bytes,
            "memory_bytes": memory_bytes,
            "rows": n_rows,
            "columns": len(df.columns),
            "numerical_count": type_counts.get("numerical", 0),
            "categorical_count": type_counts.get("categorical", 0),
            "datetime_count": type_counts.get("datetime", 0),
            "boolean_count": type_counts.get("boolean", 0),
        },
        "feature_profiles": display_profiles,
        "feature_profiles_meta": profile_meta,
        "numerical_summary": numerical_summary,
        "numerical_summary_meta": numerical_summary_meta,
        "categorical_distributions": categorical_distributions,
        "categorical_distributions_meta": categorical_distributions_meta,
        "profile_thresholds": {
            "missing_warning": OVERVIEW_MISSING_WARNING,
            "missing_poor": OVERVIEW_MISSING_POOR,
            "dominant_warning": OVERVIEW_DOMINANT_WARNING,
            "high_cardinality": OVERVIEW_HIGH_CARDINALITY,
            "id_unique_ratio": OVERVIEW_ID_UNIQUE_RATIO,
        },
        "visualizations_deferred": not include_visualizations,
    }
    if include_visualizations and render_overview_charts is not None:
        chart_df = dataframe_for_overview_detail_charts(df, display_profiles)
        overview.update(render_overview_charts(chart_df))
    return overview
