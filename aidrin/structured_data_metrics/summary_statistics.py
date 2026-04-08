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

    # background colors for plots (light and dark mode)
    plot_colors = {
        "light": {"bg": "#FFFFFF", "text": "#1A1A2E", "curve": "#4485F4"},
        "dark": {"bg": "#1A1A2E", "text": "#F0EEF6", "curve": "#6EA8FE"},
    }

    line_graphs = {}
    for column in df.select_dtypes(include="number").columns:
        column_str = str(column)

        for theme, colors in plot_colors.items():
            fig, ax = plt.subplots(figsize=(4, 3), facecolor=colors["bg"])
            ax.set_facecolor(colors["bg"])

            sns.kdeplot(df[column], bw_adjust=0.5, ax=ax, color=colors["curve"])

            ax.set_xlabel("Values", fontsize=10, color=colors["text"])
            ax.set_ylabel("Density", fontsize=10, color=colors["text"])
            ax.tick_params(colors=colors["text"], labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(colors["text"])
            fig.tight_layout(pad=0.5)

            img_buffer = io.BytesIO()
            fig.savefig(img_buffer, format="png", dpi=150)
            img_buffer.seek(0)
            encoded_img = base64.b64encode(img_buffer.read()).decode("utf-8")

            line_graphs[f"{column_str}_{theme}"] = encoded_img
            plt.close(fig)
            img_buffer.close()

    return line_graphs
