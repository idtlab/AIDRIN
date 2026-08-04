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
def kurtosis(self: Task, file_info):
    """Per-feature excess kurtosis (tail heaviness) for numeric columns.

    Uses Fisher's definition (normal distribution = 0). Positive = heavier
    tails / more outliers than normal, negative = lighter tails. Constant
    columns (undefined kurtosis) are excluded.

    Parameters
    ----------
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.

    Returns
    -------
    dict
        Per-column excess kurtosis, the most extreme feature, the max absolute
        value, the count of numeric features considered, a text description, and
        a base64 bar chart; or ``{"Error": str}``.
    """
    try:
        logger.info("Kurtosis task started")
        df = read_file(file_info)
        if len(df) == 0 or len(df.columns) == 0:
            return {"Error": "Dataset is empty"}

        numeric = df.select_dtypes(include=[np.number])
        numeric = numeric.loc[:, numeric.nunique(dropna=True) > 1]
        if numeric.shape[1] == 0:
            return {"Error": "No non-constant numeric features to score."}

        values = numeric.kurtosis(numeric_only=True).dropna()
        if values.empty:
            return {"Error": "No non-constant numeric features to score."}

        kurt_dict = {str(k): float(v) for k, v in values.items()}
        most_extreme = str(values.abs().idxmax())
        max_abs = float(values.abs().max())

        ordered = values.reindex(values.abs().sort_values(ascending=True).index)
        fig, ax = plt.subplots(figsize=(7, max(3, 0.35 * len(ordered))))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")
        ax.barh([str(c) for c in ordered.index], ordered.values,
                color=PRIMARY, edgecolor="white")
        ax.axvline(0, color=TEXT, linewidth=1)
        ax.set_xlabel("Excess kurtosis", fontsize=10, color=TEXT)
        ax.set_title("Per-feature excess kurtosis", fontsize=11, color=TEXT)
        ax.tick_params(colors=TEXT, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(TEXT)
        fig.tight_layout(pad=0.5)

        img_buf = io.BytesIO()
        fig.savefig(img_buf, format="png", dpi=150, transparent=True)
        img_buf.seek(0)
        img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")
        plt.close(fig)

        logger.info("Kurtosis task completed: max abs=%.4f", max_abs)
        return {
            "Kurtosis": kurt_dict,
            "Most Extreme Kurtosis Feature": most_extreme,
            "Max Absolute Excess Kurtosis": max_abs,
            "Numeric Features Considered": int(numeric.shape[1]),
            "Kurtosis Visualization": img_base64,
            "Description": (
                f"Most extreme feature is '{most_extreme}' (excess kurtosis "
                f"{values[most_extreme]:.2f}); positive values mean heavier tails than normal."
            ),
        }

    except SoftTimeLimitExceeded:
        logger.error("Kurtosis task timed out")
        raise Exception("Kurtosis task timed out.")
