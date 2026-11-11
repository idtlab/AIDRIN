.. _file_collections:

File Collections
================

Use the Inspector to upload one or more files. **Auto-detect from filename**
allows different supported formats in the same upload. Use **Upload more
files** to add to the workspace. The top-bar file switcher opens the selected
file's Data Overview and makes it the input for ordinary single-file checks.
Use **Batch Overview** to see counts and sizes, open a file, or remove it
from the workspace. Removing the active file opens the first remaining
available file. **New session** clears the workspace. Uploaded files are
eligible for cleanup after one hour. The file list expires after an hour
of workspace inactivity.

For Globus Compute, enter an endpoint ID and a directory path and select
**Import directory**. A compatible AIDRIN worker lists and summarizes supported
files immediately inside that directory. The workspace stores remote references.
Open an imported file to run supported single-file metrics on its endpoint.
Removing a remote reference leaves the file on the endpoint. The workspace
limit defaults to 50 files and is configurable with
``AIDRIN_MAX_UPLOAD_FILES``.

Cross-file Data Quality
-----------------------

In **Data Quality**, select column-level completeness, duplicity, or outliers.
**Files to check** defaults to **Active file only**. Choose all uploaded local
files or select a subset to check across files. Other checks on the same form
use the active file.

* **Analyze each file independently** applies the selected checks to each file.
  An unreadable file is reported separately.
* **Stack rows into one dataset** checks the combined rows, in the selected
  order. Every file must load with the same column names and parsed dtypes.
  For duplicity, this includes duplicates that appear across source files.
  For outliers, the thresholds use the combined data.

The Results panel shows per-file or combined scores and errors. The JSON
download includes file identities and the mapping from stacked rows to input
files. Stacking uses memory for the selected tables and the combined table.

Grouped Time Series
-------------------

When Grouped Time Series is the only selected collection check, the form
initially selects all uploaded local files. If you select it alongside another
collection check, the same file selection and analysis mode apply to both.
A single collection run reads the files and shows the sequence findings and
other scores in separate results cards.

In stacked mode, **One series per file** retains the source boundaries.
When you identify series by columns, choose **Continue matching series across
files** to compare adjacent samples across sources in the selected order.
See :ref:`grouped_time_series` for timing detection and result interpretation.

CLI, Python and MCP
-------------------

A stacked Grouped Time Series request keeps file boundaries by default. To
continue matching series across files in selection order, explicitly pass
``"source_columns": []`` in that metric request and provide its grouping
columns if the files contain multiple series.

The same execution layer accepts a list of file members, a mode, and metric
requests. Each member has an ``id``, ``path``, optional display ``name``, and
optional ``file_type``. Use ``aidrin collection <config.json>`` with a JSON object
containing ``files``, ``mode`` and ``metrics``. Relative paths resolve against
the config file's directory. Python callers can pass the same inputs to
``aidrin.headless.run_collection_metrics``. MCP provides
``list_collection_metrics`` and ``run_file_collection``, using files already
accessible to the MCP server.

Metrics opt in via the headless registry's ``collection_modes`` contract. Each
metric receives a private copy of its input table through the existing reader.
An assessment returns ordered ``selection``, ``datasets``, and ``summary``.
Source positions use zero-based offsets in the parsed table. Metrics that
need source metadata can advertise support for reserved source columns.
Completeness, duplicity, and outliers use only measurement columns. Undefined
scores are represented as JSON ``null``. Collection reads can reuse existing
frame caches and leave source directories unchanged.

Collection analysis currently accepts local tables from built-in readers.
Custom-loader inputs, native HDF5/Zarr dataset selection, and remote collection
execution require separate adapters. CLI execution and input errors exit
nonzero, including partial independent runs.
