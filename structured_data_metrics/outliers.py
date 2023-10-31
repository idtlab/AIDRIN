import base64
import io
import matplotlib.pyplot as plt
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

        # Create a bar chart for outlier scores
        plt.figure(figsize=(8, 8))
        plt.bar(proportions_dict.keys(), proportions_dict.values(), color='red')
        plt.title('Proportion of Outliers for Numerical Columns')
        plt.xlabel('Columns')
        plt.ylabel('Proportion of Outliers')
        # plt.ylim(0, 1)  # Setting y-axis limit between 0 and 1

        # Rotate x-axis tick labels
        plt.xticks(rotation=45, ha='right')

        # Increase bottom margin
        plt.subplots_adjust(bottom=0.5)
        plt.tight_layout()

        # Save the chart to BytesIO and encode as base64
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png')
        img_buf.seek(0)
        img_base64 = base64.b64encode(img_buf.read()).decode('utf-8')

        # Add the base64-encoded image to the dictionary under a separate key
        out_dict["Outliers Visualization"] = img_base64

        plt.close()  # Close the plot to free up resources

        return out_dict
    except Exception as e:
        return {"Error":"Check features should be numerical"}