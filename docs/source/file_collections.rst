.. _file_collections:

File Collections (Pilot)
========================

Select an explicit, ordered list of files and analyze each independently or
stack their rows into one logical table. This pilot is shared by the web UI,
CLI, Python API and MCP. It does not depend on the multi-file upload PR.

The initial supported metrics are grouped time series, completeness, duplicity,
and outliers. Other metric names are rejected before input loading. Support for
a metric on a single file does not imply support for collections.

Selection and modes
-------------------

Each member has a unique string ``id``, a ``path``, and optional display
``name`` and ``file_type``. IDs distinguish files even when names repeat. Only
listed members are read, in the specified order; directories are not searched.
All member reads use the existing ``read_file()`` readers. This pilot requires
non-empty, unambiguous tables with unique string column names. Custom loaders,
HDF5/Zarr key selection and remote execution are not yet collection adapters.

* **independent**: one assessment per selected file. An unreadable member is an
  explicit error and does not prevent other members from being assessed. Files
  may have different schemas; each metric's parameters apply to every member.
* **stacked**: one assessment of all selected rows. Every member must load, with
  identical column names and parsed dtypes. Columns are aligned to the first
  member's order. Schema or loading failures stop the assessment before metrics
  run; a failed member is never silently omitted. Strict dtype matching avoids
  implicit conversions that could round large integer time ticks. It does not
  verify physical units or semantic compatibility; confirm these before stacking.

Neither mode sorts, joins, resamples, repairs or modifies source data. Stacking
is performed in memory without writing a combined data file. Independent mode
loads one member at a time; stacked mode requires memory for the selected tables,
their combined table, and metric input copies. Choose bounded selections. The
ordinary parser cache policy still applies to member reads; set
``AIDRIN_FRAME_CACHE=0`` to avoid cache sidecars beside the inputs.

Provenance and sequence boundaries
----------------------------------

Each assessment returns ``sources`` with member ID, display name, zero-based
``start_row`` in the metric input and ``row_count``. The original parsed row
position is the metric row position minus that member's ``start_row``. Sources
occupy contiguous blocks in selected order. Display names need not be unique.

Provenance stays outside measurement columns. In particular, unique source-row
values must not make duplicate rows appear distinct or inflate completeness.
Each metric request can explicitly opt in to ``source_columns``:

* ``__aidrin_source_id``: member ID for each row.
* ``__aidrin_source_row``: zero-based parsed row position within its member.

These names are reserved and cannot already occur in a member's data. Source
columns are exposed only to the requesting metric. For grouped time series,
request ``__aidrin_source_id`` and include it in ``group_columns`` to retain
file boundaries. To deliberately continue matching groups across files, omit
it from grouping. The audit then compares adjacent samples across the boundary
in selected order. This is an explicit scientific choice, not an alignment or
synchronization check. The web form keeps file boundaries by default.

CLI and Python
--------------

The committed example selects two entirely synthetic component files:

.. code-block:: bash

   AIDRIN_FRAME_CACHE=0 aidrin collection examples/grouped_time_series/collection.json

The JSON config contains ``files``, ``mode`` and ``metrics``. Each metric request
contains ``name``, optional ``parameters`` and optional ``source_columns``. Paths
in this config are relative to the config file, not the working directory. H1
has five samples; H2 has three and reports count and duration mismatches. The
duplicity metric runs on the same stacked measurements without source columns.
Change ``mode`` to ``independent`` to assess each component separately.

.. code-block:: python

   from aidrin.file_handling.collection import load_collection_config
   from aidrin.headless import run_collection_metrics

   config = load_collection_config("examples/grouped_time_series/collection.json")
   result = run_collection_metrics(**config)

Callers can also pass member dictionaries directly to ``run_collection_metrics``;
those paths resolve against the caller's working directory. Metric requests and
output structure are the same across adapters. No new dependencies are required.

Results use ``format: aidrin.collection-assessment`` and ``version: 1``. They
include the ordered ``selection``, ``mode``, ``datasets`` and a summary. Each
dataset has ``sources``, metric results under ``metrics``, and execution errors
under ``errors``. Its status is ``ok``, ``partial`` or ``error``. A successful
sequence audit can contain findings: execution status is not a readiness verdict.
Grouped-time-series result precision is preserved. Assessments print JSON;
invalid configurations and stacked-input failures are reported on stderr. The
CLI exits nonzero on execution/input errors, including partial independent
runs; metric findings alone do not produce a nonzero exit.

Web and MCP
-----------

Open **File collection** from the workspace navigation. Upload table files,
select a subset, adjust file order with the arrows, choose the analysis mode
and checks, and run. The page displays separate dataset results and source-row
mappings and can download the complete JSON result. Uploads use session-owned
opaque IDs; browser requests cannot submit server filesystem paths. Existing
single-file workspace settings are not changed. Collections use the existing
upload lifetime. **Clear collection uploads** removes this collection's copies
without changing the single-file workspace; clearing the whole session also
removes them.

The local MCP tools are ``list_collection_metrics`` and ``run_file_collection``.
The latter accepts ``files``, ``metrics`` and ``mode`` with the same structure
as the Python API. Paths must already be visible on the MCP server. This tool
does not upload files or connect to a remote endpoint.

Extending the pilot
-------------------

Collection execution has no per-metric dispatch branches. Existing runners are
reused synchronously through ``read_file()`` with request-local table inputs;
each read receives a private copy. Provenance handling and source mapping are
also metric-independent. Plotting is sequential because Matplotlib is not
thread-safe.

To support another tabular metric, verify that its runner consumes a parsed
table without depending on original file paths or native metadata, add the
supported ``collection_modes`` to its registry entry, and test realistic
independent/stacked behavior and provenance policy. That makes it discoverable
by the executor and MCP catalogue. Web parameter controls remain an adapter
responsibility. Native metadata, units, file references and custom-code metrics
need an explicit collection contract before opting in. The pilot has no
cross-file joins, automatic unit conversion or cross-sequence alignment.
