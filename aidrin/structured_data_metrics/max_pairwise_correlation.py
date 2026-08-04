import base64
import io
import logging

import matplotlib.pyplot as plt
import numpy as np
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)

PRIMARY = "#4485F4"
TEXT = "#6b7280"

TOP_N = 5


@shared_task(bind=True, ignore_result=False)
def max_pairwise_correlation(self: Task, file_info):
    """Report the strongest absolute pairwise correlation between features.

    Considers numeric, non-constant columns and computes the absolute Pearson
    correlation matrix. Surfaces the single most-collinear pair and the top
    pairs — a compact redundancy signal distinct from the full correlation
    matrix reported by the correlation-analysis metric.

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.

    Returns
    -------
    dict
        Max absolute correlation, the most-correlated pair, the top pairs, the
        count of numeric features considered, a text description, and a base64
        heatmap; or ``{"Error": str}``.
    """
    try:
        logger.info("Max Pairwise Correlation task started")
        df = read_file(file_info)
        if len(df) == 0 or len(df.columns) == 0:
            return {"Error": "Dataset is empty"}

        numeric = df.select_dtypes(include=[np.number])
        # Drop constant columns — their correlation is undefined (NaN).
        numeric = numeric.loc[:, numeric.nunique(dropna=True) > 1]
        if numeric.shape[1] < 2:
            return {"Error": "Need at least two non-constant numeric features."}

        corr = numeric.corr(numeric_only=True).abs()
        matrix = corr.to_numpy(copy=True)
        np.fill_diagonal(matrix, np.nan)

        # Every off-diagonal correlation is NaN when no feature pair shares
        # overlapping non-null rows (disjoint sparse columns). nanargmax would
        # raise on an all-NaN slice, so return the {"Error": ...} contract.
        if np.all(np.isnan(matrix)):
            return {
                "Error": "No overlapping non-null rows between numeric features "
                "to compute a correlation."
            }

        flat_idx = np.nanargmax(matrix)
        i, j = np.unravel_index(flat_idx, matrix.shape)
        cols = list(corr.columns)
        max_corr = float(matrix[i, j])
        most_pair = f"{cols[i]} ~ {cols[j]}"

        # Rank unique pairs (upper triangle) by absolute correlation.
        pairs = []
        for a in range(len(cols)):
            for b in range(a + 1, len(cols)):
                val = matrix[a, b]
                if not np.isnan(val):
                    pairs.append((f"{cols[a]} ~ {cols[b]}", float(val)))
        pairs.sort(key=lambda p: p[1], reverse=True)
        top_pairs = [{"pair": p, "correlation": round(c, 4)} for p, c in pairs[:TOP_N]]

        fig, ax = plt.subplots(figsize=(6, 5))
        fig.patch.set_alpha(0)
        im = ax.imshow(corr.to_numpy(), vmin=0, vmax=1, cmap="Blues")
        ax.set_xticks(range(len(cols)))
        ax.set_yticks(range(len(cols)))
        ax.set_xticklabels(cols, rotation=90, fontsize=7, color=TEXT)
        ax.set_yticklabels(cols, fontsize=7, color=TEXT)
        ax.set_title("Absolute pairwise correlation", fontsize=11, color=TEXT)
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.ax.tick_params(colors=TEXT, labelsize=7)
        fig.tight_layout(pad=0.5)

        img_buf = io.BytesIO()
        fig.savefig(img_buf, format="png", dpi=150, transparent=True)
        img_buf.seek(0)
        img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")
        plt.close(fig)

        logger.info("Max Pairwise Correlation task completed: %.4f", max_corr)
        return {
            "Max Pairwise Correlation": max_corr,
            "Most Correlated Pair": most_pair,
            "Top Correlated Pairs": top_pairs,
            "Numeric Features Considered": int(numeric.shape[1]),
            "Max Pairwise Correlation Visualization": img_base64,
            "Description": (
                f"Strongest absolute correlation is {max_corr:.4f} between "
                f"{most_pair}; values near 1.0 indicate redundant features."
            ),
        }

    except SoftTimeLimitExceeded:
        logger.error("Max Pairwise Correlation task timed out")
        raise Exception("Max Pairwise Correlation task timed out.")
