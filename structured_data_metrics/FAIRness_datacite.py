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
                    fair_scores[category] += 1
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

    tot_score_each = [fair_scores[key] for key in fair_scores if key != 'Total Checks']
    labels = [key for key in fair_scores if key != 'Total Checks']

   # Plot Pie Chart
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 4), gridspec_kw={'width_ratios': [3, 3], 'wspace': 0.8})  # 1 row, 2 columns

    
    ax1.pie(tot_score_each, labels=labels, autopct='%1.1f%%', startangle=90)
    ax1.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

    # Plot Horizontal Bar Chart for Percentage of Completed Checks
    categories = ["Findability", "Accessibility", "Interoperability", "Reusability"]
    percentages = [fair_scores['Findability Checks'] / tot_score_each[0] * 100,
                fair_scores['Accessibility Checks'] / tot_score_each[1] * 100,
                fair_scores['Iteroperability Checks'] / tot_score_each[2] * 100,
                fair_scores['Reusability Checks'] / tot_score_each[3] * 100]

    bars = ax2.barh(categories, percentages, color='skyblue')
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)
    ax2.spines['bottom'].set_visible(False)
    ax2.spines['left'].set_visible(False)
    ax2.set_xticks([])  # Remove x tick values

    # Display the percentage values on the bars
    for bar in bars:
        plt.text(bar.get_width(), bar.get_y() + bar.get_height()/2, f'{bar.get_width():.2f}%', va='center')

    # Save the plot to a BytesIO object
    image_stream_combined = io.BytesIO()
    plt.savefig(image_stream_combined, format='png')
    plt.close()

    # Encode the BytesIO content as base64
    encoded_image_combined = base64.b64encode(image_stream_combined.getvalue()).decode('utf-8')

    # Define suffixes for each key
    suffixes = {
        'Findability Checks': "/10",
        'Accessibility Checks': "/1",
        'Iteroperability Checks': "/1",
        'Reusability Checks': "/7",
        'Total Checks': "/19"
    }

    # Convert values to strings and add respective suffixes
    for key in categorized_data['FAIR Compliance Checks']:
        categorized_data['FAIR Compliance Checks'][key] = str(fair_scores[key]) + suffixes[key]
    

    categorized_data['Pie chart'] = encoded_image_combined
    return categorized_data