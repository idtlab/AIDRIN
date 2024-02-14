import json
import io
import matplotlib.pyplot as plt
import base64

def handle_list_values(lst):
    if isinstance(lst, list):
        return [handle_list_values(item) for item in lst]
    elif isinstance(lst, dict):
        return {k: handle_list_values(v) for k, v in lst.items()}
    else:
        return lst

def categorize_keys_fair(json_data):
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
            "schemaVersion"
        ],
        "Accessible": [
            "contributors"
        ],
        "Interoperable": [
            "geoLocations"
        ],
        "Reusable": [
            "dates",
            "language",
            "sizes",
            "formats",
            "version",
            "rightsList",
            "fundingReferences"
        ]
    }

    categorized_data = {category: {} for category in fair_bins}
    fair_scores = {category: 0 for category in fair_bins}
    
    for key, value in json_data.items():
        for category, category_keys in fair_bins.items():
            if key in category_keys:
                if isinstance(value, list):
                    fair_scores[category] += len(value)
                    categorized_data[category][key] = [handle_list_values(item) for item in value]
                else:
                    fair_scores[category] += 1
                    categorized_data[category][key] = value
    total_fairness = sum(fair_scores.values())
    fair_scores = {
        'Findability Checks': fair_scores['Findable'],
        'Accessibility Checks': fair_scores['Accessible'],
        'Iteroperability Checks': fair_scores['Interoperable'],
        'Reusability Checks': fair_scores['Reusable']
    }
    fair_scores['Total Checks'] = total_fairness
    categorized_data['FAIR Compliance Checks'] = fair_scores

    # Generate a pie chart
    labels = list(fair_scores.keys())[:-1]  # Exclude 'Total Checks' label
    sizes = [score / total_fairness * 100 for score in fair_scores.values() if score != total_fairness]

    fig, ax = plt.subplots()
    ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140)
    ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.
    # Save the pie chart to a BytesIO object
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)

    # Encode the BytesIO object as base64
    pie_chart_base64 = base64.b64encode(buffer.read()).decode('utf-8')

    categorized_data['Pie chart'] = pie_chart_base64
    return categorized_data