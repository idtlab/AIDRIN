# How to contribute to AIDRIN development (last updated on Sep 5th, 2026)

Welcome! AIDRIN, the AI Data Readiness Infrastructure, measures how ready a dataset is for AI and
machine learning work and helps fix the problems it finds. It is developed in the The Ohio State University with collaborators at Lawrence Berkeley National
Laboratory and Argonne National Laboratory. Contributions of every size are welcome, from a typo in the documentation to a new readiness metric.

> **Important**
> No contribution can be accepted unless the contributor agrees to the terms in `LICENSE.txt` in the
> top source directory. Please also read the [Code of Conduct](CODE_OF_CONDUCT.md) before taking part.

This file is the working reference for people writing code. The published documentation at
<https://aidrin.readthedocs.io> covers installation and use, and `AGENTS.md` carries the same
conventions in condensed form for AI coding assistants.

## Table of contents

- [Getting started](#getting-started)
- [Prerequisites](#prerequisites)
- [Getting the source code](#getting-the-source-code)
- [Setting up a development environment](#setting-up-a-development-environment)
- [Running AIDRIN while you work](#running-aidrin-while-you-work)
- [Repository layout](#repository-layout)
- [Development conventions](#development-conventions)
- [Contributing changes](#contributing-changes)
- [Testing](#testing)
- [Lint and format](#lint-and-format)
- [Documentation](#documentation)
- [The four interfaces](#the-four-interfaces)
- [Checklist for contributors](#checklist-for-contributors)
- [Getting help](#getting-help)
- [Citing AIDRIN](#citing-aidrin)

---

## Getting started

One engine computes the readiness metrics, and four interfaces expose it. These are a Flask web
application, a headless `aidrin` command line tool, an importable Python library, and an MCP server
for agentic clients. A change to the engine usually has to surface in all four, so read the engine
sections below before the interface sections.

Two rules matter more than the rest. Verify before you claim, which means every command, flag,
metric name, and code example you add has to run against the real code. And keep the gates green,
which means tests, lint, and the wheel build pass locally before you push.

---

## Prerequisites

### Required

- **Python 3.10 through 3.13.** CI tests all four versions on Linux, macOS, and Windows.
- **Git** for version control. If you are new to GitHub, the
  [GitHub tutorial](https://guides.github.com/activities/hello-world/) takes about ten minutes.
- **`uv` or `pip`.** `uv` is the preferred toolchain and `uv.lock` is committed. Plain `pip` works.

### Recommended

- **`pre-commit`** for whitespace, codespell, and YAML and JSON checks before each commit.
- **`flake8`** for Python lint. Its configuration lives in `tox.ini`, with a maximum line length of 150.
- **Node with `npx`** to run Prettier over the CSS and JavaScript in `web/static/`.

### Needed only for some work

- **Redis** for the web application and the Celery worker. The command line tool and the entire test
  suite run without a broker.
- **An LLM API key** for the agentic pipeline and the optional explanation feature. `OPENAI_API_KEY`,
  or `GOOGLE_API_KEY` for Gemini embeddings.
- **Optional extras** declared in `pyproject.toml`: `agentic`, `mcp`, `globus`, `telemetry`,
  `mlflow`, `llm`, and `zarr`. Zarr needs Python 3.11 or newer.

---

## Getting the source code

```bash
git clone https://github.com/idtlab/AIDRIN.git
cd AIDRIN
```

The default branch is `develop`. Branch from it and target your pull requests at it. `main` holds
released versions. Code ownership for the whole tree is `@idtlab/aidrin`.

---

## Setting up a development environment

```bash
uv sync --group dev
# or
pip install -e ".[dev]"
```

Either command installs the runtime dependencies plus `pytest`, `pytest-cov`, and `flake8`. Add an
optional group when your work touches that feature.

```bash
uv sync --group agentic
# or
pip install -e ".[agentic]"
```

| Extra | What it adds |
| --- | --- |
| `agentic` | LLM and RAG pipeline that generates analysis code and data transformations |
| `mcp` | MCP server that exposes the metrics and agentic tools to MCP clients |
| `globus` | Dispatch of metric calls to a remote Globus Compute endpoint |
| `telemetry` | OpenTelemetry instrumentation for the Flask app |
| `mlflow` | Assessment tracking through `mlflow-skinny` |
| `llm` | Natural language explanations of metric results in the web interface |
| `docs` | Sphinx and the Read the Docs theme for building documentation |

---

## Running AIDRIN while you work

### Web application, which needs Redis

```bash
redis-server --port 6379
PYTHONPATH=. celery -A worker.make_celery worker --beat --loglevel=info   # Windows: add --pool=solo
flask --app 'web:create_app()' run --debug                                # http://127.0.0.1:5000
```

### Command line, which needs no broker

```bash
aidrin list                                  # list metrics
aidrin list --category data-quality          # one category
aidrin data-quality data.csv                 # completeness, duplicity, outliers
aidrin run completeness data.csv             # a single metric
aidrin run class-imbalance data.csv income   # metric plus required column
aidrin batch config.yaml                     # several metrics from a YAML or JSON config
aidrin add-custom-module my_audit --dir ./   # scaffold a custom metric or remedy
```

Three details catch people out. `aidrin run` accepts only the dash-separated spelling, so
`aidrin run class_imbalance` fails with `invalid choice` while the shortcut form without `run`
accepts either. Metric arguments are positional in the order shown by `aidrin run <metric> -h`,
except the completeness family, which takes named flags. Failures surface in the JSON output, so do
not read the exit code alone.

### MCP server

```bash
pip install -e ".[mcp]"
aidrin-mcp        # speaks over stdio
```

### Agentic pipeline

```bash
aidrin agentic build-index -c config.yaml
aidrin agentic run -c config.yaml -o results.json
```

Sample configurations live in `examples/agentic/`.

---

## Repository layout

Three cooperating Python packages plus the web assets.

- **`aidrin/`**: the metrics engine, importable on its own.
  - **`structured_data_metrics/`**: one module per metric, each a Celery `@shared_task` function.
  - **`file_handling/`**: `file_parser.py` with `read_file()`, plus format `readers/` for CSV, Excel,
    JSON, Parquet, HDF5, NPZ, Zarr, and ROOT. Every dataset read funnels through `read_file()`.
  - **`headless/`**: the `aidrin` CLI in `cli.py`, the programmatic API in `api.py`, and `runners.py`,
    which invokes the metric tasks synchronously with no Celery broker.
  - **`agentic/`**: the optional LLM and RAG pipeline built on LangChain and FAISS.
  - **`compute/`**: remote execution through Globus Compute.
  - **`mcp/`**: the MCP server.
  - **`custom_metrics/`**: user-supplied metric and remedy scripts named `customDR_*.py`, generated at
    runtime, ignored by Git, and excluded from lint.
- **`web/`**: the Flask app built by the factory `web:create_app()`, with blueprints in `routes/`,
  Jinja templates in `templates/`, and assets in `static/`.
- **`worker/`**: Celery wiring. `make_celery.py` builds the app and `tasks.py` holds scheduled tasks.
- **`tests/unit/`** for metric and logic tests with no Flask or Celery, and **`tests/integration/`**
  for Flask routes and uploads, where Celery runs eagerly.
- **`docs/`**: Sphinx sources. **`demos/`**: runnable demo configs and datasets.
  **`examples/`**: sample data and agentic configs. **`docker/`**: local and NERSC images.

---

## Development conventions

### Where a new metric belongs

AIDRIN organizes data readiness into seven areas. Six of them stand beside each other. The seventh,
readiness for a specific AI application, cuts across the rest, because what counts as ready depends
on the model and the science question. Before you write a metric, decide which area it serves. That
decision determines the CLI category, the web dimension, and the part of the documentation you have
to update.

| Readiness area | What it covers | Where it lives in the code |
| --- | --- | --- |
| Data quality | Completeness, duplicates, outliers, validity rules | `completeness.py`, `row_level_completeness.py`, `temporal_completeness.py`, `feature_coverage_ratio.py`, `null_count_trend.py`, `duplicity.py`, `duplicity_by_features.py`, `outliers.py`, `custom_outliers.py` |
| Understandability and usability | FAIRness of the metadata against DCAT and DataCite | `FAIRness_dcat.py`, `FAIRness_datacite.py` |
| Fairness and representativeness | Class imbalance, representation rates, statistical parity, demographic disparity | `class_imbalance.py`, `representation_rate.py`, `compare_representation_rate.py`, `statistical_rate.py`, `conditional_demo_disp.py` |
| Structure and organization | Constant features, collinearity, distribution shape | `constant_feature_count.py`, `max_pairwise_correlation.py`, `skewness.py`, `kurtosis.py` |
| Importance of data features | Correlation and how strongly each feature relates to the target | `correlation_score.py`, `feature_relevance.py` |
| Governance, ethics, security, and privacy | Re-identification risk, HIPAA identifiers, differential privacy | `privacy_measure.py`, `hipaa_compliance.py`, `add_noise.py` |
| Requirements of a specific AI application | Annotations, labels, expected distributions, domain rules | `aidrin/custom_metrics/`, through user-written scripts and remedies |

The third column names the main modules in each area rather than every file. Note also that the
groupings do not yet line up across interfaces. `aidrin list --category` exposes five categories, the
web interface groups six dimensions, and the FAIR metrics behind understandability run only in the
web interface today. Closing those gaps is welcome work. If your metric fits none of the seven areas,
open an issue and discuss it before writing code, since a new area changes the report layout and the
scoring.

### Adding a metric

1. Write one module per metric in `aidrin/structured_data_metrics/`, exposed as a Celery
   `@shared_task` function.
2. Read the dataset through `read_file()`. A reader improvement then benefits every metric at once.
3. Return values that are JSON serializable. The result keys are what users read programmatically.
4. Register the metric in the relevant `web/routes/` blueprint and in the headless API and registry
   so that the web interface, the CLI, the library, and MCP all see it.
5. Cover the logic with a test in `tests/unit/`.
6. Add the metric to `docs/source/metric_names.rst`. `tests/unit/test_docs_metric_names.py` compares
   the documentation with the code, so a missing entry fails CI.

Naming follows the interface. The library uses underscores and a `calculate_` prefix, or `compute_`
for the privacy metrics. The command line uses dash-separated names. The web interface uses title
case display labels. `cli.py` derives its subparsers by replacing underscores with hyphens, so the
two spellings stay in step as long as you register the metric once.

### Code style

- Follow PEP 8. `flake8` enforces it with a maximum line length of 150 and the exclusions in
  `tox.ini`.
- Run Prettier over CSS and JavaScript you touch. The repository is Prettier clean, so a failure
  comes from your edit.
- Document with docstrings. Level one is mandatory and covers the summary, parameters, return value,
  exceptions, and any TODOs. Level two is optional and covers algorithms, data structures, and logic
  that is hard to follow.
- Keep diffs surgical. Touch only what the task needs, match the surrounding style, and do not
  reformat untouched code.

### Commit messages

Write a plain, human, present-tense subject line. No "Generated with" footers, no AI co-author
trailers, no robot emoji. Avoid em dashes in commit messages and in anything a user will read.

### Things that bite

- Correlations use `dython.associations`, which is pandas only and quadratic in the number of
  columns. `dython` needs `pkg_resources`, which is why `pyproject.toml` pins `setuptools`.
- Matplotlib runs on the non-interactive `Agg` backend and is not thread safe. Do not generate plots
  from concurrent threads, since several metric calls at once in one process will contend.
- Boolean columns count as categorical in the Data Overview summary.
- `aidrin run custom <PATH>` should preserve the case of the path. Lowercase names are safest on
  case-sensitive filesystems.
- Custom metrics, the agentic executor, and the MCP tools run user-generated or LLM-generated Python
  locally. Treat all three as a code execution surface and point them only at trusted inputs.

---

## Contributing changes

### Workflow

1. **Open a GitHub issue.** Every change starts with an issue. Use the right template for a bug
   report, feature request, install problem, or question, and label it.
2. **Fork the repository and branch off `develop`.** Do not create branches in the main repository
   without discussing it first.
3. **Make your change.** Follow the conventions above, add tests, and update the documentation.
4. **Run the gates locally.** See the pre-commit checklist below.
5. **Open a pull request against `develop`** using the default template, and link the issue.
6. **Work through review.** `develop` needs one approval and `main` needs two. Squash and merge is
   the default. Long-lived feature branches such as `cli-integration` stay in sync with merge rather
   than rebase.

### Acceptance criteria

- **Clear purpose.** The pull request links an issue and says what problem it solves and who
  benefits.
- **Tests.** New behavior and bug fixes come with tests. Never weaken, skip, or delete a test to make
  a change pass. Fix the cause.
- **Green CI.** Tests on Python 3.10 through 3.13 across Linux, macOS, and Windows, `flake8`,
  Prettier, and the wheel build all pass.
- **A stable output contract.** Metric result keys are public API. Renaming a key, removing one, or
  changing what an existing key means is a breaking change. Document it in `CHANGELOG.md` under
  `Changed (breaking)` with the old behavior, the new behavior, the reason, and a small before and
  after example. The column-wise redefinition of `Overall Completeness` is the model to follow.
- **Optional dependencies stay optional.** Guard imports so that a missing extra hides the feature
  instead of breaking the application, the way `web/llm.py` does.
- **Evidence for performance claims.** If a change is made for speed or memory, report the machine,
  the dataset shape, and the measurement rather than the direction of the change alone. A number
  without its platform and data size cannot be reproduced or defended in review.
- **Documentation.** New features and any public API change come with documentation updates.

---

## Testing

`PYTHONPATH=.` lets Python find the `aidrin`, `web`, and `worker` packages.

```bash
PYTHONPATH=. pytest tests/                    # everything
PYTHONPATH=. pytest tests/unit/ -v            # metric and logic tests
PYTHONPATH=. pytest tests/integration/ -v     # Flask routes, eager Celery
PYTHONPATH=. pytest tests/unit/test_privacy.py -v
```

With coverage, the way CI runs it:

```bash
PYTHONPATH=. pytest tests/unit/ tests/integration/ -v \
  --cov=aidrin --cov=web --cov=worker --cov-report=term-missing
```

Both suites run offline. Neither needs Redis, a Celery broker, or a running server, because the unit
tests exercise the library directly and the integration tests build their own Flask app with Celery
in eager mode. A plain `.[dev]` install skips the tests whose optional dependencies are absent,
notably the agentic and HDF5 suites, so install the extras you want to exercise.

---

## Lint and format

```bash
flake8 --config=tox.ini aidrin/ web/ worker/
npx --yes prettier@3 --check web/static/css web/static/js
pre-commit run --all-files
```

`prettier --write` fixes formatting, but let it touch only the lines you changed.

### Pre-commit checklist

Run these three before every commit.

```bash
PYTHONPATH=. pytest tests/                                   # green
flake8 --config=tox.ini aidrin/ web/ worker/                 # zero issues
npx --yes prettier@3 --check web/static/css web/static/js    # only if you touched JS, CSS, or HTML
```

---

## Documentation

Sphinx sources live in `docs/source/` and publish to Read the Docs. Build locally with
`pip install -e ".[docs]"` followed by `make html` from the `docs/` directory.

Which page you update depends on what you changed. A web-facing metric goes in `web_usage.rst`, a
command line change in `cli_usage.rst`, a library change in `python_api.rst`, and a new metric always
goes in `metric_names.rst`, which CI checks against the code. New test suites belong in
`testing.rst`, and known gaps belong in `limitations.rst`.

### Changelog entries

`CHANGELOG.md` loosely follows [Keep a Changelog](https://keepachangelog.com/). Add an entry under
`Unreleased` for user-visible changes in behavior, new metrics and interfaces, and fixes to reported
issues. Internal refactors, comments, and CI adjustments do not need one.

Write a breaking entry as a short story rather than a line item. State what changed, why the old
behavior was wrong, what a consumer of the affected keys will now see, and a worked example small
enough to check by hand.

---

## The four interfaces

| Interface | Entry point | Notes |
| --- | --- | --- |
| Web application | `web:create_app()` | Needs Redis and a Celery worker. Blueprints in `web/routes/`. |
| Command line | `aidrin` from `aidrin.headless.cli:main` | Runs metrics synchronously with no broker. |
| Python library | `import aidrin` | `calculate_*` and `compute_*` functions over the same engine. |
| MCP server | `aidrin-mcp` from `aidrin.mcp.server:main` | Speaks stdio and dispatches on the CLI registry. |

A metric that reaches only one of the four is incomplete unless there is a reason it cannot reach the
others, as with the FAIR metrics today. Say which reason applies in the pull request.

---

## Checklist for contributors

### Code

- [ ] A GitHub issue exists and the pull request links it.
- [ ] The change follows the conventions above, including the 150 character line limit.
- [ ] Dataset reads go through `read_file()`.
- [ ] Metric results are JSON serializable.
- [ ] New or changed metrics are registered for the web interface, the CLI, the library, and MCP.
- [ ] Optional imports are guarded so a missing extra hides the feature rather than breaking the app.

### Documentation

- [ ] `docs/source/metric_names.rst` lists any new metric.
- [ ] The matching usage page is updated for the interfaces you touched.
- [ ] `CHANGELOG.md` describes user-visible changes, with breaking changes spelled out in full.
- [ ] Docstrings cover the summary, parameters, return value, and exceptions.

### Testing

- [ ] Unit tests cover the new logic and integration tests cover new routes.
- [ ] The full suite passes locally on your Python version.
- [ ] No existing test was weakened, skipped, or deleted to make the change pass.
- [ ] Performance-motivated changes report the machine, dataset shape, and measurement.

## AI Tool Usage

How much of this PR was AI-assisted? (check one)

- [ ] **0** - No AI at any point
- [ ] **1** - AI helped me think, but I wrote all the code myself
- [ ] **2** - I planned the change and decided the approach; AI helped write the code
- [ ] **3** - AI planned and wrote it; I checked and approved each step as it went
- [ ] **4** - I set the AI going and left it to it; I reviewed the finished result
- [ ] **5** - I set the AI going and left it to it; nobody has read the result - no review, or AI review only

If an AI agent is filling this in: declare the level honestly, and open as a draft if it is 5. Do not lower the declared level to get the PR reviewed.

**If level 1 or above:**

- Tool(s) used:
- What was generated:
- What you reviewed and changed:


## Alternative Approaches Considered

Did you consider other approaches? Why this one?

## Review Guide

How should a reviewer test this? Anything to watch for?

## Checklist

- [ ] I have read the Contributing Guide
- [ ] PR is focused and small
- [ ] Tests are included or updated
- [ ] I understand all code in this PR and can answer questions about it
- [ ] No secrets, credentials, or sensitive data are included
- [ ] Commit messages are descriptive
- [ ] Related docs and screenshots are updated

---

## Getting help

Open a [GitHub issue](https://github.com/idtlab/AIDRIN/issues) for bugs, feature requests, install
problems, and questions, using the matching template. The published documentation at
<https://aidrin.readthedocs.io> covers installation, usage, the Python API, and the metric name
mapping. `AGENTS.md` is the fastest orientation to the repository itself.

Maintainers are listed in `pyproject.toml` and `AUTHORS.txt`. If you are unsure whether an idea fits
AIDRIN, open an issue and ask before writing code. Early discussion saves rework, especially for a
new readiness area or a change to metric output.

---

## Citing AIDRIN

If AIDRIN supports work you publish, cite it using the metadata in `CITATION.cff`. The archived
software has DOI [10.5281/zenodo.21798062](https://doi.org/10.5281/zenodo.21798062).

Thank you for contributing to AIDRIN. Better tools for judging whether data is ready for AI make the
science built on that data easier to trust.
