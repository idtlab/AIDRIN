import base64
import io

import matplotlib.pyplot as plt
import seaborn as sns
from celery import Task, shared_task

from aidrin.file_handling.file_parser import read_file


@shared_task(bind=True, ignore_result=False)
def summary_histograms(self: Task, file_info):
    df = read_file(file_info)
    # background colors for plots (light and dark mode)
    plot_colors = {
        "light": {"bg": "#FBFBF2", "text": "#212529", "curve": "blue"},
        "dark": {"bg": "#495057", "text": "#F8F9FA", "curve": "red"},
    }

    line_graphs = {}
    for column in df.select_dtypes(include="number").columns:
        for theme, colors in plot_colors.items():
            plt.figure(figsize=(6, 6), facecolor=colors["bg"])
            ax = plt.gca()
            ax.set_facecolor(colors["bg"])

            # Using seaborn's kdeplot to estimate the distribution
            sns.kdeplot(df[column], bw_adjust=0.5, ax=ax, color=colors["curve"])

            # Set a larger font size for the title
            plt.title(
                f"Distribution Estimate for {column}", fontsize=14, color=colors["text"]
            )

            # Add labels to the axes
            plt.xlabel("Values", fontsize=12, color=colors["text"])
            plt.ylabel("Density", fontsize=12, color=colors["text"])
            # Set axis color
            ax.tick_params(colors=colors["text"])
            for spine in ax.spines.values():
                spine.set_color(colors["text"])
            # Encode the plot as base64
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format="png", bbox_inches="tight", pad_inches=0.1)
            img_buffer.seek(0)
            encoded_img = base64.b64encode(img_buffer.read()).decode("utf-8")

            line_graphs[f"{column}_{theme}"] = encoded_img
            plt.close()
            img_buffer.close()

    return line_graphs
