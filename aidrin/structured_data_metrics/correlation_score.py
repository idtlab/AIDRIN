import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from typing import List, Dict
from dython.nominal import associations
import seaborn as sns
import base64
from io import BytesIO
from celery import shared_task, Task
from celery.exceptions import SoftTimeLimitExceeded
from aidrin.read_file import read_file

matplotlib.use('Agg')

NOMINAL_NOMINAL_ASSOC = 'theil'

@shared_task(bind=True, ignore_result=False)
def calc_correlations(self: Task, columns: List[str], file_info):
    df,_,_ = read_file(file_info)
    try:
        # Separate categorical and numerical columns
        categorical_columns = df[columns].select_dtypes(include='object').columns
        numerical_columns = df[columns].select_dtypes(exclude='object').columns

        result_dict = {'Correlations Analysis Categorical': {}, 'Correlations Analysis Numerical': {}, 'Correlation Scores': {}}

        # Check if there are categorical features
        if not categorical_columns.empty:
            # Categorical-categorical correlations are computed using theil
            categorical_correlation = associations(df[categorical_columns], nom_nom_assoc=NOMINAL_NOMINAL_ASSOC, plot=False)
            print(categorical_correlation['corr'])

            # Create a subplot with 1 row and 1 column
            fig, axes = plt.subplots(1, 1, figsize=(8, 8))

            # Plot for categorical-categorical correlations
            cax1 = sns.heatmap(categorical_correlation['corr'], annot=True, cmap='coolwarm', fmt='.2f', ax=axes)
            axes.set_title('Categorical-Categorical Correlation Matrix')
            axes.tick_params(axis='x', rotation=0, labelsize=12)
            axes.tick_params(axis='y', rotation=90, labelsize=12)

            # Add trailing 3 dots if the label is longer than 9 characters
            tick_labels = axes.get_xticklabels()
            for label in tick_labels:
                if len(label.get_text()) > 9:
                    label.set_text(label.get_text()[:9] + '...')

            tick_labels = axes.get_yticklabels()
            for label in tick_labels:
                if len(label.get_text()) > 9:
                    label.set_text(label.get_text()[:9] + '...')

            plt.show()

            # Save the plot to a BytesIO object
            image_stream_cat = BytesIO()
            plt.savefig(image_stream_cat, format='png')
            plt.close()

            # Convert the plot to base64
            base64_image_cat = base64.b64encode(image_stream_cat.getvalue()).decode('utf-8')

            # Close the BytesIO stream
            image_stream_cat.close()

            result_dict['Correlations Analysis Categorical']["Correlations Analysis Categorical Visualization"] = base64_image_cat
            result_dict['Correlations Analysis Categorical']["Description"] = "Categorical correlations are calculated using Theil's U, with values ranging from 0 to 1. A value of 1 indicates a perfect correlation, while a value of 0 indicates no correlation"
            
        # Check if there are numerical features
        if not numerical_columns.empty:
            # Numerical-numerical correlations are computed using pearson
            numerical_correlation = df[numerical_columns].corr()

            # Create a subplot with 1 row and 1 column
            fig, axes = plt.subplots(1, 1, figsize=(8, 8))

            # Plot for numerical-numerical correlations
            cax2 = sns.heatmap(numerical_correlation, annot=True, cmap='coolwarm', fmt='.2f', ax=axes)
            axes.set_title('Numerical-Numerical Correlation Matrix')
            axes.tick_params(axis='x', rotation=0, labelsize=12)
            axes.tick_params(axis='y', rotation=90, labelsize=12)

            # Save the plot to a BytesIO object
            image_stream_num = BytesIO()
            plt.savefig(image_stream_num, format='png')
            plt.close()

            # Convert the plot to base64
            base64_image_num = base64.b64encode(image_stream_num.getvalue()).decode('utf-8')

            # Close the BytesIO stream
            image_stream_num.close()

            result_dict['Correlations Analysis Numerical']["Correlations Analysis Numerical Visualization"] = base64_image_num
            result_dict['Correlations Analysis Numerical']["Description"] = "Numerical correlations are calculated using Pearson's correlation coefficient, with values ranging from -1 to 1. A value of 1 indicates a perfect positive correlation, -1 indicates a perfect negative correlation, and 0 indicates no correlation"

        # Create and return a dictionary with correlation scores and plots
        correlation_dict = {}
        if not categorical_columns.empty:
            for col1 in categorical_correlation['corr'].columns:
                for col2 in categorical_correlation['corr'].columns:
                    if col1 != col2:
                        key = f"{col1} vs {col2}"
                        correlation_dict[key] = categorical_correlation['corr'].loc[col1, col2]

        if not numerical_columns.empty:
            for col1 in numerical_correlation.columns:
                for col2 in numerical_correlation.columns:
                    if col1 != col2:
                        key = f"{col1} vs {col2}"
                        correlation_dict[key] = numerical_correlation.loc[col1, col2]

        result_dict["Correlation Scores"] = correlation_dict

        return result_dict
    except SoftTimeLimitExceeded:
        raise Exception("Correlations task timed out.")
    except Exception as e:
        return {"Message": f"Error: {str(e)}"}
