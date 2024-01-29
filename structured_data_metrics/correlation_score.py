# import pandas as pd
# import matplotlib
# import matplotlib.pyplot as plt
# from typing import List, Dict
# from dython.nominal import associations
# import seaborn as sns
# import base64
# from io import BytesIO

# matplotlib.use('Agg')

# NOMINAL_NOMINAL_ASSOC = 'theil'

# def calc_correlations(df: pd.DataFrame, columns: List[str]) -> Dict:
#     """
#     Calculate correlations between columns in a DataFrame.

#     Parameters:
#         - df (pd.DataFrame): The input DataFrame.
#         - columns (List[str]): List of column names for which correlations are calculated.

#     Returns:
#         - Dict: A dictionary containing correlation scores.
#     """
#     try:
#         # Categorical-categorical correlations are computed using theil,
#         # Numerical-numerical correlations are computed using pearson.
#         complete_correlation = associations(df[columns], nom_nom_assoc=NOMINAL_NOMINAL_ASSOC, plot=False)
        
#         correlation_dict = {}
#         for col1 in complete_correlation['corr'].columns:
#             for col2 in complete_correlation['corr'].columns:
#                 if col1 != col2:
#                     key = f"{col1} vs {col2}"
#                     correlation_dict[key] = complete_correlation['corr'].loc[col1, col2]

#         # Create a correlation matrix heatmap
#         plt.figure(figsize=(8, 8))
#         sns.heatmap(complete_correlation['corr'], annot=True, cmap='coolwarm', fmt='.2f')
#         plt.title('Correlation Matrix')

#         plt.xticks(rotation=45, fontsize=8)
#         plt.yticks(rotation=0, fontsize=8)

#         plt.tight_layout()
        
#         # Save the plot to a BytesIO object
#         image_stream = BytesIO()
#         plt.savefig(image_stream, format='png')
#         plt.close()

        
#         # Convert the plot to base64
#         base64_image = base64.b64encode(image_stream.getvalue()).decode('utf-8')

#         # Close the BytesIO stream
#         image_stream.close()

#         return {"Correlation Scores": correlation_dict, "Correlation Matrix":base64_image}
#     except Exception as e:
#         return {"Message": f"error, {str(e)}"}


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
    """
    Calculate correlations between columns in a DataFrame.

    Parameters:
        - df (pd.DataFrame): The input DataFrame.
        - columns (List[str]): List of column names for which correlations are calculated.

    Returns:
        - Dict: A dictionary containing correlation scores, a combined plot, and individual plots.
    """
    try:
        # Separate categorical and numerical columns
        categorical_columns = df[columns].select_dtypes(include='object').columns
        numerical_columns = df[columns].select_dtypes(exclude='object').columns


        # Categorical-categorical correlations are computed using theil
        categorical_correlation = associations(df[categorical_columns], nom_nom_assoc=NOMINAL_NOMINAL_ASSOC, plot=False)

        # Numerical-numerical correlations are computed using pearson
        numerical_correlation = df[numerical_columns].corr()

        # Create a subplot with 1 row and 2 columns
        fig, axes = plt.subplots(2, 1, figsize=(8, 8))

        # Plot for categorical-categorical correlations
        cax1 = sns.heatmap(categorical_correlation['corr'], annot=True, cmap='coolwarm', fmt='.2f', ax=axes[0])
        axes[0].set_title('Categorical-Categorical Correlation Matrix')
        axes[0].tick_params(axis='x', rotation=45, labelsize=8)
        axes[0].tick_params(axis='y', rotation=0, labelsize=8)
        # axes[0].set_aspect('equal') 

        # Plot for numerical-numerical correlations
        cax2 = sns.heatmap(numerical_correlation, annot=True, cmap='coolwarm', fmt='.2f', ax=axes[1])
        axes[1].set_title('Numerical-Numerical Correlation Matrix')
        axes[1].tick_params(axis='x', rotation=45, labelsize=8)
        axes[1].tick_params(axis='y', rotation=0, labelsize=8)
        # axes[1].set_aspect('equal') 

        # fig.colorbar(cax1.get_children()[0], ax=axes, orientation='horizontal', label='Correlation')


        # Adjust layout for better spacing
        plt.tight_layout()

        # Save the combined plot to a BytesIO object
        combined_image_stream = BytesIO()
        plt.savefig(combined_image_stream, format='png')
        plt.close()

        # Convert the combined plot to base64
        base64_combined_image = base64.b64encode(combined_image_stream.getvalue()).decode('utf-8')

        # Close the BytesIO stream
        combined_image_stream.close()

        # Create and return a dictionary with correlation scores and plots
        correlation_dict = {}
        for col1 in categorical_correlation['corr'].columns:
            for col2 in categorical_correlation['corr'].columns:
                if col1 != col2:
                    key = f"{col1} vs {col2}"
                    correlation_dict[key] = categorical_correlation['corr'].loc[col1, col2]

        for col1 in numerical_correlation.columns:
            for col2 in numerical_correlation.columns:
                if col1 != col2:
                    key = f"{col1} vs {col2}"
                    correlation_dict[key] = numerical_correlation.loc[col1, col2]

        return {
            "Correlation Scores": correlation_dict,
            "Correlation Matrix": base64_combined_image
        }
    except Exception as e:
        return {"Message": f"error, {str(e)}"}
