"""Functions that execute on a remote Globus Compute endpoint.

These live in the ``aidrin`` package (not the ``web`` app) on purpose: when a
function is submitted to Globus Compute, the default serialiser records a
*reference* to it (its ``__module__``/``__qualname__``) rather than its source.
The remote worker then imports that module to reconstruct the function. The
endpoint has ``aidrin`` installed but **not** the ``web`` Flask app, so the
runner must live here to be importable on the worker.

Keep module-level imports minimal — everything the functions need is imported
*inside* the function bodies so that a bare ``import aidrin.compute.remote`` on
the endpoint stays cheap and side-effect free.
"""


def remote_metric_runner(metric_name, file_path, file_name, file_type, **params):
    """Execute an AIDRIN metric on the remote Globus Compute endpoint.

    This function is serialised and sent to the remote endpoint, where it
    imports ``aidrin`` locally and dispatches to the requested metric.
    The remote environment must have ``pip install aidrin`` completed.
    """
    # Ensure matplotlib uses non-interactive backend on remote endpoint
    import matplotlib
    matplotlib.use("Agg")

    import aidrin

    file_info = (file_path, file_name, file_type)

    def _data_quality():
        """Run selected data quality sub-metrics and bundle results."""
        result = {}
        selected = params.get("selected", ["completeness", "outliers", "duplicates"])
        if "completeness" in selected:
            r = aidrin.calculate_completeness(file_info)
            r["Description"] = (
                "Indicate the proportion of available data for each feature, "
                "with values closer to 1 indicating high completeness, and values near "
                "0 indicating low completeness."
            )
            result["Completeness"] = r
        if "row_level_completeness" in selected:
            result["Row-Level Completeness"] = aidrin.calculate_row_level_completeness(
                params.get("required_columns", []), file_info
            )
        if "duplicity_by_features" in selected:
            result["Duplicates by Selected Features"] = aidrin.calculate_duplicity_by_features(
                params.get("duplicate_features", []), file_info
            )
        if "feature_coverage_ratio" in selected:
            result["Feature Coverage Ratio"] = aidrin.calculate_feature_coverage_ratio(
                params.get("threshold", 0.9), file_info
            )
        if "temporal_completeness" in selected:
            result["Temporal Completeness"] = aidrin.calculate_temporal_completeness(
                params.get("timestamp_column", ""), params.get("frequency", "D"), file_info
            )
        if "null_count_trend" in selected:
            result["Null Count Trend"] = aidrin.calculate_null_count_trend(
                params.get("batch_column", ""), params.get("target_columns", []), file_info
            )
        if "outliers" in selected:
            r = aidrin.calculate_outliers(file_info)
            r["Description"] = (
                "Outlier scores are calculated for numerical columns using the IQR method, "
                "where a score of 1 indicates all data points are outliers, "
                "and 0 signifies no outliers."
            )
            result["Outliers"] = r
        if "duplicates" in selected:
            r = aidrin.calculate_duplicates(file_info)
            r["Description"] = (
                "A value of 0 indicates no duplicates, and a value closer to 1 signifies "
                "a higher proportion of duplicated data points."
            )
            result["Duplicity"] = r
        if "custom_outliers" in selected:
            rules = params.get("custom_outlier_rules", [])
            max_outliers = params.get("max_outliers", 100)
            scan_limit = params.get("scan_limit")
            stop_after_outliers = params.get("stop_after_outliers", False)
            max_export_rows = params.get("max_export_rows", 10000)
            try:
                r = aidrin.calculate_custom_outliers(
                    file_info,
                    rules,
                    max_outliers=max_outliers,
                    scan_limit=scan_limit,
                    stop_after_outliers=stop_after_outliers,
                    max_export_rows=max_export_rows,
                )
                r["Description"] = (
                    "Custom criteria outliers are values that violate user-defined range "
                    "or regex rules on selected columns or native HDF5 datasets."
                )
            except Exception as e:
                r = {
                    "Error": f"{type(e).__name__}: {e}",
                    "Description": (
                        "Custom criteria outliers are values that violate user-defined range "
                        "or regex rules on selected columns or native HDF5 datasets."
                    ),
                }
            result["Custom Criteria Outliers"] = r
        return result

    def _data_structure():
        """Run selected data-structure sub-metrics and bundle results."""
        result = {}
        selected = params.get(
            "selected",
            ["constant_feature_count", "max_pairwise_correlation", "skewness", "kurtosis"],
        )
        if "constant_feature_count" in selected:
            result["Constant Feature Count"] = (
                aidrin.calculate_constant_feature_count(file_info)
            )
        if "max_pairwise_correlation" in selected:
            result["Max Pairwise Correlation"] = (
                aidrin.calculate_max_pairwise_correlation(file_info)
            )
        if "skewness" in selected:
            result["Skewness"] = aidrin.calculate_skewness(file_info)
        if "kurtosis" in selected:
            result["Kurtosis"] = aidrin.calculate_kurtosis(file_info)
        return result

    def _custom_outlier_targets():
        """Discover selectable custom-outlier targets on the remote file."""
        from aidrin.file_handling.value_iterators import iter_targets
        return {"success": True, "targets": iter_targets(file_info)}

    def _summary_statistics():
        """Compute summary statistics + histograms on the remote file."""
        import io
        import base64
        import pandas as pd
        import matplotlib.pyplot as plt
        import seaborn as sns
        from aidrin.file_handling.file_parser import read_file as _read_file
        from aidrin.file_handling.hashable_utils import hashable_series, safe_nunique

        df = _read_file(file_info)
        if isinstance(df, str):
            return {"error": df}

        # Booleans are treated as categorical (excluded from describe() and
        # select_dtypes("number") below, so they belong with the categorical
        # summary, not the numerical one).
        numerical_columns = [
            col for col, dtype in df.dtypes.items()
            if pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype)
        ]
        categorical_columns = [
            col for col, dtype in df.dtypes.items()
            if pd.api.types.is_string_dtype(dtype) or pd.api.types.is_bool_dtype(dtype)
        ]
        all_features = numerical_columns + categorical_columns

        # Restrict to numeric columns: describe() would otherwise fall back to
        # object-column stats (top/freq are strings) and the numeric formatter
        # below would fail on them when there are no numerical features (#125).
        numeric_df = df.select_dtypes(include="number")
        if numeric_df.shape[1] == 0:
            summary = {}
        else:
            summary = numeric_df.describe().map(
                lambda x: round(x, 2) if x == 0 or abs(x) >= 0.001 else f"{x:.2e}"
            ).to_dict()

        # Rename percentile keys
        for v in summary.values():
            for old_key in list(v.keys()):
                if old_key in ["25%", "50%", "75%"]:
                    v[old_key.replace("%", "th percentile")] = v.pop(old_key)

        # Per-column summary for categorical features (parity with the local
        # /summary-statistics panel).
        categorical_summary = {}
        for col in categorical_columns:
            # value_counts() and nunique() both hash, so a column holding
            # arrays/lists/dicts (parquet/HDF5/JSON) would raise and take the
            # whole summary down. Normalize such columns first.
            series = hashable_series(df[col])
            counts = series.value_counts(dropna=True)
            count = int(series.notna().sum())
            freq = int(counts.iloc[0]) if not counts.empty else 0
            categorical_summary[str(col)] = {
                "count": count,
                "unique": safe_nunique(series, dropna=True),
                "top": str(counts.index[0]) if not counts.empty else "—",
                "freq": freq,
                "freq_pct": round(freq / count * 100, 1) if count else 0.0,
            }

        # Generate histograms (transparent, same as local)
        text_color = "#6b7280"
        curve_color = "#4485F4"
        histograms = {}
        for column in df.select_dtypes(include="number").columns:
            try:
                fig, ax = plt.subplots(figsize=(4, 3))
                fig.patch.set_alpha(0)
                ax.set_facecolor("none")
                sns.kdeplot(df[column], bw_adjust=0.5, cut=0, ax=ax, color=curve_color)
                ax.set_xlabel("Values", fontsize=10, color=text_color)
                ax.set_ylabel("Density", fontsize=10, color=text_color)
                ax.tick_params(colors=text_color, labelsize=8)
                for spine in ax.spines.values():
                    spine.set_color(text_color)
                fig.tight_layout(pad=0.5)
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=150, transparent=True)
                buf.seek(0)
                histograms[f"{column}_light"] = base64.b64encode(buf.read()).decode("utf-8")
                plt.close(fig)
                buf.close()
            except Exception:
                pass

        return {
            "success": True,
            "records_count": len(df),
            "features_count": len(df.columns),
            "categorical_features": list(categorical_columns),
            "numerical_features": list(numerical_columns),
            "all_features": all_features,
            "summary_statistics": summary,
            "categorical_summary": categorical_summary,
            "histograms": histograms,
            "class_imbalance_features": [
                col for col in all_features if safe_nunique(df[col]) <= 30
            ],
        }

    def _fairness():
        """Run selected fairness sub-metrics and bundle results (matching local route)."""
        from aidrin.structured_data_metrics.representation_rate import (
            calculate_representation_rate as _calc_rr,
            create_representation_rate_vis as _vis_rr,
        )
        aidrin._eager_celery()
        result = {}
        selected = params.get("selected", [])

        if "representation_rate" in selected:
            columns = params.get("rep_columns", [])
            rep_dict = {}
            rep_dict["Probability ratios"] = _calc_rr.apply(args=(columns, file_info)).get()
            rep_dict["Representation Rate Visualization"] = _vis_rr.apply(args=(columns, file_info)).get()
            rep_dict["Description"] = (
                "Probability ratios quantify the relative representation of different "
                "categories within the sensitive features, highlighting differences in "
                "representation rates between various groups."
            )
            result["Representation Rate"] = rep_dict

        if "statistical_rates" in selected:
            sr_dict = aidrin.calculate_statistical_rates(
                params.get("sensitive_attr", ""),
                params.get("y_true", ""),
                file_info,
            )
            sr_dict["Description"] = (
                "The graph illustrates the statistical rates of various classes across "
                "different sensitive attributes."
            )
            result["Statistical Rate"] = sr_dict

        return result

    dispatch = {
        "summary_statistics": _summary_statistics,
        "data_quality": _data_quality,
        "data_structure": _data_structure,
        "custom_outlier_targets": _custom_outlier_targets,
        "completeness": lambda: aidrin.calculate_completeness(file_info),
        "outliers": lambda: aidrin.calculate_outliers(file_info),
        "duplicates": lambda: aidrin.calculate_duplicates(file_info),
        "constant_feature_count": lambda: aidrin.calculate_constant_feature_count(file_info),
        "max_pairwise_correlation": lambda: aidrin.calculate_max_pairwise_correlation(
            file_info
        ),
        "skewness": lambda: aidrin.calculate_skewness(file_info),
        "kurtosis": lambda: aidrin.calculate_kurtosis(file_info),
        "row_level_completeness": lambda: aidrin.calculate_row_level_completeness(
            params.get("required_columns", []), file_info
        ),
        "duplicity_by_features": lambda: aidrin.calculate_duplicity_by_features(
            params.get("duplicate_features", []), file_info
        ),
        "feature_coverage_ratio": lambda: aidrin.calculate_feature_coverage_ratio(
            params.get("threshold", 0.9), file_info
        ),
        "temporal_completeness": lambda: aidrin.calculate_temporal_completeness(
            params.get("timestamp_column", ""), params.get("frequency", "D"), file_info
        ),
        "null_count_trend": lambda: aidrin.calculate_null_count_trend(
            params.get("batch_column", ""), params.get("target_columns", []), file_info
        ),
        "correlations": lambda: aidrin.calculate_correlations(
            params.get("columns", []), file_info
        ),
        "feature_relevance": lambda: aidrin.calculate_feature_relevance(
            file_info,
            params["target_col"],
            params.get("cat_cols"),
            params.get("num_cols"),
        ),
        "fairness": _fairness,
        "representation_rate": _fairness,  # alias — routes through _fairness
        "statistical_rates": _fairness,    # alias
        "k_anonymity": lambda: aidrin.compute_k_anonymity(
            params.get("quasi_ids", []), file_info
        ),
        "l_diversity": lambda: aidrin.compute_l_diversity(
            params.get("quasi_ids", []),
            params["sensitive_col"],
            file_info,
        ),
        "t_closeness": lambda: aidrin.compute_t_closeness(
            params.get("quasi_ids", []),
            params["sensitive_col"],
            file_info,
        ),
        "entropy_risk": lambda: aidrin.compute_entropy_risk(
            params.get("quasi_ids", []), file_info
        ),
        "class_distribution": lambda: aidrin.calculate_class_distribution(
            params["column"], file_info
        ),
    }

    fn = dispatch.get(metric_name)
    if fn is None:
        return {"error": f"Unknown metric: {metric_name}"}

    try:
        result = fn()
        # Ensure all values are JSON-serializable (convert numpy types, etc.)
        import json
        try:
            json.dumps(result)
        except (TypeError, ValueError):
            # Fall back to recursive conversion
            def _make_serializable(obj):
                import numpy as np
                import pandas as pd
                if isinstance(obj, dict):
                    return {str(k): _make_serializable(v) for k, v in obj.items()}
                elif isinstance(obj, (list, tuple)):
                    return [_make_serializable(i) for i in obj]
                elif isinstance(obj, (np.integer,)):
                    return int(obj)
                elif isinstance(obj, (np.floating,)):
                    return float(obj)
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
                elif isinstance(obj, (np.bool_,)):
                    return bool(obj)
                elif isinstance(obj, pd.Timestamp):
                    return obj.isoformat()
                elif isinstance(obj, set):
                    return list(obj)
                return obj
            result = _make_serializable(result)
        return result
    except Exception as e:
        return {"error": f"Remote execution failed: {str(e)}"}


def remote_env_probe():
    """Report the remote endpoint's environment for compatibility checks.

    Runs ON the Globus Compute endpoint. Because it imports ``aidrin`` the same
    way ``remote_metric_runner`` does, a successful probe also proves the worker
    can import ``aidrin`` at all — turning "wrong env / import error / version
    drift" into a clear message at connect time instead of a dill traceback
    after a real job runs.
    """
    import sys
    import aidrin

    return {
        "aidrin_version": aidrin.__version__,
        "python_version": ".".join(map(str, sys.version_info[:3])),
    }
