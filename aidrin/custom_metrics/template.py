"""Canonical starter template for a CustomDR module.

The web Custom Metrics panel (web/routes/custom.py) and the CLI/MCP
scaffolding commands (aidrin/headless/api.py::generate_metric_template, used
by `aidrin add-custom-module` and the MCP `create_custom_metric` tool) both
generate this same starter file. It is defined once here so the two call
sites can't drift out of sync with each other.
"""

CUSTOM_DR_TEMPLATE = '''from aidrin.custom_metrics.base_dr import BaseDRAgent
from typing import Any
import pandas as pd

class CustomDR(BaseDRAgent):
    def __init__(self, dataset: Any, **kwargs):
        super().__init__(dataset, **kwargs)

    def metric(self, **kwargs):
        """
        Implement your custom metric logic here.
        """

        # IMPLEMENT YOUR METRIC LOGIC BELOW
        # Example: Calculating the total number of missing cells in the entire DataFrame

        # df: pd.DataFrame = self.dataset
        # return {
        #     "total_missing_cells": df.isna().sum().to_dict()
        # }

        return {"message": "Placeholder metric. Implement your logic here."}

    def remedy(self, **kwargs) -> pd.DataFrame:
        """
        Applies custom remediation logic based on the calculated metrics.
        Access metric results via kwargs.get("metric_results", {}).
        """

        # IMPLEMENT YOUR REMEDIATION LOGIC BELOW
        # metric_results = kwargs.get("metric_results", {})
        # For example, filling null values with a default value

        # df_remedied: pd.DataFrame = self.dataset.copy()
        # df_remedied.fillna(0, inplace=True)
        # return df_remedied

        return self.dataset
'''
