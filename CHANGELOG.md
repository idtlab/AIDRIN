# Changelog

All notable changes to AIDRIN are documented here. This project loosely follows
[Keep a Changelog](https://keepachangelog.com/) conventions.

## [Unreleased]

### Changed (breaking)

- **Completeness — `Overall Completeness` is now column-wise.** The
  `completeness` metric's `Overall Completeness` value changed from a *row-wise*
  score (the fraction of rows with no missing value in any column) to a
  *column-wise* score (the mean of the per-column non-missing rates, equivalently
  `1 - df.isnull().mean().mean()`).

  **Why:** the row-wise definition counted a row as incomplete if *any* single
  cell was missing, so the score collapsed toward `0` on wide datasets even when
  every column was individually near-complete — misleading for the per-column
  scores the metric reports. The column-wise definition is the mean of those
  per-column scores and degrades gracefully.

  **Impact:** any consumer reading `result["Overall Completeness"]` will see a
  different (generally higher) number when missing values are scattered across
  columns. The two are equal only when the dataset is fully complete or when
  every missing cell falls in the same rows.

  Example — two columns each 50% complete, missing in *different* rows:
  - before (row-wise): `0.0`
  - after (column-wise): `0.5`

  The interim keys `Overall Completeness (row-wise)` and
  `Overall Completeness (column-wise)` (present briefly on this branch) were
  removed in favor of the single `Overall Completeness` key.

### Added

- **New data-quality completeness metrics** (CLI, Python library, batch, MCP,
  Globus, and web UI):
  - `row_level_completeness` — % of rows whose *required* columns are all
    non-null (param: `required_columns`).
  - `feature_coverage_ratio` — % of features whose non-null rate meets a
    threshold (param: `threshold`, default `0.9`).
  - `temporal_completeness` — % of expected time intervals present (params:
    `timestamp_column`, `frequency` default `"D"`). Computes present/expected
    counts arithmetically (grid-flooring for fixed offsets, period bucketing for
    anchored offsets like `W`/`ME`/`QE`/`YE`) rather than materializing the full
    interval set — correct for anchored frequencies and safe for fine ones
    (`s`/`ms`/… no longer hang on long spans).
  - `null_count_trend` — null counts grouped by a batch column, to spot quality
    regressions (params: `batch_column`, optional `target_columns`).
  - `duplicity_by_features` — duplicate rows computed using only selected
    feature columns, with counts, percentage, and the largest duplicate groups
    (param: `duplicate_columns`).

- **New "Data Structure" pillar** (CLI, Python library, batch, MCP, Globus, and
  web UI), under a new `data-structure` category with a matching web panel:
  - `constant_feature_count` — count of columns with a single distinct
    value, along with each constant column's value (no params). Null is
    treated as a value like any other, so an all-null column counts as
    constant.
  - `max_pairwise_correlation` — strongest absolute pairwise (Pearson)
    correlation between features, flagging redundant/collinear columns; returns
    the max, the most-correlated pair, the top pairs, and a heatmap.
  - `skewness` — per-feature skewness (distribution asymmetry) with a bar chart.
  - `kurtosis` — per-feature excess kurtosis (Fisher's definition; tail
    heaviness) with a bar chart.

  All four are available in the web UI under the "Data Structure" sidebar tab.
  `max_pairwise_correlation`, `skewness`, and `kurtosis` operate on the
  numeric, non-constant columns.

- **`-o`/`--output` on `run`, `batch`, `data-quality`, and `summarize`.**
  Previously only `agentic run` could write its JSON report to a file; the
  other commands only wrote to stdout, so a report path had to come from a
  shell redirect (`aidrin data-quality f.csv --detail > audit/pre.json`) —
  invisible to any tool that records the command line, and therefore not a
  recorded output of the run. `-o`/`--output` writes the same result to disk
  (creating parent directories as needed) while still printing to stdout,
  with the same semantics as `agentic run -o`.

- **`aidrin inventory <file>`** classifies an HDF5/Zarr file's on-disk layout
  (`empty` / `single_dataset` / `multi_dataset` / `legacy`) and lists its
  datasets/arrays, without reading the file as a table. Useful before trusting
  `data-quality`/`run`/`summarize` on a structured file whose datasets might
  not actually represent one table (e.g. simulation fields on a mesh that
  happen to share a length). `run`, `data-quality`, and `summarize` now also
  refuse (non-zero exit, naming the layout and pointing at `aidrin inventory`)
  instead of silently flattening an HDF5 file classified `multi_dataset` when
  no `--selected-keys` was given — previously only Zarr refused this way; HDF5
  returned an empty result silently.

### Fixed

- **Datasets with array-valued columns no longer break the summary or
  duplicity.** Object columns holding arrays/lists/dicts — routine in parquet,
  HDF5 and JSON (e.g. a per-node measurement array) — are unhashable, and
  `nunique()` / `value_counts()` / `duplicated()` all hash. This raised
  `TypeError: unhashable type: 'numpy.ndarray'`, which surfaced as a failed web
  summary ("An internal error occurred") and made the `duplicity` metric — and
  therefore the whole `aidrin data-quality` bundle — unusable on such files.

  Normalization now lives in a shared helper,
  `aidrin/file_handling/hashable_utils.py` (`make_hashable`, `hashable_series`,
  `hashable_frame`, `safe_nunique`), used by both the duplicity metric and the
  web summary route. Values are converted to nested tuples, which preserves
  equality so distinct-counting and duplicate detection stay correct.
  `duplicity._make_hashable` remains as an alias for backwards compatibility.

- **`differential-privacy`'s noisy CSV write is now visible and controllable.**
  `add_laplace_noise`/`return_noisy_stats` wrote `noisy/noisy_data.csv`
  relative to the process's working directory on every run, with no CLI
  option and no mention of the path in the result — silent for any tool that
  only records the command. The result now always includes the resolved
  `"Noisy file path"` when a file is written, and `aidrin run
  differential-privacy` gained `--noisy-output <path>` (write there instead)
  and `--no-noisy-output` (skip the write). The library default
  (`save_output=True`, writing to `./noisy/noisy_data.csv`) is unchanged for
  existing callers.

- **The agent skill's metrics index no longer contradicts its own
  reference entry.** `reference/metrics.md` listed `differential-privacy` as
  "(currently unavailable)" in the category index while documenting its full
  syntax and a working example further down — an agent that only read the
  index would skip a metric the CLI actually runs.
