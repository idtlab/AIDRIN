# File collections

## Choose files and mode

Use the files the user named. If the request gives a directory and a rule such
as "all CSV files", list the matching paths before running. Ask which files to
use if the selection is unclear. Give each file a unique, stable ID and keep
the requested order.

- Use `independent` to get a result for each file and compare those results.
- Use `stacked` when the metric should see one table, such as when looking for
  duplicates across files. AIDRIN appends rows in file order. The column names
  and parsed data types must match. Keep the original data types and row order.

Ask which mode the user wants if the request could mean either a per-file
comparison or a combined result. Run metrics separately when they need
different files or modes.

Use nonempty local tables with unique column names and a built-in reader.
Custom loaders, selection of an HDF5 or Zarr dataset, and remote execution
require a separate workflow. Stacking holds both the input tables and the
combined table in memory.

## Check metric support

With MCP, call `list_collection_metrics()` to check each metric's modes and
arguments. Call `run_file_collection` when the MCP server can read the selected
paths. If either tool is missing or the server cannot read the files, use the
CLI on a host that can read them. Get approval for any separate file transfer.

On the CLI, check `aidrin collection --help` and `aidrin list --capabilities`.
Completeness, duplicity, and outliers support both modes. Use the Grouped Time
Series instructions below if the catalogue includes `grouped-time-series`.

For metrics that take column names, check each file with `summarize_dataset`
or `aidrin summarize`. If a metric lacks collection support, explain the
limit. Use single-file calls if the user wants per-file results. Follow the
main skill's column-role confirmation step for fairness or privacy checks.

## Run the collection

In `files`, give each entry an `id` and a `path`. The optional `name` sets the
display label. Set `file_type` to override format detection. In `metrics`, give
each entry a `name` and any `parameters` it needs. List each metric once. Supply
`source_columns` only for metrics that support them. Completeness, duplicity,
and outliers use only the original table columns.

For the CLI example, save this JSON as `collection.json`. Resolve relative
paths from the directory containing that file.

```json
{
  "files": [
    {"id": "january", "path": "stations-january.csv"},
    {"id": "march", "path": "stations-march.csv"}
  ],
  "mode": "independent",
  "metrics": [
    {"name": "completeness"},
    {"name": "duplicity"},
    {"name": "outliers"}
  ]
}
```

```bash
aidrin collection collection.json -o results.json
```

For MCP, pass `files`, `metrics`, and `mode` to `run_file_collection`. Use
absolute paths on the MCP server host. The tool takes these three arguments
and returns the result as JSON.

## Grouped Time Series

Confirm the timestamp column, units, expected spacing, and series identifiers
against the user's description or trusted metadata. Set `timestamp_column`
and `expected_cadence` in `parameters`. Use the column's units for numeric
time and seconds for datetimes. Set `time_kind` to `numeric` or `datetime`
when the format needs to be explicit.

Use `group_columns` when a file contains multiple series. Omit it for one
series per file. Set `tolerance`, `expected_count`, or `expected_duration`
when those expectations are known. Use `max_findings` to cap the detail
records per series. The totals still include every finding.

This request checks each station and component at an expected cadence of
0.01 seconds in `elapsed_s`.

```json
{
  "name": "grouped_time_series",
  "parameters": {
    "group_columns": ["station", "component"],
    "timestamp_column": "elapsed_s",
    "time_kind": "numeric",
    "expected_cadence": 0.01
  }
}
```

In `stacked` mode, omit `source_columns` to keep series from different files
separate. For a series that continues across files, verify the file order
and set `"source_columns": []` on this metric request. AIDRIN checks timestamps
in input order. To assess synchronization between recordings, verify absolute
start times or another shared timing reference.

## Interpret and report

- Give the files, mode, and metrics used. Report independent scores by file
  ID. For stacked scores, use the returned combined result and keep its
  source mapping.
- Read `summary.datasets_with_errors` and each dataset's `status` and
  `errors`. Keep successful results and identify failed files or metrics.
  The CLI exits nonzero on a partial run and still returns the results it
  has. If stacking fails because a file is unreadable or the schemas differ,
  report the error and check with the user before changing the files or mode.
- To trace a stacked row back to its file, use `start_row` and `row_count`.
  Row positions in the JSON start at zero. Keep exact timestamps and
  undefined scores (`null`) in the raw results. For a timing finding, give
  the expected spacing and units along with the observed values.
- Save the raw JSON alongside any requested report. Describe the findings
  and failures. Leave the readiness decision to the user.
