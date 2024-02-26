def calculate_real_representation_rates(column_name, values, populations):
    representation_rates = {}
    
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            value1 = values[i]
            value2 = values[j]
            
            population1 = int(populations[i])
            population2 = int(populations[j])
            
            ratio1_to_2 = population1 / population2
            ratio2_to_1 = population2 / population1
            
            key1 = f"Column: '{column_name}', Probability ratio for '{value1}' to '{value2}'"
            key2 = f"Column: '{column_name}', Probability ratio for '{value2}' to '{value1}'"
            
            representation_rates[key1] = ratio1_to_2
            representation_rates[key2] = ratio2_to_1
            
    return representation_rates