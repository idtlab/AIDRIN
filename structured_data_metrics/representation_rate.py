import pandas as pd
import matplotlib.pyplot as plt
import io
import base64

def calculate_representation_rate(dataframe, columns):
    representation_rate_info = {}
    processed_keys = set()  # Using a set to track processed pairs
    x_tick_keys = []
    try:
        for column in columns:
            column_series = dataframe[column].dropna()  # Drop rows with NaN values
            value_counts = column_series.value_counts(normalize=True)
            
            for attribute_value1 in value_counts.index:
                for attribute_value2 in value_counts.index:
                    if attribute_value1 != attribute_value2:
                        # Check if the pair has been processed or its reverse
                        pair = f"{attribute_value1} vs {attribute_value2}"
                        reverse_pair = f"{attribute_value2} vs {attribute_value1}"

                        if pair in processed_keys or reverse_pair in processed_keys:
                            continue

                        probability_ratio = value_counts[attribute_value1] / value_counts[attribute_value2]
                        key = f"Column: '{column}', Probability ratio for '{attribute_value1}' to '{attribute_value2}'"
                        x_tick_keys.append(f"{attribute_value1} vs {attribute_value2}")
                        processed_keys.add(pair)  # Mark the pair as processed
                        representation_rate_info[key] = probability_ratio

        return representation_rate_info
    except Exception as e:
        return {"Error": f"Error calculating representation rate: {str(e)}"}


def create_representation_rate_vis(dataframe, columns):
    x_tick_keys = []
    try:
        for column in columns:
            column_series = dataframe[column].dropna()  # Drop rows with NaN values
            total_count = len(column_series)
            value_counts = column_series.value_counts(normalize=True)

            for attribute_value in value_counts.index:
                proportion = value_counts[attribute_value] * 100  # Calculate the proportion as a percentage
                x_tick_keys.append(f"{attribute_value}")

        # Create a bar chart
        plt.figure(figsize=(12, 6))
        values = [value_counts[attribute_value] * 100 for attribute_value in value_counts.index]

        # Plot the bar chart
        plt.bar(x_tick_keys, values, color='blue')
        plt.title('Proportion of Attribute Values Against Total')
        plt.xlabel('Attribute Values')
        plt.ylabel('Proportion (%)')
        plt.xticks(rotation=45, ha='right')  # Rotate x-axis labels by 45 degrees for better readability

        plt.subplots_adjust(bottom=0.5, left=0.2)

        # Save the chart to a BytesIO object
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png')
        img_buf.seek(0)

        # Encode the image as base64
        img_base64 = base64.b64encode(img_buf.read()).decode('utf-8')

        plt.close()  # Close the plot to free up resources

        return img_base64
    except Exception as e:
        return {"Error": f"Error calculating representation rate: {str(e)}"}
