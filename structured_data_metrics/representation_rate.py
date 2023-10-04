def calculate_representation_rate(dataframe, columns):
    representation_rate_info = {}
    try:
        for column in columns:
            column_series = dataframe[column].dropna()  # Drop rows with NaN values
            value_counts = column_series.value_counts(normalize=True)
            
            for attribute_value1 in value_counts.index:
                for attribute_value2 in value_counts.index:
                    if attribute_value1 != attribute_value2:
                        probability_ratio = value_counts[attribute_value1] / value_counts[attribute_value2]
                        key = f"Column: '{column}', Probability ratio for '{attribute_value1}' to '{attribute_value2}'"
                        representation_rate_info[key] = probability_ratio
    
        return representation_rate_info
    except Exception as e:
        return{"Error":"Error calculating representation rate, check column name"}