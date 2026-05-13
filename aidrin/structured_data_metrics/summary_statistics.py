import base64
import io

import matplotlib.pyplot as plt
import seaborn as sns
from celery import Task, shared_task

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def summary_histograms(self: Task, file_info):
    df = read_file(file_info)

    # Ensure DataFrame columns are strings to avoid numpy array issues
    if hasattr(df, 'columns'):
        df.columns = [str(col) for col in df.columns]

    text_color = "#6b7280"
    curve_color = "#4485F4"

    line_graphs = {}
    for column in df.select_dtypes(include="number").columns:
        column_str = str(column)

        fig, ax = plt.subplots(figsize=(4, 3))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")

        sns.kdeplot(df[column], bw_adjust=0.5, ax=ax, color=curve_color)

        ax.set_xlabel("Values", fontsize=10, color=text_color)
        ax.set_ylabel("Density", fontsize=10, color=text_color)
        ax.tick_params(colors=text_color, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(text_color)
        fig.tight_layout(pad=0.5)

        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format="png", dpi=150, transparent=True)
        img_buffer.seek(0)
        encoded_img = base64.b64encode(img_buffer.read()).decode("utf-8")

        line_graphs[f"{column_str}_light"] = encoded_img
        plt.close(fig)
        img_buffer.close()

    return line_graphs
