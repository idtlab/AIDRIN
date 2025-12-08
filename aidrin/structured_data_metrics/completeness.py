import base64
import io
from typing import Optional

import matplotlib

matplotlib.use("Agg")  
import matplotlib.pyplot as plt
import numpy as np
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded

from aidrin.file_handling.file_parser import read_file


def iterate_chunks(df, chunksize: int = 50_000):
    for start in range(0, len(df), chunksize):
        yield df.iloc[start : start + chunksize]


MAX_B64_LEN = 250_000
MAX_BARS = 40
CHUNK_SIZE = 50_000
MAX_CHUNK_STATS = 200  # cap response size


def _fig_to_b64(dpi: int = 85) -> str:
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    buf.seek(0)
    s = base64.b64encode(buf.read()).decode("utf-8")
    plt.close()
    return s


def _info_image(message: str) -> str:
    plt.figure(figsize=(7.5, 2.3))
    plt.axis("off")
    plt.text(0.01, 0.5, message, fontsize=11, va="center")
    plt.tight_layout()
    return _fig_to_b64(dpi=95)


def _barplot_small(
    keys,
    vals,
    title: str,
    max_bars: int = MAX_BARS,
    worst: bool = True,
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
        order = order[:max_bars] if worst else order[-max_bars:]
        keys = [keys[i] for i in order]
        vals = vals[order]

    x = np.arange(len(keys))
    plt.figure(figsize=(7.5, 3.2))
    plt.bar(x, vals)
    plt.title(title, fontsize=12)
    plt.ylim(0, 1)

    step = max(1, len(keys) // 10)
    tick_idx = np.arange(0, len(keys), step)
    plt.xticks(
        tick_idx,
        [str(keys[i]) for i in tick_idx],
        rotation=45,
        ha="right",
        fontsize=8,
    )

    plt.tight_layout()
    return _fig_to_b64(dpi=85)


@shared_task(bind=True, ignore_result=False)
def completeness(self: Task, file_info):
    try:
        df = read_file(file_info)

        if df is None:
            return {
                "Error": "File could not be read.",
                "Completeness Visualization": _info_image(
                    "Completeness unavailable: file could not be read."
                ),
            }

        if not hasattr(df, "columns") or df.empty:
            return {
                "Error": "Dataset is empty.",
                "Completeness Visualization": _info_image(
                    "Completeness unavailable: dataset is empty."
                ),
            }

        # Ensure column names are plain strings
        df.columns = [str(c) for c in df.columns]
        cols = list(df.columns)

        total_rows = 0
        total_missing_per_col = {col: 0 for col in cols}
        total_rows_with_any_missing = 0

        chunk_stats = []

        for idx, chunk in enumerate(iterate_chunks(df, chunksize=CHUNK_SIZE)):
            chunk_size = int(len(chunk))
            if chunk_size == 0:
                continue

            total_rows += chunk_size

            miss = chunk.isna().sum().to_dict()
            for col in cols:
                total_missing_per_col[col] += int(miss.get(col, 0))

            rows_any_missing = int(chunk.isna().any(axis=1).sum())
            total_rows_with_any_missing += rows_any_missing

            
            if idx < MAX_CHUNK_STATS:
                chunk_overall = float(1.0 - (rows_any_missing / chunk_size))
                chunk_stats.append(
                    {
                        "chunk": idx,
                        "size": chunk_size,
                        "overall": chunk_overall,
                    }
                )

        if total_rows == 0:
            return {
                "Error": "No rows found in dataset.",
                "Completeness Visualization": _info_image(
                    "Completeness unavailable: no rows found."
                ),
            }

        # Final feature-wise completeness
        final_feature_scores = {
            col: float(1.0 - (total_missing_per_col[col] / total_rows)) for col in cols
        }
        # Final overall completeness (row has no missing values)
        final_overall = float(1.0 - (total_rows_with_any_missing / total_rows))

        out = {
            
            "Completeness scores": final_feature_scores,
            "Overall Completeness": final_overall,
            
            "Chunk Completeness": chunk_stats,
            "Final Completeness": {
                "feature_wise": final_feature_scores,
                "overall": final_overall,
            },
        }

        vals = np.asarray(list(final_feature_scores.values()), dtype=float)
        finite_vals = vals[np.isfinite(vals)]

        if finite_vals.size == 0:
            out["Completeness Visualization"] = _info_image(
                "Completeness computed, but no finite scores to plot."
            )
            return out

        if float(np.nanmin(finite_vals)) == 1.0 and float(np.nanmax(finite_vals)) == 1.0:
            out["Completeness Visualization"] = _info_image(
                "All features are 100% complete.\nNo missing values detected."
            )
            return out

        img = _barplot_small(
            keys=list(final_feature_scores.keys()),
            vals=list(final_feature_scores.values()),
            title="Feature-wise Completeness (worst features)",
            max_bars=MAX_BARS,
            worst=True,
        )

        if (not img) or (len(img) > MAX_B64_LEN):
            out["Completeness Visualization"] = _info_image(
                "Completeness chart omitted to prevent oversized payload.\n"
                "Scores are computed successfully."
            )
        else:
            out["Completeness Visualization"] = img

        return out

    except SoftTimeLimitExceeded:
        raise Exception("Completeness task timed out.")
    except Exception as e:
        msg = f"Completeness calculation failed: {str(e)}"
        return {
            "Error": msg,
            "Completeness Visualization": _info_image(f"{msg}"),
        }

