# Agentic pipeline and remote datasets

Two optional capabilities, each needing setup the user must have done already.

Read this when the user asked for domain grounding against their own literature
(the agentic pipeline), or when preflight reported a configured Globus Compute
endpoint and the dataset may live there. Neither is needed for an ordinary
local assessment.

## Contents

- Agentic pipeline — LLM + RAG over the user's documents, including the config schema
- Remote datasets (Globus Compute) — running metrics where the data already is

## Agentic pipeline (advanced)

Steps 2 and 8 of the main workflow already offer this automatically once the user
gives a resource path and domain questions — this section is the schema/command
reference those steps point to. It's also useful standalone: re-running with a
different config, or driving the pipeline outside the guided workflow.

For domain-specific dataset evaluation grounded in field literature. Use when the
user has domain PDFs (research papers, standards, regulations) and wants to evaluate
whether the dataset meets domain-specific requirements — not just generic quality
checks. Requires `pip install 'aidrin[agentic]'` and an API key for one provider —
OpenRouter (`OPENROUTER_API_KEY`) or LBL CBORG (`CBORG_API_KEY`). Pick one; the
pipeline does not mix providers within a run.

**How domain specificity works:** You define domain-specific questions in the config
(`retrieval.question` / `retrieval.questions`). The pipeline embeds those questions,
retrieves the most relevant passages from the indexed domain PDFs, and feeds both the
retrieved context and the dataset profile to an LLM that generates analysis code. That
code is executed against the actual dataset (with a self-healing repair loop on failure).
The questions are where you inject domain knowledge — e.g. "Does more than 80% of the
data conform to IEC smart-meter resampling standards?" or "Which EU regulation requires
profiling consequences to be disclosed?"

**Pipeline stages:** profile → (build index if needed) → retrieve → execute/self-heal → score complexity → recommend remediation

### Config structure

The pipeline is entirely config-driven. Create a YAML file with these sections:

```yaml
llm:
  base_url: "https://openrouter.ai/api/v1"   # or "https://api.cborg.lbl.gov" — pick one, never both
  model: "openai/gpt-oss-120b"                # chat backend, reused by executor/complexity_scorer/remediation below
  embedding_model: "openai/text-embedding-3-large"  # used by build-index and by retrieval's query embedding

paths:
  data_loader: "./loader.py:load_dataset"  # Python function returning a DataFrame
  # OR: data_csv: "./data/mydata.csv"      # for plain CSV
  metadata_csv: "./data/metadata.txt"      # free-text domain description (required)

vector_store:
  sources:
    - ./sources                            # directory of domain PDFs
  vector_store_name: my_index             # output directory name
  chunk_size: 1000
  chunk_overlap: 200

retrieval:
  enabled: true                           # false = skip RAG, use LLM knowledge only
  top_k: 3
  max_workers: 4                          # questions run in parallel
  question: "Single question as a string"
  # OR for multiple:
  # questions:
  #   - "First domain question"
  #   - "Second domain question"

executor:
  enabled: true
  max_attempts: 5                         # self-heal retries
  timeout_seconds: 60                     # wall-clock limit per execution attempt
  temperature: 0.0

complexity_scorer:
  enabled: true

remediation:
  enabled: true
```

Nothing is written to disk by `agentic_run`/`aidrin agentic run` unless you pass
an output path (MCP's `output_path` / CLI's `-o`).

The API key is never written into the config — it's resolved from `llm.base_url`
(`OPENROUTER_API_KEY` for OpenRouter, `CBORG_API_KEY` for CBORG), or an explicit
`llm.api_key` if you need to override that inference.

`paths.data_loader` is required for non-CSV datasets. It points to a Python file and
function (`"./loader.py:load_dataset"`) that returns a pandas DataFrame.

When `retrieval.enabled: false`, the pipeline generates code from LLM knowledge and
the data profile alone — no PDFs or vector store needed.

### Running

**MCP:**
1. `agentic_build_index(config_path="/abs/path/config.yaml")` — index domain PDFs into FAISS (run once; skip if index already exists).
2. `agentic_run(config_path="/abs/path/config.yaml", output_path="results.json")` — runs the full pipeline. Set `skip_vector=True` only if you already built the index in a prior call.

**CLI:**
```bash
aidrin agentic build-index -c path/to/config.yaml
aidrin agentic run -c path/to/config.yaml -o path/to/results.json [--skip-vector]
```

Returns combined JSON: `profile` + `queries` (one entry per question: retrieval, execution, complexity, remediation) + `token_usage`.

## Remote datasets (Globus Compute)

When the dataset lives on a remote machine (HPC scratch, a lab server) that runs
a Globus Compute endpoint, AIDRIN can execute the metrics there and return only
the results. The data never moves.

**MCP:** pass `profile="<name>"` (or `endpoint="<uuid>"`) to `summarize_dataset`,
`run_data_quality_check`, `run_aidrin_metric`, or `run_batch`.

**CLI:** prefix the command with `remote`, for example
`aidrin remote summarize /scratch/proj/data.csv`. The arguments and the JSON are
identical to a local run, so steps 4 through 9 of the workflow are unchanged.

What differs:

- **Paths are remote.** `file_path` is a path on the endpoint's filesystem. You
  cannot list it, so ask the user for the full path. A wrong path comes back as
  a metric error, not as a local file-not-found. For `run_batch`/`aidrin remote
  batch`, this applies only to the `file_path` *inside* the config — the config
  file itself is read from wherever it sits (locally for the CLI, on the MCP
  server's machine for `run_batch`).
- **Local-only:** custom metrics, remedies, and the agentic pipeline. They need
  files or credentials on this machine. Say so plainly rather than retrying.
- **Setup:** if no profile is configured, the user runs
  `aidrin remote configure --name <name> --endpoint <uuid>` once. Do not run
  this for them: it needs an endpoint UUID only they have.
- **Version skew:** the endpoint may run an older AIDRIN. If a metric that
  `list_metrics()` reports fails remotely with an unknown-metric error, that is
  the likely cause; report it rather than working around it.
