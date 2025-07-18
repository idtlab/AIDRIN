import re
import matplotlib.pyplot as plt
import base64
import io
from celery import shared_task, Task
from celery.exceptions import SoftTimeLimitExceeded

def extract_keys_and_values(data, parent_key='', separator='_'):
    result = {}
    for key, value in data.items():
        new_key = f"{parent_key}{separator}{key}" if parent_key else key
        if isinstance(value, dict):
            result.update(extract_keys_and_values(value, new_key, separator))
        elif isinstance(value, list):
            for i, item in enumerate(value, start=1):
                if isinstance(item, dict):
                    result.update(extract_keys_and_values(item, f"{new_key}{separator}{i}", separator))
                else:
                    result[f"{new_key}{separator}{i}"] = item
        else:
            result[new_key] = value
    return result


def categorize_metadata(flat_metadata, original_metadata):
    # FAIR principles and criteria
    fair_criteria = {
        "Findable": [
            "identifier", "title", "description", "keyword", "theme", "landingPage"
        ],
        "Accessible": [
            "accessLevel", "downloadURL", "mediaType", "accessURL", "issued", "modified"
        ],
        "Interoperable": [
            "conformsTo", "references", "language", "format", "spatial", "temporal"
        ],
        "Reusable": [
            "license", "rights", "publisher", "description", "format",
            "programCode", "bureauCode", "contactPoint"
        ]
    }

    categories = {k: {} for k in fair_criteria}
    categories["Other"] = {}
    categorized_keys = set()
    fair_pass_counts = {}

    # Normalize and match
    for principle, fields in fair_criteria.items():
        matched = set()
        for field in fields:
            for key in flat_metadata:
                base_key = re.sub(r'_\d+$', '', key)
                if field == base_key or field == key or key.endswith(field):
                    if key not in categorized_keys:
                        categories[principle][key] = flat_metadata[key]
                        categorized_keys.add(key)
                        matched.add(field)
                        break
        fair_pass_counts[principle] = len(matched)

    # Other keys
    for key, value in flat_metadata.items():
        if key not in categorized_keys:
            categories["Other"][key] = value

    # Compliance summary
    total_checks = {k: len(set(v)) for k, v in fair_criteria.items()}
    total_passed = sum(fair_pass_counts.values())
    total_expected = sum(total_checks.values())
    fair_summary = {
        f"{p} Checks": f"{fair_pass_counts[p]}/{total_checks[p]}"
        for p in fair_criteria
    }
    fair_summary["Total Checks"] = f"{total_passed}/{total_expected}"

    # Visualization
    pie_labels = ['Pass', 'Fail']
    pie_sizes = [total_passed, max(0, total_expected - total_passed)]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 4), gridspec_kw={'width_ratios': [3, 3], 'wspace': 0.8})
    plt.rcParams.update({'font.size': 20})

    ax1.pie(pie_sizes, labels=pie_labels, colors=['green', 'lightgray'], autopct='%1.1f%%', startangle=90)
    ax1.axis('equal')
    ax1.set_title('FAIR Compliance Summary')

    bar_labels = list(fair_criteria.keys())
    bar_passed = [fair_pass_counts[k] for k in bar_labels]
    bar_totals = [total_checks[k] for k in bar_labels]
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

    # Final return structure
    categorized_metadata = {
        **categories,
        "FAIR Compliance Checks": fair_summary,
        "Pie chart": encoded_image_combined,
        "Original Metadata": original_metadata
    }

    return categorized_metadata
