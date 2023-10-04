import json

def handle_list_values(lst):
    if isinstance(lst, list):
        return [handle_list_values(item) for item in lst]
    elif isinstance(lst, dict):
        return {k: handle_list_values(v) for k, v in lst.items()}
    else:
        return lst

def categorize_keys_fair(json_data):
    fair_bins = {
        "Findability": [
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
        "Accessibility": [
            "contributors"
        ],
        "Interoperability": [
            "geoLocations"
        ],
        "Reusability": [
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
    fair_scores['Total Checks'] = total_fairness
    categorized_data['FAIRness Score'] = fair_scores
    return categorized_data