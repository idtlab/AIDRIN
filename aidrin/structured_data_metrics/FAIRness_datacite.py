import json
import io
import matplotlib.pyplot as plt
import base64
from celery import shared_task, Task
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
            "Findable": ["identifiers", "creators", "titles", "publisher", "publicationYear", "subjects", "alternateIdentifiers", "relatedIdentifiers", "descriptions", "schemaVersion"],
            "Accessible": ["contributors"],
            "Interoperable": ["geoLocations"],
            "Reusable": ["dates", "language", "sizes", "formats", "version", "rightsList", "fundingReferences"]
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
            "Total Checks": f"{sum(fair_scores.values())}/19"
        }

        # Visualization
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 4), gridspec_kw={'width_ratios': [3, 3], 'wspace': 0.8})
        plt.rcParams.update({'font.size': 20})

        pie_sizes = [sum(fair_scores.values()), 19 - sum(fair_scores.values())]
        ax1.pie(pie_sizes, labels=["Pass", "Fail"], colors=['green', 'lightgray'], autopct='%1.1f%%', startangle=90)
        ax1.axis('equal')
        ax1.set_title('FAIR compliance')

        bar_labels = list(fair_bins.keys())
        bar_passed = [fair_scores[label] for label in bar_labels]
        bar_totals = [len(fair_bins[label]) for label in bar_labels]
        bar_percentages = [p / t * 100 if t else 0 for p, t in zip(bar_passed, bar_totals)]

        bars = ax2.barh(bar_labels, bar_percentages, color='skyblue')
        for i, bar in enumerate(bars):
            ax2.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f"{bar_passed[i]}/{bar_totals[i]}", va='center')
        ax2.set_title("Compliance per Principle")
        ax2.set_xticks([])
        for spine in ax2.spines.values():
            spine.set_visible(False)

        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', bbox_inches='tight')
        plt.close()
        encoded_image_combined = base64.b64encode(buffer.getvalue()).decode('utf-8')

        categorized_data['FAIR Compliance Checks'] = fair_summary
        categorized_data['Pie chart'] = encoded_image_combined
        return categorized_data

    except SoftTimeLimitExceeded:
        raise Exception("Categorize Keys task timed out.")
