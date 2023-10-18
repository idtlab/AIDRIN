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
        - Dict: A dictionary containing correlation scores.
    """
    try:
        # Categorical-categorical correlations are computed using theil,
        # Numerical-numerical correlations are computed using pearson.
        complete_correlation = associations(df[columns], nom_nom_assoc=NOMINAL_NOMINAL_ASSOC, plot=False)
        
        correlation_dict = {}
        for col1 in complete_correlation['corr'].columns:
            for col2 in complete_correlation['corr'].columns:
                if col1 != col2:
                    key = f"{col1} vs {col2}"
                    correlation_dict[key] = complete_correlation['corr'].loc[col1, col2]

        # Create a correlation matrix heatmap
        plt.figure(figsize=(8, 6))
        sns.heatmap(complete_correlation['corr'], annot=True, cmap='coolwarm', fmt='.2f')
        plt.title('Correlation Matrix')
        
        # Save the plot to a BytesIO object
        image_stream = BytesIO()
        plt.savefig(image_stream, format='png')
        plt.close()

        # Convert the plot to base64
        base64_image = base64.b64encode(image_stream.getvalue()).decode('utf-8')


        return {"Correlation Scores": correlation_dict, "Correlation Matrix":base64_image}
    except Exception as e:
        return {"Message": f"error, {str(e)}"}
