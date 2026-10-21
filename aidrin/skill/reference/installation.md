# Installing & verifying AIDRIN

## Preferred invocation

**MCP (preferred):** If the `list_metrics` tool is available, use MCP tools directly — no PATH or shell setup required. See the skill's Tool path table.

**CLI (fallback):** Prefer the `aidrin` console script. If it is not on PATH, use
`python -m aidrin.headless.cli` with the same arguments. Decide once and use
consistently.

If you are using the `uv`-managed environment shipped with this repo (see
[uv path](#uv-path) below), use `uv run aidrin` instead.

## Install

### Standard (Python >= 3.10 required)

From the AIDRIN repository root:

    pip install -e '.[mcp]'

> **Note:** Python 3.9 (macOS system default) is not supported. Use Python
> 3.10 or later.

### uv path

The repo ships a `uv.lock`. If you have [uv](https://github.com/astral-sh/uv)
installed, you can create a ready-to-use Python 3.13 environment without
touching your system Python:

    uv sync --group mcp

## Verify (capability check — also the skill's Step 1 preflight)

    aidrin list
    # or, with uv:
    uv run aidrin list

Expected: JSON of available metrics grouped by category. This list is the
source of truth for which metrics exist. If a metric you intend to run is not
in this output, do not run it — offer to scaffold it as a custom metric instead.

## Agentic dependencies

The `agentic_build_index` and `agentic_run` MCP tools need extra dependencies
and an API key:

    pip install 'aidrin[agentic]'
    export OPENAI_API_KEY="sk-..."

Use when the user asks for literature-grounded analysis or remediation
recommendations.

---

## Setting up AIDRIN with Claude Code (MCP + skill)

This section is for users who want Claude Code to drive AIDRIN assessments
directly — asking questions like "is my dataset AI-ready?" and having Claude
run the metrics, interpret the results, and write a report.

### How it works

AIDRIN ships two things that plug into Claude Code:

- **MCP server** (`aidrin-mcp`) — exposes AIDRIN's metrics as tools that Claude
  can call directly, without you writing any commands.
- **Skill** (`.claude/skills/aidrin/`) — tells Claude *how*
  to use those tools: what workflow to follow, which metrics to run for which
  intent, how to interpret results, and how to write the report.

Claude Code reads `.mcp.json` from your project root to connect the MCP server,
and picks up the skill automatically when the AIDRIN repo is your working directory.

### Step 1 — Install AIDRIN

The `aidrin-mcp` server requires the `[mcp]` extra — a bare `pip install -e .`
installs the console script but the `mcp` package itself is absent, so
`aidrin-mcp` will crash with `ModuleNotFoundError` at runtime.

Use one of:

    pip install -e '.[mcp]'     # pip path
    uv sync --group mcp         # uv path

Verify:

    which aidrin-mcp   # prints the script path; confirms it is on PATH

### Step 2 — Open the AIDRIN repo in Claude Code

The repo already contains `.mcp.json` at the root:

```json
{
  "mcpServers": {
    "aidrin": {
      "type": "stdio",
      "command": "aidrin-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

When you open this directory in Claude Code (CLI, desktop app, or IDE extension),
Claude Code automatically starts the `aidrin-mcp` server and makes its tools
available. No manual configuration needed.

> **Using a different project directory?** Copy `.mcp.json` and the
> `.claude/skills/aidrin/` folder into that project's root.
> Claude Code will pick both up on next launch.

### Step 3 — Verify the MCP connection

Start a Claude Code session in the AIDRIN directory and ask:

> "List the available AIDRIN metrics."

Claude should call `list_metrics()` and return the full metric catalogue. If it
falls back to the CLI instead, the MCP server didn't connect — check that
`aidrin-mcp` is on your PATH (run `which aidrin-mcp` in a terminal).

### Step 4 — Assess a dataset

Point Claude at your data file:

> "Is my dataset at `/path/to/data.csv` ready for training a classifier?"

Claude will follow the skill's workflow: inspect the schema, propose a metric
plan, ask you to confirm column roles, run the metrics, and write an interpreted
markdown report.

Supported formats: CSV, Excel (`.xls`/`.xlsx`/`.xlsb`/`.xlsm`), JSON, NumPy
(`.npz`), HDF5 (`.h5`), Parquet.

### Step 5 (optional) — Agentic pipeline

For literature-grounded evaluation against domain papers and standards:

1. Install extra dependencies:

       pip install 'aidrin[agentic]'

2. Set your API key:

       export OPENAI_API_KEY="sk-..."   # or any OpenAI-compatible key

3. Create an agentic config YAML (see the skill's *Agentic pipeline* section for
   the full config structure), then tell Claude:

   > "Run an agentic evaluation using my config at `/path/to/config.yaml`."

   Claude will call `agentic_build_index` (once, to index your PDFs) then
   `agentic_run` to execute the full pipeline.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `aidrin-mcp` not found | Run `pip install -e '.[mcp]'` from the AIDRIN root, or `uv sync --group mcp` |
| `aidrin-mcp` crashes with `ModuleNotFoundError` | The `mcp` package is missing — run `pip install -e '.[mcp]'` or `uv sync --group mcp` |
| Claude uses CLI instead of MCP tools | `.mcp.json` missing or server failed to start — run `which aidrin-mcp` to confirm the script is on PATH |
| `aidrin list` fails | See [Install](#install) — likely a missing dependency |
| Agentic run fails with credential error | Set `OPENAI_API_KEY` env var before launching Claude Code |
| Agentic run fails with `metadata_csv` error | Your config must include `paths.metadata_csv` pointing to a text description of the dataset |
