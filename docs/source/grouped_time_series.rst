.. _grouped_time_series:

Grouped Time Series
===================

Audit each sensor, subject, or simulation-run sequence independently. A table can
contain one sequence or use group columns to identify several. Checks retain the parsed input order:
AIDRIN never sorts, repairs, interpolates, or removes rows during this audit.
This complements temporal completeness, which measures datetime interval
coverage between observed endpoints rather than sequence ordering or cadence.

Motivation and synthetic example
--------------------------------

Parkfield observation preparation exposed horizontal components with different
sample counts (5119 versus 4607 at 0.01 seconds), missing absolute starts, and
small start offsets. This motivates independent sequence checks and explicit
count/duration expectations. It does not establish that any particular record
is scientifically usable. This feature has not been run against those real
records as part of its implementation.

The committed example is entirely synthetic and deliberately small. It contains
three sequences: S_A/H1 has five regular samples, S_A/H2 has three regular
samples, and S_B/H1 has a gap, a reversal, and a duplicate. Acceleration zeros
are ordinary valid values. Run from the repository root:

.. code-block:: bash

   aidrin run grouped-time-series examples/grouped_time_series/synthetic_sensors.csv \
     --group-columns station,component --timestamp-column elapsed_s \
     --expected-cadence 0.01 --tolerance 0.000001 \
     --expected-count 5 --expected-duration 0.04

Or use the same parameters in the batch example:

.. code-block:: bash

   aidrin batch examples/grouped_time_series/config.yaml

S_A/H1 has no findings. S_A/H2 reports count and duration mismatches despite
regular cadence. S_B/H1 reports an interval from row 8 to row 9 (0 to 0.02),
a reversal from row 9 to row 10, and a duplicate at row 11 referencing row 10,
as well as count/duration mismatches. Row positions start at zero after parsing
and exclude the CSV header. They are positions, not DataFrame index labels.

Python and datetime inputs
--------------------------

.. code-block:: python

   from aidrin import calculate_grouped_time_series

   result = calculate_grouped_time_series(
       ("examples/grouped_time_series/synthetic_sensors.csv", "synthetic_sensors.csv", ".csv"),
       group_columns=["station", "component"],
       timestamp_column="elapsed_s",
       expected_cadence=0.01,
       tolerance=0.000001,
       expected_count=5,
       expected_duration=0.04,
   )

The registry API accepts the same keyword arguments via
``run_metric("grouped_time_series", path, ...)``. The MCP
``run_aidrin_metric`` tool also accepts them. The web Data Quality form exposes
the same controls. Existing remote adapters require an AIDRIN worker containing
this feature; no endpoint installation or real remote execution is part of the
example.

Set ``time_kind="datetime"`` for datetime values or datetime strings. Cadence,
tolerance and expected duration then use seconds: for example,
``expected_cadence=0.01`` means ten milliseconds. Numeric time
(``time_kind="numeric"``, the default in Python) uses the input
unit. Numeric epochs are never silently interpreted as datetime nanoseconds.
Timezone-aware datetimes are compared as instants; timezone-naive and aware
values cannot be combined within a group. Datetime arithmetic preserves
nanosecond precision within pandas' nanosecond timestamp range. Numeric
integer ticks (including decimal integer strings) retain exact integer equality
and subtraction. Integer time endpoints, intervals, durations and estimated missing counts outside
the browser-safe range (absolute value greater than 2**53 - 1) are serialized as
decimal strings. Nonintegral numeric inputs use finite floating-point values;
keep elapsed origins near zero when checking very fine floating-point cadence.

Parameters
----------

* ``group_columns``: required non-empty list of distinct scalar-key columns,
  or a comma-separated string. The time column must be separate. With
  ``aidrin.calculate_grouped_time_series``, pass ``None`` to audit the entire
  table as one series.
* ``timestamp_column``: required time column in the parsed table.
* ``expected_cadence``: required finite positive interval.
* ``time_kind``: ``numeric``, ``datetime``, or ``auto`` in Python. Auto-detection
  uses the parsed column type or samples up to 256 values for numeric values and
  ISO-style dates. A sample with both formats requires an explicit choice.
  Rows incompatible with the detected format are reported during the audit.
  The web form defaults to auto-detection. Results record the format used.
* ``tolerance``: non-negative absolute interval tolerance, strictly less than
  half the cadence. Comparisons also allow relative floating-point roundoff of
  1e-9. The same tolerances apply to optional duration checks.
* ``expected_count``: optional positive expected row count, applied to every
  group, including rows whose time is invalid.
* ``expected_duration``: optional non-negative expected span, applied to every
  group. The observed span is maximum minus minimum valid time, including for
  disordered sequences; it is not an assurance of continuous coverage.
* ``max_findings``: maximum detail records per group, default 100; zero means
  unlimited. Also caps the separate unassigned-row detail list. All rows are
  checked and all finding counts remain complete regardless of detail caps.

Results and interpretation
--------------------------

Results are versioned machine-readable JSON (``format`` is
``aidrin.grouped-time-series``, ``version`` is 1). CLI stdout, JSON files, batch
results and web result caches retain sequence number precision rather than
applying the usual display rounding. Result fields include:

* ``parameters``: the explicit measurement configuration and row-position base.
* ``summary``: total rows, group count, groups with findings, unassigned rows,
  and full counts by finding kind. Finding kinds can overlap; their sum is
  not a count of unique bad rows.
* ``unassigned_row_positions`` and ``unassigned_rows_truncated``: rows with
  missing group keys. These rows are not pooled into an invented sequence.
* ``groups``: group identities, row/valid-time/unique-time counts, evaluated
  adjacent intervals, first/last valid time in input order, observed duration,
  time-reference metadata, finding counts, finding details and truncation flag.

Findings distinguish missing times (including NaN), nonfinite numeric times
(infinity), malformed times, mixed timezone awareness, duplicate times,
reversed intervals, shorter-than-expected intervals, longer-than-expected
intervals (``cadence_gap``), insufficient valid times, count/duration mismatches,
and numeric arithmetic overflow. A duplicate points to its first occurrence,
including non-adjacent duplicates. Intervals contain both endpoint times and
source row positions. Missing or invalid times break adjacency: no interval is
invented across an unknown time. A gap has an estimated missing-sample count
only when its endpoints match an integer multiple of the cadence within the
declared tolerance; otherwise this field is null. A detail cap may omit later
kinds from the preview; always consult full finding counts and truncation flags.
An empty table reports zero groups and is not proof of readiness.

Scope
-----

The input is a long-form table, one sample per row with group keys and time.
Existing AIDRIN readers and trusted custom loaders can provide it. Native
station-grouped waveform stores need a loader or an explicit long-form export;
this feature does not infer station/component or time metadata from arbitrary
HDF5 layouts. The audit reads the parsed table in memory; detail caps do not
limit parsing or scan memory.

Each group is assessed independently. Unequal component lengths are visible in
the result and can violate an explicit common count/duration expectation.
Cross-component alignment, offsets, absolute-start availability, orientation,
free-field classification and analysis eligibility are separate checks. Missing
absolute start time is never presented as proven synchronization. Entirely absent
groups and missing leading/trailing samples cannot be inferred without external
expectations; an internally regular but shortened group can otherwise have no
findings. Value/rate-of-change bounds, flatline detection and automatic repair
are outside this first version. No conclusion about scientific accuracy follows
from a clean sequence audit. MT period grids are spectral coordinates, not
sample timestamps, and should not use this cadence audit.

Separate component files and a pilot protocol
--------------------------------------------------

For a shared collection input that retains measurement columns and supports
independent or stacked analysis with other metrics, see :ref:`file_collections`.
The time-only example adapter below remains available for its explicit
record/station/component manifest.

The trusted example loader ``examples/grouped_time_series/multi_file_loader.py``
reads an explicit JSON manifest through the custom-loader interface. Each record
declares ``record_id``, ``station``, ``component``, ``path`` and
``timestamp_column`` as non-empty strings. Record IDs must be unique. Member
paths are relative to the manifest; ``file_type`` optionally overrides the path
extension for an existing AIDRIN reader. Each member must already expose a time
column in an unambiguous table. Missing, empty or ambiguous members fail the
load rather than silently disappearing from the inventory.

Run the entirely synthetic two-file control from the repository root:

.. code-block:: bash

   AIDRIN_FRAME_CACHE=0 aidrin run grouped-time-series \
     examples/grouped_time_series/multi_file_manifest.json \
     --loader examples/grouped_time_series/multi_file_loader.py:load \
     --group-columns record_id,station,component --timestamp-column time \
     --expected-cadence 0.01 --tolerance 0.000001 \
     --expected-count 5 --expected-duration 0.04

H1 has five samples and no findings. H2 starts at 0.01 and contains three
regular samples; it reports count and duration mismatches. The 0.01 difference
between component origins is visible in ``first_time`` but is not itself an
audit finding. A pair of equally long regular sequences with different origins
can both pass this audit. Neither result proves synchronization.

The loader projects time and identity only; amplitude values are not assessed.
It preserves manifest order and each member's parsed row order. Group by all
three identity columns so repeated station/component records remain separate.
Audit row positions refer to the concatenated projection; each record occupies
a contiguous block in manifest order. Its ``source_row_position`` column starts
at zero within the member. Disabling the ordinary frame cache in this example
avoids writing cache sidecars beside scientific inputs.

For a real Parkfield pilot, retain the original files and build a manifest with
verified station/component identities. Confirm cadence and units from source
metadata before setting expectations. Keep absolute-start availability,
orientation, free-field classification and intended-analysis membership in a
separate inventory; this loader does not infer them or generate missing time
axes. First run independent sequence checks, then compare component counts and
time origins against that inventory. Decide alignment or exclusion explicitly
before any truncation, resampling or waveform comparison. Preserve clean,
shortened and shifted controls alongside the real-data report. The supplied
controls are synthetic; a real Parkfield run remains pending.
