import base64
import io

import matplotlib.pyplot as plt
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded


@shared_task(bind=True, ignore_result=False)
def handle_list_values(self: Task, lst):
    try:
        if isinstance(lst, list):
            return [handle_list_values(item) for item in lst]
        elif isinstance(lst, dict):
            return {k: handle_list_values(v) for k, v in lst.items()}
        else:
            return lst
    except SoftTimeLimitExceeded:
        raise Exception("Handle List Values task timed out.")


@shared_task(bind=True, ignore_result=False)
def categorize_keys_fair(self: Task, json_data):
    try:
        fair_bins = {
            "Findable": [
                "identifiers",
                "creators",
                "titles",
                "publisher",
                "publicationYear",
                "subjects",
                "alternateIdentifiers",
                "relatedIdentifiers",
                "descriptions",
                "schemaVersion",
            ],
            "Accessible": ["contributors"],
            "Interoperable": ["geoLocations"],
            "Reusable": [
                "dates",
                "language",
                "sizes",
                "formats",
                "version",
                "rightsList",
                "fundingReferences",
            ],
        }

        categorized_data = {category: {} for category in fair_bins}
        fair_scores = {category: 0 for category in fair_bins}

        for category, fields in fair_bins.items():
            for field in fields:
                if field in json_data:
                    value = json_data[field]
                    categorized_data[category][field] = handle_list_values(value)
                    fair_scores[category] += 1
                else:
                    categorized_data[category][field] = "CHECK FAILED ❌"

        fair_summary = {
            "Findability Checks": f"{fair_scores['Findable']}/10",
            "Accessibility Checks": f"{fair_scores['Accessible']}/1",
            "Interoperability Checks": f"{fair_scores['Interoperable']}/1",
            "Reusability Checks": f"{fair_scores['Reusable']}/7",
            "Total Checks": f"{sum(fair_scores.values())}/19",
        }

        # Visualization
        fig, (ax1, ax2) = plt.subplots(
            1, 2, figsize=(6, 2.5),
            gridspec_kw={"width_ratios": [1, 2], "wspace": 0.6}
        )

        pie_sizes = [sum(fair_scores.values()), 19 - sum(fair_scores.values())]
        ax1.pie(
            pie_sizes,
            labels=["Pass", "Fail"],
            colors=["#4485F4", "#e5e7eb"],
            autopct="%1.1f%%",
            startangle=90,
            textprops={"fontsize": 10, "color": "#6b7280"},
        )
        ax1.axis("equal")

        bar_labels = list(fair_bins.keys())
        bar_passed = [fair_scores[label] for label in bar_labels]
        bar_totals = [len(fair_bins[label]) for label in bar_labels]
        bar_percentages = [
            p / t * 100 if t else 0 for p, t in zip(bar_passed, bar_totals)
        ]

        bar_colors = ["#3b82f6", "#22c55e", "#eab308", "#f97316"]
        bars = ax2.barh(bar_labels, bar_percentages, color=bar_colors[:len(bar_labels)], height=0.5)
        for i, bar in enumerate(bars):
            ax2.text(
                bar.get_width() + 1,
                bar.get_y() + bar.get_height() / 2,
                f"{bar_passed[i]}/{bar_totals[i]}",
                va="center", fontsize=9, color="#6b7280",
            )
        ax2.set_xlim(0, 110)
        ax2.set_xticks([])
        ax2.tick_params(axis="y", labelsize=9, colors="#6b7280")
        for spine in ax2.spines.values():
            spine.set_visible(False)
        fig.patch.set_alpha(0)
        ax1.set_facecolor("none")
        ax2.set_facecolor("none")

        fig.tight_layout(pad=0.5)
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=200, transparent=True)
        plt.close(fig)
        encoded_image_combined = base64.b64encode(buffer.getvalue()).decode("utf-8")

        categorized_data["FAIR Compliance Checks"] = fair_summary
        categorized_data["Pie chart"] = encoded_image_combined
        return categorized_data

    except SoftTimeLimitExceeded:
        raise Exception("Categorize Keys task timed out.")
