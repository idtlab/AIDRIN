import io
import base64
import matplotlib.pyplot as plt
import time
from celery.exceptions import SoftTimeLimitExceeded
from aidrin.read_file import read_file
from celery import shared_task, Task

@shared_task(bind=True, ignore_result=False)
def completeness(self: Task, file_info):
    try:
        file, _, _ = read_file(file_info)
        # Calculate completeness metric for each column
        completeness_scores = (1 - file.isnull().mean()).to_dict()
        # Calculate overall completeness metric for the dataset
        overall_completeness = 1 - file.isnull().any(axis=1).mean()

        result_dict = {}

        if overall_completeness != 0 and overall_completeness != 1:
            
            # Filter out columns with completeness score of 1
            incomplete_columns = {k: v for k, v in completeness_scores.items() if v < 1}

            if incomplete_columns:
                # Add completeness scores to the dictionary
                result_dict["Completeness scores"] = incomplete_columns

                # Create a bar chart
                plt.figure(figsize=(8, 8))
                plt.bar(incomplete_columns.keys(), incomplete_columns.values(), color='blue')
                plt.title('Completeness Scores', fontsize=16)
                plt.xlabel('Columns', fontsize=14)
                plt.ylabel('Completeness Score', fontsize=14)
                plt.ylim(0, 1)  # Setting y-axis limit between 0 and 1 for completeness scores

                # Rotate x-axis tick labels
                plt.xticks(rotation=45, ha='right', fontsize=12)

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

        elif overall_completeness == 1:
            # Create a bar chart for 0 completeness
            plt.figure(figsize=(8, 4))
            plt.bar(['Overall Missingness'], [0], color='red')
            plt.title('Missingness of the Dataset')
            plt.xlabel('Dataset')
            plt.ylabel('Missingness Score')
            plt.ylim(0, 1)  # Setting y-axis limit between 0 and 1 for completeness scores

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
            result_dict['Overall Completeness'] = 1
        else:
            result_dict["Overall Completeness of Dataset"] = "Error"

        return result_dict
    except SoftTimeLimitExceeded:
        raise Exception("Completeness task timed out.")
