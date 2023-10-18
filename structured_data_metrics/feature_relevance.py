import pandas as pd
import numpy as np
import shap
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error

def calc_shapley(df, cat_cols, num_cols, target_col):
    """
    Calculate Shapley values and other metrics for a predictive model.

    Parameters:
        - df (pd.DataFrame): The input DataFrame.
        - cat_cols (list): List of categorical column names.
        - num_cols (list): List of numerical column names.
        - target_col (str): The target column name.

    Returns:
        - dict: A dictionary containing RMSE and top 3 features based on Shapley values.
    """
    final_dict = {}

    try:
        # Drop rows with missing values
        df = df.dropna()

        # Check if cat_cols and num_cols are not empty
        if not cat_cols or not num_cols:
            raise ValueError("cat_cols and num_cols must not be empty.")

        # Check if specified columns are present in the DataFrame
        if not set(cat_cols).issubset(df.columns) or not set(num_cols).issubset(df.columns):
            raise ValueError("Specified columns not found in the DataFrame.")

        # Convert categorical columns to dummy variables
        data = pd.get_dummies(df[cat_cols], drop_first=True)
        data = pd.concat([df[num_cols], data], axis=1)

        # Convert target column to numerical
        target = pd.get_dummies(df[target_col]).astype(float)

        data = data.astype(float)

        # Split the dataset into train and test sets
        X_train, X_test, y_train, y_test = train_test_split(data, target, test_size=0.2, random_state=0)

        # Create a regressor model
        model = RandomForestRegressor(n_estimators=100, random_state=0)
        model.fit(X_train, y_train)

        # Make predictions
        y_pred = model.predict(X_test)

        # Calculate RMSE
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))

        # Create an explainer for the model
        explainer = shap.Explainer(model, X_test)

        # Calculate Shapley values for a single instance (e.g., the first test sample)
        shap_values = explainer.shap_values(X_test.iloc[0])

        # Get feature importance based on mean absolute Shapley values
        mean_abs_shap_values = np.abs(shap_values).mean(axis=0)
        top_3_feature_indices = mean_abs_shap_values.argsort()[-3:][::-1]
        top_3_features = X_test.columns[top_3_feature_indices]

        final_dict["RMSE"] = rmse
        final_dict["Top 3 features"] = top_3_features.to_list()

    except Exception as e:
        final_dict["Error"] = f"An error occurred: {str(e)}"

    return final_dict
