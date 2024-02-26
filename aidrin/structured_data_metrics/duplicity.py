def duplicity(file):
    dup_dict = {}
    # Calculate the proportion of duplicate values
    duplicate_proportions = (file.duplicated().sum() / len(file)) 
    
    dup_dict["Duplicity scores"]={'Overall duplicity of the dataset': duplicate_proportions}
    
    return dup_dict