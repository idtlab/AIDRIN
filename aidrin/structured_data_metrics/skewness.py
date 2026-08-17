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


@shared_task(bind=True, ignore_result=False)
def skewness(self: Task, file_info):
    """Per-feature skewness (distribution asymmetry) for numeric columns.

    Positive skew = long right tail, negative = long left tail, ~0 = symmetric.
    Constant columns (undefined skew) are excluded.

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.

    Returns
    -------
    dict
        Per-column skewness, the most-skewed feature, the max absolute
        skewness, the count of numeric features considered, a text description,
        and a base64 bar chart; or ``{"Error": str}``.
    """
    try:
        logger.info("Skewness task started")
        df = read_file(file_info)
        if len(df) == 0 or len(df.columns) == 0:
            return {"Error": "Dataset is empty"}

        numeric = df.select_dtypes(include=[np.number])
        numeric = numeric.loc[:, numeric.nunique(dropna=True) > 1]
        if numeric.shape[1] == 0:
            return {"Error": "No non-constant numeric features to score."}

        values = numeric.skew(numeric_only=True).dropna()
        if values.empty:
            return {"Error": "No non-constant numeric features to score."}

        skew_dict = {str(k): float(v) for k, v in values.items()}
        most_skewed = str(values.abs().idxmax())
        max_abs = float(values.abs().max())

        ordered = values.reindex(values.abs().sort_values(ascending=True).index)
        fig, ax = plt.subplots(figsize=(7, max(3, 0.35 * len(ordered))))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")
        ax.barh([str(c) for c in ordered.index], ordered.values,
                color=PRIMARY, edgecolor="white")
        ax.axvline(0, color=TEXT, linewidth=1)
        ax.set_xlabel("Skewness", fontsize=10, color=TEXT)
        ax.set_title("Per-feature skewness", fontsize=11, color=TEXT)
        ax.tick_params(colors=TEXT, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(TEXT)
        fig.tight_layout(pad=0.5)

        img_buf = io.BytesIO()
        fig.savefig(img_buf, format="png", dpi=150, transparent=True)
        img_buf.seek(0)
        img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")
        plt.close(fig)

        logger.info("Skewness task completed: max abs=%.4f", max_abs)
        return {
            "Skewness": skew_dict,
            "Most Skewed Feature": most_skewed,
            "Max Absolute Skewness": max_abs,
            "Numeric Features Considered": int(numeric.shape[1]),
            "Skewness Visualization": img_base64,
            "Description": (
                f"Most skewed feature is '{most_skewed}' (skewness {values[most_skewed]:.2f}); "
                "values far from 0 indicate asymmetric distributions."
            ),
        }

    except SoftTimeLimitExceeded:
        logger.error("Skewness task timed out")
        raise Exception("Skewness task timed out.")
