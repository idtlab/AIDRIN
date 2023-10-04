import pandas as pd
import numpy as np
import shap
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error

def calc_shapely(df,cat_cols,num_cols,target_col):

    final_dict = {}
    
    df = df.dropna()

    data = pd.concat([df[num_cols], pd.get_dummies(df[cat_cols])], axis=1)
    target = pd.get_dummies(df[target_col]).astype(float)

    data = data.astype(float)

    # Split the dataset into train and test sets
    X_train, X_test, y_train, y_test = train_test_split(data, target, test_size=0.2, random_state=0)

    model = RandomForestRegressor(n_estimators=100, random_state=0)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    rmse = np.sqrt(mean_squared_error(y_test, y_pred))

    # Create an explainer for the model
    explainer = shap.Explainer(model, X_test)
    
    # Calculate Shapley values for a single instance (e.g., the first test sample)
    shap_values = explainer.shap_values(X_test.iloc[0])

    mean_abs_shap_values = np.abs(shap_values).mean(axis=0)
    top_3_feature_indices = mean_abs_shap_values.argsort()[-3:][::-1]
    top_3_features = X_test.columns[top_3_feature_indices]

    final_dict["RMSE"] = rmse
    final_dict["Top 3 features"] = top_3_features.to_list()
    
    return final_dict

