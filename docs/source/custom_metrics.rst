=========================================
Defining Custom Metrics and Remedies
=========================================

This guide explains how to define custom metrics and remediation logic for your uploaded CSV files
using the **CustomDR** class inside the CodeMirror editor. After uploading a dataset, you
will navigate you to a page where you can write Python code that
extends the platform’s data-review logic.

----------------------------------------------------
Workflow Overview for Creating Custom Metrics
----------------------------------------------------

1. Navigate to the file upload page at `https://127.0.0.1:5000/upload_file`. And upload a CSV file.

2. After upload, click the **Define Custom Metrics** button.
   You will be redirected to the custom metric editor page at `https://127.0.0.1:5000/customMetrics`.

3. On this page, a CodeMirror Python editor appears, preloaded with an editable example class
   ``CustomDR``. This class inherits from ``BaseDRAgent`` and contains two key methods:

   - ``metric()``: returns a dictionary of metric results
   - ``remedy()``: returns a modified dataset based on your remediation logic

4. Write or modify your code inside the editor.

5. Press **Save** to store your custom logic on the server (temporary, 1-hour expiration).

6. Press **Submit** to execute your ``metric()`` function, and optionally your ``remedy()`` function if you
   have checked the **Apply Remedy** box.

The platform will display:

- Your computed metric dictionary
- Any remediated dataset to download (if remedy is enabled)
- Any warnings or errors raised by your code

------------------------------------------
Understanding the ``CustomDR`` Base Class
------------------------------------------

Below is the template initially shown in CodeMirror:

.. code-block:: python

    from aidrin.custom_metrics.base_dr import BaseDRAgent
    from typing import Any
    from typing import Dict, Union, Any

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
            #   "total_missing_cells": df.isna().sum().to_dict()
            # }

            return {"message": "Placeholder metric. Implement your logic here."}

        def remedy(self, metric_results: dict):
            """
            Applies custom remediation logic based on the calculated metrics.
            """

            # IMPLEMENT YOUR REMEDIATION LOGIC BELOW
            # For example, filling null values with a default value

            # df_remedied: pd.DataFrame = self.dataset.copy()
            # df_remedied.fillna(0, inplace=True)
            # return df_remedied

            return self.dataset

The goal is to replace the placeholder logic with your own custom metric and remediation steps.

----------------------------------------------
Implementing ``metric()``: Requirements & Tips
----------------------------------------------

Your ``metric()`` method:

- Must return a **dictionary** whose keys are metric names and values are computed results.
- Receives the dataset through ``self.dataset``.
- May accept additional keyword arguments (depending on future UI extensions).
- Should not mutate the dataset; all transformations belong in ``remedy()``.

Example: Compute missing values, row count, and column datatypes.

.. code-block:: python

    def metric(self, **kwargs):
        df = self.dataset

        return {
            "row_count": len(df),
            "column_count": df.shape[1],
            "missing_values": df.isna().sum().to_dict(),
            "dtypes": df.dtypes.apply(lambda x: str(x)).to_dict(),
        }

----------------------------------------------
Implementing ``remedy()``: Requirements & Tips
----------------------------------------------

The ``remedy()`` method receives the ``metric_results`` dictionary returned by ``metric()``.
Use this method when you want to apply data-cleaning or transformation logic based on your computed metrics. Or, you can modify the dataset directly without relying on ``metric_results``.

You must return the updated dataset at the end of ``remedy()``.

--------------------------------------------------------
Full Practical Example: A Combined Metric + Remedy Class
--------------------------------------------------------

The example below shows both ``metric()`` and ``remedy()`` implemented in a realistic workflow.

.. code-block:: python

    from aidrin.custom_metrics.base_dr import BaseDRAgent
    import pandas as pd
    from typing import Dict, Union, Any

    class CustomDR(BaseDRAgent):
        """
        An agent focused on detecting and removing duplicate rows.
        """

        def __init__(self, dataset: Any, **kwargs):
            super().__init__(dataset, **kwargs)

        def metric(self, **kwargs) -> Dict[str, int]:
            """
            Calculates the total count of duplicate rows.
            """
            df: pd.DataFrame = self.dataset
            duplicate_rows_count: int = df.duplicated().sum()

            return {
                "duplicate_rows_total": duplicate_rows_count,
            }

        def remedy(self, metric_results: Dict[str, Any]) -> pd.DataFrame:
            """
            Removes duplicate rows using the calculated metric results.
            """
            # Create a copy for safe modification to prevent side effects on the original state.
            df_remedied: pd.DataFrame = self.dataset.copy()

            duplicate_count = metric_results.get("duplicate_rows_total", 0)

            if duplicate_count > 0:
                df_remedied.drop_duplicates(inplace=True)

            return df_remedied

-------------------------------------------
How the System Uses Your CustomDR Class
-------------------------------------------

When you click **Submit**:

1. Your code is dynamically loaded and executed in an isolated environment.
2. The system creates an instance of your ``CustomDR`` class.
3. The system calls your ``metric()`` method to compute metrics.
4. If **Apply Remedy** is checked , the system calls your ``remedy()`` method to get the modified dataset.
5. Metrics and (optionally) the remedied data preview are displayed on the results section of the page.

-------------------------------------------
Best Practices for Writing Custom Metrics
-------------------------------------------

- **Do not mutate the dataset inside ``metric()``.**
  All modifications belong in ``remedy()``.
- Work on a **copy** of ``self.dataset`` in ``remedy()`` to avoid side effects.
- Always return the modified dataset at the end of ``remedy()``.

-------------------------------------------
Data & Code Storage Rules
-------------------------------------------

- Your custom metric code is stored temporarily for **1 hour**.
- The (optional) remedied dataset is also stored for **1 hour**.
- After expiration, all artifacts are safely removed.
