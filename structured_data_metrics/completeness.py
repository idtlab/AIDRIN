import matplotlib.pyplot as plt
import io
import base64


def completeness(file):
    # Calculate completeness metric for each column
    completeness_scores = (1 - file.isnull().mean()).to_dict()

    # Calculate overall completeness metric for the dataset

    overall_completeness = file.isnull().any(axis=1).mean()

    result_dict = {}

    if overall_completeness != 0:
        # Add completeness scores to the dictionary
        result_dict["Completeness scores"] = completeness_scores

        # Create a bar chart
        plt.figure(figsize=(8, 8))
        plt.bar(completeness_scores.keys(), completeness_scores.values(), color='blue')
        plt.title('Completeness Scores for Each Column')
        plt.xlabel('Columns')
        plt.ylabel('Completeness Score')
        plt.ylim(0, 1)  # Setting y-axis limit between 0 and 1 for completeness scores

        # Rotate x-axis tick labels
        plt.xticks(rotation=45, ha='right')

        plt.subplots_adjust(bottom=0.5)
        plt.tight_layout()

        # Save the chart to a BytesIO object
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png')
        img_buf.seek(0)

        # Encode the image as base64
        img_base64 = base64.b64encode(img_buf.read()).decode('utf-8')

        # Add the base64-encoded image to the dictionary under a separate key
        result_dict["Completeness Visualization"] = img_base64

        plt.close()  # Close the plot to free up resources

        # Add overall completeness to the dictionary
        result_dict['Overall Completeness'] = overall_completeness
    elif overall_completeness == 0:
        result_dict["Overall Completeness of Dataset"] = 1
    else:
        result_dict["Overall Completeness of Dataset"] = "Error"

    return result_dict
