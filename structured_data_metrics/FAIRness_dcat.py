import re


# Function to extract keys and values and create a dictionary
def extract_keys_and_values(data, parent_key='', separator='_'):

    result_dict = {}
    for key, value in data.items():
        new_key = f"{parent_key}{separator}{key}" if parent_key else key
        if isinstance(value, dict):
            result_dict.update(extract_keys_and_values(value, new_key, separator=separator))
        elif isinstance(value, list):
            for i, item in enumerate(value, start=1):
                if isinstance(item, dict):
                    result_dict.update(extract_keys_and_values(item, f"{new_key}{separator}{i}", separator=separator))
                else:
                    result_dict[f"{new_key}{separator}{i}"] = item
        else:
            result_dict[new_key] = value
    
    return result_dict




def categorize_metadata(metadata_dict,original_metadata):
    # Initialize dictionaries for each category
    findable = {}
    accessible = {}
    interoperable = {}
    reusable = {}
    other = {}
    find_c,acc_c,inter_c,reu_c = 0,0,0,0
    find_tot_checks = 4
    acc_tot_checks = 3
    inter_tot_checks = 3
    reu_tot_checks = 2

    find_iter,acc_iter,inter_iter,reu_iter = 0,0,0,0

    keyword_weight = 0.1
    for key, value in metadata_dict.items():
        categorized = False  # Flag to track if the key was categorized
        
        # Findable
        if key in ["identifier", "description","title"]:
            find_c+=1
            findable[key] = value
            categorized = True
        elif key.startswith("keyword"):
            if find_iter > 0:
                find_tot_checks += keyword_weight
                find_c+=keyword_weight
                findable[key] = value
                categorized = True
            else:
                find_c+=1
                findable[key] = value
                categorized = True
                find_iter+=1
        # Accessible
        elif key in ['accessLevel']:
            accessible[key] = value
            acc_c+=1
            categorized = True
        elif key.endswith("fn") or key.endswith("hasEmail"):
            if acc_iter > 2:
                acc_tot_checks+=1
                
            accessible[key] = value
            acc_c+=1
            categorized = True
        # Interoperable
        elif key.endswith("conformsTo"):
            interoperable[key] = value
            inter_c+=1
            categorized = True
        elif  key.startswith("bureauCode") or key.endswith("programCode"):
            if inter_iter > 2:
                inter_tot_checks+=1
            interoperable[key] = value
            inter_c+=1
            categorized = True
        
        # Reusable
        elif key.endswith("modified"):
            reusable[key] = value
            reu_c+=1
            categorized = True
        
        elif re.match(r"publisher_\d+_name", key) or re.match(r"publisher_name", key):
            if reu_iter > 1:
                reu_tot_checks+=1

            reusable[key] = value
            reu_c+=1
            categorized = True
        # Other (not in predefined categories)
        if not categorized:
            other[key] = value

    # Create a dictionary containing the categorized key-value pairs
    categorized_metadata = {
        "Findable": findable,
        "Accessible": accessible,
        "Interoperable": interoperable,
        "Reusable": reusable,
        "FAIRness Score": {"Findablity Checks":"{}/{}".format(round(find_c,2),round(find_tot_checks,2)),"Accesseiblity Checks":"{}/{}".format(round(acc_c,2),round(acc_tot_checks,2)),"Interoperability Checks":"{}/{}".format(round(inter_c,2),round(inter_tot_checks,2)),"Reusability Checks":"{}/{}".format(round(reu_c,2),round(reu_tot_checks,2)),"Total Checks":find_c+acc_c+inter_c+reu_c},
        "Other": other,  # All other keys
        "Original Metadata":original_metadata
    }

    return categorized_metadata

# Extract keys and values and create a dictionary
# result_dict = extract_keys_and_values(data_dict)

# Print the resulting dictionary
# for key, value in result_dict.items():
#     print(f"{key}: {value}")

# Categorize the metadata
# categorized_metadata = categorize_metadata(result_dict)

# for category, category_dict in categorized_metadata.items():
#     print(f"{category}:")
#     for key, value in category_dict.items():
#         print(f"{key}: {value}")
#     print()