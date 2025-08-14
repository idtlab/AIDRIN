import base64
import io
import json

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
            1, 2, figsize=(15, 4), gridspec_kw={"width_ratios": [3, 3], "wspace": 0.8}
        )
        plt.rcParams.update({"font.size": 20})

        pie_sizes = [sum(fair_scores.values()), 19 - sum(fair_scores.values())]
        ax1.pie(
            pie_sizes,
            labels=["Pass", "Fail"],
            colors=["green", "lightgray"],
            autopct="%1.1f%%",
            startangle=90,
        )
        ax1.axis("equal")
        ax1.set_title("FAIR compliance")

        bar_labels = list(fair_bins.keys())
        bar_passed = [fair_scores[label] for label in bar_labels]
        bar_totals = [len(fair_bins[label]) for label in bar_labels]
        bar_percentages = [
            p / t * 100 if t else 0 for p, t in zip(bar_passed, bar_totals)
        ]

        bars = ax2.barh(bar_labels, bar_percentages, color="skyblue")
        for i, bar in enumerate(bars):
            ax2.text(
                bar.get_width(),
                bar.get_y() + bar.get_height() / 2,
                f"{bar_passed[i]}/{bar_totals[i]}",
                va="center",
            )
        ax2.set_title("Compliance per Principle")
        ax2.set_xticks([])
        for spine in ax2.spines.values():
            spine.set_visible(False)

        buffer = io.BytesIO()
        plt.savefig(buffer, format="png", bbox_inches="tight")
        plt.close()
        encoded_image_combined = base64.b64encode(buffer.getvalue()).decode("utf-8")

        categorized_data["FAIR Compliance Checks"] = fair_summary
        categorized_data["Pie chart"] = encoded_image_combined
        return categorized_data

    except SoftTimeLimitExceeded:
        raise Exception("Categorize Keys task timed out.")


def analyze_datacite_fair(data):
    """
    Analyzes a DataCite JSON dataset for FAIR compliance, processes nested metadata,
    categorizes it, and displays a visualization.

    Args:
        data (dict or str): The input DataCite JSON data as a dictionary or a file path to a JSON file.

    Returns:
        dict: Categorized metadata with FAIR compliance checks.

    Raises:
        ValueError: If the input is neither a valid dictionary nor a valid JSON file path.
        FileNotFoundError: If the provided file path does not exist.
        json.JSONDecodeError: If the JSON file is invalid.
    """
    # Handle input: load JSON if a file path is provided
    if isinstance(data, str):
        try:
            with open(data) as file:
                data = json.load(file)
        except FileNotFoundError:
            raise FileNotFoundError(f"The file {data} was not found.")
        except json.JSONDecodeError:
            raise json.JSONDecodeError(f"The file {data} contains invalid JSON.")
    elif not isinstance(data, dict):
        raise ValueError("Input must be a dictionary or a valid JSON file path.")

    # Handle nested lists and dictionaries
    def handle_list_values(item):
        if isinstance(item, list):
            return [handle_list_values(sub_item) for sub_item in item]
        elif isinstance(item, dict):
            return {k: handle_list_values(v) for k, v in item.items()}
        else:
            return item

    # FAIR principles and criteria
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

    # Initialize categories and scores
    categorized_data = {category: {} for category in fair_bins}
    fair_scores = {category: 0 for category in fair_bins}

    # Categorize metadata
    for category, fields in fair_bins.items():
        for field in fields:
            if field in data:
                value = data[field]
                categorized_data[category][field] = handle_list_values(value)
                fair_scores[category] += 1
            else:
                categorized_data[category][field] = "CHECK FAILED ❌"

    # Compliance summary
    fair_summary = {
        "Findability Checks": f"{fair_scores['Findable']}/10",
        "Accessibility Checks": f"{fair_scores['Accessible']}/1",
        "Interoperability Checks": f"{fair_scores['Interoperable']}/1",
        "Reusability Checks": f"{fair_scores['Reusable']}/7",
        "Total Checks": f"{sum(fair_scores.values())}/19",
    }

    # Create visualization
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(15, 4), gridspec_kw={"width_ratios": [3, 3], "wspace": 0.8}
    )
    plt.rcParams.update({"font.size": 20})

    # Pie chart
    pie_sizes = [sum(fair_scores.values()), 19 - sum(fair_scores.values())]
    ax1.pie(
        pie_sizes,
        labels=["Pass", "Fail"],
        colors=["green", "lightgray"],
        autopct="%1.1f%%",
        startangle=90,
    )
    ax1.axis("equal")
    ax1.set_title("FAIR Compliance")

    # Bar chart
    bar_labels = list(fair_bins.keys())
    bar_passed = [fair_scores[label] for label in bar_labels]
    bar_totals = [len(fair_bins[label]) for label in bar_labels]
    bar_percentages = [
        p / t * 100 if t else 0 for p, t in zip(bar_passed, bar_totals)
    ]

    bars = ax2.barh(bar_labels, bar_percentages, color="skyblue")
    for i, bar in enumerate(bars):
        ax2.text(
            bar.get_width(),
            bar.get_y() + bar.get_height() / 2,
            f"{bar_passed[i]}/{bar_totals[i]}",
            va="center",
        )
    ax2.set_title("Compliance per Principle")
    ax2.set_xticks([])
    for spine in ax2.spines.values():
        spine.set_visible(False)

    # Display the plot
    plt.show()

    # Final result
    categorized_data["FAIR Compliance Checks"] = fair_summary
    return categorized_data
