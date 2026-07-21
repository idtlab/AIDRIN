import base64
import io
import logging

import matplotlib.pyplot as plt
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file

logger = logging.getLogger(__name__)

PRIMARY = "#4485F4"
NEGATIVE = "#D86470"
TEXT = "#6b7280"


@shared_task(bind=True, ignore_result=False)
def feature_coverage_ratio(self: Task, threshold, file_info):
    """% of features whose non-null rate is at least *threshold* (in [0, 1]).

    Parameters
    ----------
    threshold : float
        Value in [0, 1]. A feature is 'covered' if its non-null rate >= threshold.
    file_info : tuple
        ``(file_path, file_name, file_type)`` describing the dataset to read.
    """
    try:
        logger.info("Feature Coverage Ratio task started")
        df = read_file(file_info)
        if len(df) == 0 or len(df.columns) == 0:
            return {"Error": "Dataset is empty"}
        if not (0.0 <= threshold <= 1.0):
            return {"Error": f"threshold must be in [0, 1], got {threshold}"}
        non_null_rates = df.notnull().mean()
        # Inclusive >=: threshold=1.0 correctly counts fully-complete features
        # (the strict > previously made threshold=1.0 unreachable).
        covered = int((non_null_rates >= threshold).sum())
        pct = (covered / len(df.columns)) * 100

        fig, ax = plt.subplots(figsize=(8, 4))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")
        ax.hist(non_null_rates.values, bins=20, range=(0, 1),
                color=PRIMARY, edgecolor="white")
        ax.axvline(threshold, color=NEGATIVE, linestyle="--", linewidth=2,
                   label=f"threshold = {threshold:.2f}")
        ax.set_xlabel("Non-null rate per feature", fontsize=10, color=TEXT)
        ax.set_ylabel("Number of features", fontsize=10, color=TEXT)
        ax.set_xlim(0, 1.02)
        ax.tick_params(colors=TEXT, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(TEXT)
        ax.legend(facecolor="none", edgecolor=TEXT, labelcolor=TEXT, fontsize=8)
        fig.tight_layout(pad=0.5)

        img_buf = io.BytesIO()
        fig.savefig(img_buf, format="png", dpi=150, transparent=True)
        img_buf.seek(0)
        img_base64 = base64.b64encode(img_buf.read()).decode("utf-8")
        plt.close(fig)

        logger.info("Feature Coverage Ratio task completed: %.4f%%", pct)
        return {
            "Feature Coverage Ratio (%)": float(pct),
            "Threshold": float(threshold),
            "Covered features": covered,
            "Total features": int(len(df.columns)),
            "Feature Coverage Ratio Visualization": img_base64,
            "Description": (
                f"Percentage of features whose non-null rate exceeds {threshold:.0%}."
            ),
        }

    except SoftTimeLimitExceeded:
        logger.error("Feature Coverage Ratio task timed out")
        raise Exception("Feature Coverage Ratio task timed out.")
