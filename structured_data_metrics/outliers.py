import pandas as pd
import numpy as np

def outliers(file):
    try:
        out_dict = {}
        # Select numerical columns for outlier detection
        numerical_columns = file.select_dtypes(include=[np.number])
        #drop nan
        numerical_columns_dropna = numerical_columns.dropna()

        #IQR method
        q1=numerical_columns_dropna.quantile(0.25)
        q3=numerical_columns_dropna.quantile(0.75)
        IQR=q3-q1
        outliers = numerical_columns_dropna[((numerical_columns_dropna<(q1-1.5*IQR)) | (numerical_columns_dropna>(q3+1.5*IQR)))]

        # Calculate the proportion outliers in each column
        proportions = outliers.notna().mean()

        # Convert the proportions Series to a dictionary
        proportions_dict = proportions.to_dict()
        
        # Calculate the average of dictionary values
        average_value = sum(proportions_dict.values()) / len(proportions_dict)
        proportions_dict['Overall outlier score'] = average_value
        #add the average to dictionary
        out_dict['Outlier scores'] = proportions_dict

        return out_dict
    except Exception as e:
        return {"Error":"Check features should be numerical"}