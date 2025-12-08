import base64
import io
from typing import Optional

import matplotlib

matplotlib.use("Agg")  
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


MAX_B64_LEN = 250_000
MAX_BARS = 40


def _fig_to_b64(fig: plt.Figure, dpi: int = 85) -> str:
    """Convert a specific Matplotlib Figure to base64 PNG."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    buf.seek(0)
    s = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return s


def _info_image(message: str) -> str:
    fig = plt.figure(figsize=(7.5, 2.3))
    ax = fig.add_subplot(111)
    ax.axis("off")
    ax.text(0.01, 0.5, message, fontsize=11, va="center")
    fig.tight_layout()
    return _fig_to_b64(fig, dpi=95)


def _barplot_small(
    keys,
    vals,
    title: str,
    max_bars: int = MAX_BARS,
    top: bool = True,
) -> Optional[str]:
    keys = list(keys)
    vals = np.asarray(list(vals), dtype=float)

    mask = np.isfinite(vals)
    keys = [k for k, m in zip(keys, mask) if m]
    vals = vals[mask]
    if vals.size == 0:
        return None

    if len(keys) > max_bars:
        order = np.argsort(vals)
        order = order[-max_bars:] if top else order[:max_bars]
        keys = [keys[i] for i in order]
        vals = vals[order]

    x = np.arange(len(keys))
    fig = plt.figure(figsize=(7.5, 3.2))
    ax = fig.add_subplot(111)
    ax.bar(x, vals)
    ax.set_title(title, fontsize=12)
    ax.set_ylim(0, 1)

    step = max(1, len(keys) // 10)
    tick_idx = np.arange(0, len(keys), step)
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(
        [str(keys[i]) for i in tick_idx],
        rotation=45,
        ha="right",
        fontsize=8,
    )

    fig.tight_layout()
    return _fig_to_b64(fig, dpi=85)


@shared_task(bind=True, ignore_result=False)
def outliers(self: Task, file_info):

    try:
        df = read_file(file_info)

        if df is None:
            return {
                "Error": "File could not be read.",
                "Outliers Visualization": _info_image(
                    "Outliers unavailable: file could not be read."
                ),
            }

        if not hasattr(df, "columns") or df.empty:
            return {
                "Error": "Dataset is empty.",
                "Outliers Visualization": _info_image(
                    "Outliers unavailable: dataset is empty."
                ),
            }

        df.columns = [str(c) for c in df.columns]


        for c in df.columns:
            if df[c].dtype == object:
                coerced = pd.to_numeric(df[c], errors="coerce")
       
                if np.isfinite(coerced.to_numpy(dtype=float, copy=False)).sum() > 0:
                    df[c] = coerced

        numerical_df = df.select_dtypes(include=[np.number])
        if numerical_df.empty:
 
            return {
                "Error": "No numerical features found in the dataset.",
                "Outlier scores": {"Overall outlier score": 0.0},
                "Outliers Visualization": _info_image(
                    "No numerical features found in the dataset."
                ),
            }

        proportions = {}

        for col in numerical_df.columns:
            series = numerical_df[col].dropna()

            if series.empty:
                proportions[str(col)] = np.nan
                continue

            q1 = float(series.quantile(0.25))
            q3 = float(series.quantile(0.75))
            iqr = float(q3 - q1)

            if not np.isfinite(iqr) or iqr == 0.0:
                proportions[str(col)] = 0.0
                continue

            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            mask = (series < lower) | (series > upper)
            proportions[str(col)] = float(mask.mean())

        valid_values = [v for v in proportions.values() if np.isfinite(v)]
        overall_score = float(np.mean(valid_values)) if valid_values else 0.0
        proportions["Overall outlier score"] = overall_score

        out = {"Outlier scores": proportions}

        # Visualization (feature-level only)
        feature_scores = {
            k: v for k, v in proportions.items() if k != "Overall outlier score"
        }

        if not feature_scores:
            out["Outliers Visualization"] = _info_image(
                "Outliers computed, but no feature scores to plot."
            )
            return out

        vals = np.asarray(list(feature_scores.values()), dtype=float)
        finite_vals = vals[np.isfinite(vals)]

        if finite_vals.size == 0:
            out["Outliers Visualization"] = _info_image(
                "Outliers computed, but no finite scores to plot."
            )
            return out

        if float(np.nanmax(finite_vals)) == 0.0:
            out["Outliers Visualization"] = _info_image(
                "No outliers detected (all proportions are 0).\n"
                "Common causes: very few rows, constant columns (IQR=0)."
            )
            return out

        img = _barplot_small(
            keys=list(feature_scores.keys()),
            vals=list(feature_scores.values()),
            title="Proportion of Outliers (top features)",
            max_bars=MAX_BARS,
            top=True,
        )

        if (not img) or (len(img) > MAX_B64_LEN):
            out["Outliers Visualization"] = _info_image(
                "Outliers chart omitted to prevent oversized payload.\n"
                "Scores are computed successfully."
            )
        else:
            out["Outliers Visualization"] = img

        return out

    except SoftTimeLimitExceeded:
        raise Exception("Outliers task timed out.")
    except Exception as e:
        msg = f"Outlier detection failed: {str(e)}"
        return {
            "Error": msg,
            "Outliers Visualization": _info_image(msg),
        }

