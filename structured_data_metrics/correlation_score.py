import matplotlib
matplotlib.use('Agg')

from dython.nominal import associations

def calc_correlations(df,columns):
    try:
        #categorical-categorical correlations are computed using theil
        #numerical-numerical correlations are computed using pearson
        
        complete_correlation= associations(df[columns],nom_nom_assoc='theil',plot=False)
        correlation_dict = {}
        for col1 in complete_correlation['corr'].columns:
            for col2 in complete_correlation['corr'].columns:
                if col1 != col2:
                    key = f"{col1} vs {col2}"
                    correlation_dict[key] = complete_correlation['corr'].loc[col1, col2]
        return {"Correlation Scores":correlation_dict}
    except Exception as e:
        return {"Message":"error, check column names"}
    