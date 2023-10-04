
def completeness(file):
    # Calculate completeness metric for each column
    completeness_scores = (1 - file.isnull().mean()).to_dict()
    
    # Calculate overall completeness metric for the dataset
    overall_completeness = file.isnull().any(axis=1).mean()
    
    if overall_completeness:
        completeness_scores['Overall Completeness'] = overall_completeness
        return {"Completeness scores":completeness_scores}
    else:
        return {"Overall Completeness of Dataset":"Error"}