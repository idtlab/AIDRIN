import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from typing import List, Dict
from dython.nominal import associations
import seaborn as sns
import base64
from io import BytesIO

matplotlib.use('Agg')

NOMINAL_NOMINAL_ASSOC = 'theil'

def calc_correlations(df: pd.DataFrame, columns: List[str]) -> Dict:
    try:
        # Separate categorical and numerical columns
        categorical_columns = df[columns].select_dtypes(include='object').columns
        numerical_columns = df[columns].select_dtypes(exclude='object').columns

        result_dict = {}

        # Check if there are categorical features
        if not categorical_columns.empty:
            # Categorical-categorical correlations are computed using theil
            categorical_correlation = associations(df[categorical_columns], nom_nom_assoc=NOMINAL_NOMINAL_ASSOC, plot=False)

            # Create a subplot with 1 row and 1 column
            fig, axes = plt.subplots(1, 1, figsize=(8, 8))

            # Plot for categorical-categorical correlations
            cax1 = sns.heatmap(categorical_correlation['corr'], annot=True, cmap='coolwarm', fmt='.2f', ax=axes)
            axes.set_title('Categorical-Categorical Correlation Matrix')
            axes.tick_params(axis='x', rotation=45, labelsize=8)
            axes.tick_params(axis='y', rotation=0, labelsize=8)

            # Save the plot to a BytesIO object
            image_stream_cat = BytesIO()
            plt.savefig(image_stream_cat, format='png')
            plt.close()

            # Convert the plot to base64
            base64_image_cat = base64.b64encode(image_stream_cat.getvalue()).decode('utf-8')

            # Close the BytesIO stream
            image_stream_cat.close()

            result_dict["Categorical-Categorical Correlation Matrix"] = base64_image_cat

        # Check if there are numerical features
        if not numerical_columns.empty:
            # Numerical-numerical correlations are computed using pearson
            numerical_correlation = df[numerical_columns].corr()

            # Create a subplot with 1 row and 1 column
            fig, axes = plt.subplots(1, 1, figsize=(8, 8))

            # Plot for numerical-numerical correlations
            cax2 = sns.heatmap(numerical_correlation, annot=True, cmap='coolwarm', fmt='.2f', ax=axes)
            axes.set_title('Numerical-Numerical Correlation Matrix')
            axes.tick_params(axis='x', rotation=45, labelsize=8)
            axes.tick_params(axis='y', rotation=0, labelsize=8)

            # Save the plot to a BytesIO object
            image_stream_num = BytesIO()
            plt.savefig(image_stream_num, format='png')
            plt.close()

            # Convert the plot to base64
            base64_image_num = base64.b64encode(image_stream_num.getvalue()).decode('utf-8')

            # Close the BytesIO stream
            image_stream_num.close()

            result_dict["Numerical-Numerical Correlation Matrix"] = base64_image_num

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
    except Exception as e:
        return {"Message": f"Error: {str(e)}"}
