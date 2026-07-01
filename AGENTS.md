# AGENTS.md

Guidance for anyone (human or AI) working in the **AIDRIN** repository. Read this before making
changes. Full docs: https://aidrin.readthedocs.io.

**AIDRIN** (AI Data Readiness Infrastructure) helps teams both **assess and improve** how ready a dataset
is for AI/ML workflows. It runs quantitative readiness metrics across **data quality** (completeness,
duplicity, outliers), **fairness/bias** (class imbalance, representation and statistical rates,
demographic disparity), **privacy** (k-anonymity, l-diversity, t-closeness, entropy and attribute
risk, HIPAA identifiers, differential privacy), and **data governance / FAIRness**. It goes beyond
assessment in two ways: it is **extensible with custom metrics and remedies** (user scripts that both
score a dataset and apply fixes/transformations to it), and it ships an optional **agentic** pipeline
that uses LLMs + RAG to **generate analysis code and data transformations** for a dataset. The same
engine is exposed through several interfaces: a Flask web app, a headless `aidrin` CLI, a Python
library, and the agentic pipeline.

## Golden rules

1. **Verify before you claim.** Every command, flag, metric name, and code example you add (here, in
   docs, or in the UI) must actually work against the real code. Run it. Never invent APIs.
2. **Keep the gates green.** CI runs tests (`pytest`, Python 3.10-3.13), `flake8`, Prettier, and a
   wheel `build` on every push/PR. Run them locally first (see the checklist below). Do not weaken or
   delete a test to make a change pass: fix the cause.
3. **Surgical changes.** Touch only what the task needs; match the surrounding style. Max line length
   is 150.
4. **Default branch is `develop`.** Branch off it and target PRs at it. CODEOWNERS is `@idtlab/aidrin`.

## Project layout

Three cooperating Python packages plus the web assets:

- `aidrin/` — the metrics engine (importable on its own).
  - `structured_data_metrics/` — one module per metric (Celery `@shared_task` functions:
    completeness, class_imbalance, privacy_measure, correlation_score, hipaa_compliance, ...).
  - `file_handling/` — `file_parser.py::read_file()` plus format `readers/` (CSV, Parquet, Excel,
    JSON, HDF5, NPZ). **All dataset reads funnel through `read_file()`.**
  - `headless/` — the `aidrin` CLI (`cli.py`), the programmatic API (`api.py`), and `runners.py`
    that invoke the metric tasks synchronously (no Celery broker required).
  - `agentic/` — optional LLM + RAG pipeline that generates analysis code and data transformations
    (OpenAI/Gemini via LangChain + FAISS).
  - `custom_metrics/` — user-uploaded metric/remedy scripts (`customDR_*.py`); generated at runtime,
    git-ignored, excluded from lint.
- `web/` — Flask app via the factory `web:create_app()`.
  - `routes/` blueprints (`core`, `metrics`, `custom`, `admin`, `globus`, `llm`), `templates/`
    (Jinja), `static/` (CSS/JS). Optional integrations: `globus.py`, `llm.py`, `telemetry.py`.
- `worker/` — Celery wiring. `make_celery.py` builds the app; `tasks.py` holds scheduled tasks.
  Requires a running Redis broker.
- `tests/unit/` (pure metric/logic, no Flask/Celery), `tests/integration/` (Flask routes, uploads;
  Celery runs in eager mode, so **no Redis needed**). Docs in `docs/` (Sphinx).

## Setup

`uv` is the preferred toolchain (`uv.lock` is committed); plain pip also works. Python **3.10-3.13**.

```bash
uv sync --group dev               # runtime + dev/test tools
# or:
pip install -e ".[dev]"
```

Optional extras (declared in `pyproject.toml`): `agentic` (LLM/RAG), `globus`, `telemetry`, `llm`.
Install e.g. `uv sync --group agentic` or `pip install -e ".[agentic]"`.

## Running

### Web app (needs Redis)
```bash
redis-server --port 6379
PYTHONPATH=. celery -A worker.make_celery worker --beat --loglevel=info   # Windows: add --pool=solo
flask --app 'web:create_app()' run --debug                                # http://127.0.0.1:5000
```

### CLI (no Redis)
```bash
aidrin list                                  # list metrics
aidrin data-quality data.csv                 # fast completeness/duplicity/outliers
aidrin run completeness data.csv             # single metric (arguments are POSITIONAL, not flags)
aidrin run class_imbalance data.csv income   # metric + required column(s)
aidrin batch config.yaml                      # multiple metrics from a YAML/JSON config
aidrin add-custom-module my_audit --dir ./    # scaffold a custom metric/remedy
```
Library/CLI metric keys are lowercase with underscores (`class_imbalance`). Run failures surface in
the JSON output; do not rely on the exit code alone.

### Agentic pipeline (optional)
Needs `[agentic]` installed and an LLM key (`OPENAI_API_KEY`, or `GOOGLE_API_KEY` for Gemini
embeddings). Driven by a YAML config (see `examples/agentic/`):
`aidrin agentic build-index -c config.yaml` then `aidrin agentic run -c config.yaml -o results.json`.

### MCP server (on the `aidrin-mcp` branch, not yet on develop)
`pip install -e '.[mcp]'` then run `aidrin-mcp` (stdio). Exposes the metrics/agentic tools to MCP
clients. The custom-metric and agentic tools execute code: only point them at trusted inputs.

## Testing

`PYTHONPATH=.` is required so the local packages resolve.

```bash
PYTHONPATH=. pytest tests/                              # full suite
PYTHONPATH=. pytest tests/unit/ -v                      # pure unit
PYTHONPATH=. pytest tests/integration/ -v               # eager Celery, no Redis
# With coverage (as CI does):
PYTHONPATH=. pytest tests/unit/ tests/integration/ -v --cov=aidrin --cov=web --cov=worker --cov-report=term-missing
```
Single test: `PYTHONPATH=. pytest tests/unit/test_privacy.py -v`.

## Lint & format

```bash
flake8 --config=tox.ini aidrin/ web/ worker/        # flake8 config in tox.ini, max-line-length 150
npx --yes prettier@3 --check web/static/css web/static/js   # frontend formatting
pre-commit run --all-files                           # whitespace, codespell, yaml/json, etc.
```
The repo's JS/CSS is Prettier-clean, so a Prettier failure means your edit. Run `prettier --write`
but only let it touch lines you changed; do not reformat the whole file.

## Pre-commit checklist (run before every commit)

```bash
PYTHONPATH=. pytest tests/                            # green
flake8 --config=tox.ini aidrin/ web/ worker/         # 0 issues
npx --yes prettier@3 --check web/static/css web/static/js   # only if you touched JS/CSS/HTML
```

## Conventions

- **Adding a metric:** new module in `aidrin/structured_data_metrics/`, wire it into the relevant
  `web/routes/` blueprint and the headless API/registry, and cover the logic with a `tests/unit/`
  test. Public API changes need a docs update and tests (see `.github/pull_request_template.md`).
- **Branching/merging:** branch off `develop`; prefer **squash-merge**. `cli-integration` and similar
  long-lived feature branches use merge (not rebase) to stay in sync.
- **Commit style:** plain, human, present-tense subject. No "Generated with..." footers, no AI
  co-author trailers, no robot emoji. Avoid em dashes in commit messages and user-facing copy.

## Don't

- Don't weaken, skip, or delete tests to make a change pass.
- Don't show unverified CLI/library/API examples (verify against the real code first).
- Don't reformat untouched code; keep diffs surgical.

## Gotchas

- Correlations use `dython.associations` (pandas-only, O(cols^2)); `dython` needs `pkg_resources`,
  hence the `setuptools<81` pin. `shap` can be slow to resolve on some Python versions.
- Matplotlib uses the non-interactive `Agg` backend and is **not thread-safe**: do not generate plots
  from concurrent threads (e.g. several metric calls at once in one process will serialize/contend).
- Boolean columns are treated as **categorical** in the Data Overview summary.
- `aidrin run custom <PATH>` should preserve path case; lowercase-only names are safest on
  case-sensitive (Linux) filesystems.
- Custom metrics and the agentic executor **run user/LLM-generated Python locally**. Only run trusted
  inputs; treat this as a code-execution surface (relevant for the CLI, web custom metrics, and MCP).
