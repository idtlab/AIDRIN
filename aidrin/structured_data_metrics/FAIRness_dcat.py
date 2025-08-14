import base64
import io
import re
import json

import matplotlib.pyplot as plt
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded


@shared_task(bind=True, ignore_result=False)
def extract_keys_and_values(self: Task, data, parent_key="", separator="_"):
    try:
        result = {}
        for key, value in data.items():
            new_key = f"{parent_key}{separator}{key}" if parent_key else key
            if isinstance(value, dict):
                result.update(extract_keys_and_values(value, new_key, separator))
            elif isinstance(value, list):
                for i, item in enumerate(value, start=1):
                    if isinstance(item, dict):
                        result.update(
                            extract_keys_and_values(
                                item, f"{new_key}{separator}{i}", separator
                            )
                        )
                    else:
                        result[f"{new_key}{separator}{i}"] = item
            else:
                result[new_key] = value
        return result
    except SoftTimeLimitExceeded:
        raise Exception("Extract keys and values task timed out.")


@shared_task(bind=True, ignore_result=False)
def categorize_metadata(self: Task, flat_metadata, original_metadata):
    try:
        # FAIR principles and criteria
        fair_criteria = {
            "Findable": [
                "identifier",
                "title",
                "description",
                "keyword",
                "theme",
                "landingPage",
            ],
            "Accessible": [
                "accessLevel",
                "downloadURL",
                "mediaType",
                "accessURL",
                "issued",
                "modified",
            ],
            "Interoperable": [
                "conformsTo",
                "references",
                "language",
                "format",
                "spatial",
                "temporal",
            ],
            "Reusable": [
                "license",
                "rights",
                "publisher",
                "description",
                "format",
                "programCode",
                "bureauCode",
                "contactPoint",
            ],
        }

        categories = {k: {} for k in fair_criteria}
        categories["Other"] = {}
        categorized_keys = set()
        fair_pass_counts = {}

        # Normalize and match
        for principle, fields in fair_criteria.items():
            matched = 0
            for field in fields:
                found = False
                for key in flat_metadata:
                    base_key = re.sub(r"_\d+$", "", key)
                    if field == base_key or field == key or key.endswith(field):
                        if key not in categorized_keys:
                            categories[principle][field] = flat_metadata[key]
                            categorized_keys.add(key)
                            matched += 1
                            found = True
                            break
                if not found:
                    categories[principle][field] = "CHECK FAILED ❌"
            fair_pass_counts[principle] = matched

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
        pie_labels = ["Pass", "Fail"]
        pie_sizes = [total_passed, max(0, total_expected - total_passed)]

        fig, (ax1, ax2) = plt.subplots(
            1, 2, figsize=(15, 4), gridspec_kw={"width_ratios": [3, 3], "wspace": 0.8}
        )
        plt.rcParams.update({"font.size": 20})

        ax1.pie(
            pie_sizes,
            labels=pie_labels,
            colors=["green", "lightgray"],
            autopct="%1.1f%%",
            startangle=90,
        )
        ax1.axis("equal")
        ax1.set_title("FAIR Compliance Summary")

        bar_labels = list(fair_criteria.keys())
        bar_passed = [fair_pass_counts[k] for k in bar_labels]
        bar_totals = [total_checks[k] for k in bar_labels]
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

        # Final return structure
        categorized_metadata = {
            **categories,
            "FAIR Compliance Checks": fair_summary,
            "Pie chart": encoded_image_combined,
            "Original Metadata": original_metadata,
        }

        return categorized_metadata
    except SoftTimeLimitExceeded:
        raise Exception("Categorize metadata task timed out.")


def analyze_dcat_fair(data):
    """
    Analyzes a DCAT JSON dataset for FAIR compliance, flattens metadata, categorizes it,
    and displays a visualization.

    Args:
        data (dict or str): The input DCAT JSON data as a dictionary or a file path to a JSON file.

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

    # Flatten the metadata
    def extract_keys_and_values(data, parent_key="", separator="_"):
        result = {}
        for key, value in data.items():
            new_key = f"{parent_key}{separator}{key}" if parent_key else key
            if isinstance(value, dict):
                result.update(extract_keys_and_values(value, new_key, separator))
            elif isinstance(value, list):
                for i, item in enumerate(value, start=1):
                    if isinstance(item, dict):
                        result.update(
                            extract_keys_and_values(item, f"{new_key}{separator}{i}", separator)
                        )
                    else:
                        result[f"{new_key}{separator}{i}"] = item
            else:
                result[new_key] = value
        return result

    flat_metadata = extract_keys_and_values(data)

    # FAIR principles and criteria
    fair_criteria = {
        "Findable": [
            "identifier",
            "title",
            "description",
            "keyword",
            "theme",
            "landingPage",
        ],
        "Accessible": [
            "accessLevel",
            "downloadURL",
            "mediaType",
            "accessURL",
            "issued",
            "modified",
        ],
        "Interoperable": [
            "conformsTo",
            "references",
            "language",
            "format",
            "spatial",
            "temporal",
        ],
        "Reusable": [
            "license",
            "rights",
            "publisher",
            "description",
            "format",
            "programCode",
            "bureauCode",
            "contactPoint",
        ],
    }

    # Initialize categories and tracking
    categories = {k: {} for k in fair_criteria}
    categories["Other"] = {}
    categorized_keys = set()
    fair_pass_counts = {}

    # Categorize metadata
    for principle, fields in fair_criteria.items():
        matched = 0
        for field in fields:
            found = False
            for key in flat_metadata:
                base_key = re.sub(r"_\d+$", "", key)
                if field == base_key or field == key or key.endswith(field):
                    if key not in categorized_keys:
                        categories[principle][field] = flat_metadata[key]
                        categorized_keys.add(key)
                        matched += 1
                        found = True
                        break
            if not found:
                categories[principle][field] = "CHECK FAILED ❌"
        fair_pass_counts[principle] = matched

    # Add uncategorized keys to Other
    for key, value in flat_metadata.items():
        if key not in categorized_keys:
            categories["Other"][key] = value

    # Compliance summary
    total_checks = {k: len(set(v)) for k, v in fair_criteria.items()}
    total_passed = sum(fair_pass_counts.values())
    total_expected = sum(total_checks.values())
    fair_summary = {
        f"{p} Checks": f"{fair_pass_counts[p]}/{total_checks[p]}" for p in fair_criteria
    }
    fair_summary["Total Checks"] = f"{total_passed}/{total_expected}"

    # Create visualization
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(15, 4), gridspec_kw={"width_ratios": [3, 3], "wspace": 0.8}
    )
    plt.rcParams.update({"font.size": 20})

    # Pie chart
    pie_labels = ["Pass", "Fail"]
    pie_sizes = [total_passed, max(0, total_expected - total_passed)]  # Fixed typo here
    ax1.pie(
        pie_sizes,
        labels=pie_labels,
        colors=["green", "lightgray"],
        autopct="%1.1f%%",
        startangle=90,
    )
    ax1.axis("equal")
    ax1.set_title("FAIR Compliance Summary")

    # Bar chart
    bar_labels = list(fair_criteria.keys())
    bar_passed = [fair_pass_counts[k] for k in bar_labels]
    bar_totals = [total_checks[k] for k in bar_labels]
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
    categorized_metadata = {
        **categories,
        "FAIR Compliance Checks": fair_summary,
        "Original Metadata": data,
    }

    return categorized_metadata
