.. _aidrin_skill:

AIDRIN Skill
=============

AIDRIN ships a `Model Context Protocol (MCP) <https://modelcontextprotocol.io>`_ server and a
Claude Code skill that together let Claude drive AIDRIN assessments on your behalf — running
metrics, interpreting results, and writing a readiness report — all from a plain-language request.

No commands to remember, no argument ordering to look up. Claude handles it.

----

How It Works
------------

Two components plug into Claude Code:

**MCP server** (``aidrin-mcp``)
   Exposes all AIDRIN metrics as tools that Claude can call directly. Claude sends named
   parameters; the server runs the metric and returns structured JSON. Image side-effects are
   suppressed by default, so only the JSON result comes back.

**Skill** (``.claude/skills/aidrin/``)
   Instructs Claude on the full assessment workflow: which metrics to run for which intent,
   what column roles to confirm before running privacy or fairness metrics, how to interpret
   scores, and how to format the report. The skill is read by Claude Code at session start when
   the AIDRIN directory is open.

Claude Code reads ``.mcp.json`` from the project root to start the MCP server automatically.
Both files ship with the AIDRIN repository — no extra configuration is required.

----

Prerequisites
-------------

- **Claude Code** installed (CLI, desktop app, or IDE extension). See the
  `Claude Code documentation <https://docs.anthropic.com/en/docs/claude-code>`_.
- **AIDRIN** installed in a Python 3.10+ environment with its conda/virtual environment
  activated. If you haven't done this yet, follow :ref:`cli_installation` first, then return here.

----

Setup
-----

Step 1 — Install AIDRIN with MCP support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Once your environment is active, add the ``[mcp]`` extra from the repository root:

.. code-block:: bash

   pip install -e '.[mcp]'

Or, with ``uv``:

.. code-block:: bash

   uv sync --group mcp

Verify the command is on your PATH before continuing:

.. code-block:: bash

   which aidrin-mcp   # should print a path inside your active environment

Custom criteria outlier rules can be supplied to ``run_custom_outlier_check``
or ``run_aidrin_metric`` as inline ``rules_json`` or as ``rules_file``. A
``rules_file`` path is read on the MCP server host and must point to a UTF-8
JSON array in the same format as ``examples/custom_outlier_rules.json``.
Set ``"target_match": "regex"`` on a rule to apply it to every target whose
complete column name or HDF5 dataset path matches ``target``.

Step 2 — Open the AIDRIN directory in Claude Code
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The repository already contains ``.mcp.json`` at the root:

.. code-block:: json

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

When you open this directory in Claude Code, the MCP server starts automatically and AIDRIN's
tools become available to Claude for that session.

.. note::

   **Using a different project directory?** Copy ``.mcp.json`` and the
   ``.claude/skills/aidrin/`` folder into your project root. Claude Code
   will pick both up on next launch.

Step 3 — Verify the connection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Start a Claude Code session in the AIDRIN directory and ask:

.. code-block:: text

   List the available AIDRIN metrics.

Claude should call the ``list_metrics`` tool and return the full metric catalogue grouped by
category. If it falls back to running ``aidrin list`` in the terminal instead, the MCP server
did not connect — check that ``aidrin-mcp`` is on your PATH (``which aidrin-mcp``).

----

.. _aidrin_skill_tools:

Available Tools
---------------

The MCP server exposes eleven tools. You do not normally call these by name;
Claude selects them from your request. They are listed here so you know what is
reachable.

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Tool
     - What it does
   * - ``list_metrics``
     - Lists all available metrics, grouped by category
   * - ``summarize_dataset``
     - Describes a dataset's numerical and categorical features
   * - ``run_data_quality_check``
     - Runs the three core data quality metrics: completeness, duplicity, outliers
   * - ``run_aidrin_metric``
     - Runs a single built-in metric against a dataset
   * - ``run_custom_outlier_check``
     - Runs Custom Criteria Outliers against selected targets
   * - ``run_batch``
     - Runs multiple metrics declared in a YAML or JSON batch config
   * - ``create_custom_metric``
     - Generates a ``CustomDR`` template file with ``metric()`` and ``remedy()`` stubs
   * - ``run_custom_metric``
     - Runs the ``metric()`` method of a ``CustomDR`` class defined in a ``.py`` file
   * - ``run_custom_remedy``
     - Runs the ``remedy()`` method of a ``CustomDR`` class and applies it to the dataset
   * - ``agentic_build_index``
     - Builds the FAISS vector index from the domain-literature PDFs in the agentic config
   * - ``agentic_run``
     - Runs the full agentic evaluation pipeline

.. warning::

   ``run_custom_metric``, ``run_custom_remedy``, and the agentic tools execute
   Python from the files you point them at. Only use them with code you trust.

----

Running an Assessment
---------------------

Point Claude at a dataset and describe your intent:

.. code-block:: text

   Is my dataset at /path/to/data.csv ready for training a classifier?

.. code-block:: text

   Check fairness and privacy in my CSV - the target is the "approved" column,
   and "age", "zipcode", and "gender" may be quasi-identifiers.

.. code-block:: text

   Run a full data quality check on /path/to/data.csv and write a report.

Claude follows a structured workflow:

1. Confirms AIDRIN is available and lists the metrics.
2. Asks whether you have domain literature (PDFs, standards, regulations) the dataset
   should be evaluated against — see :ref:`aidrin_skill_agentic` below. If you say no,
   this step is a no-op and the rest of the workflow is unchanged. If your dataset
   isn't a plain CSV, Claude writes a small loader for it automatically (or asks for
   one, if the format isn't one AIDRIN already parses).
3. Inspects the dataset schema and sample statistics.
4. Proposes a metric plan matched to your intent and asks you to confirm column roles —
   plus, if you gave a literature path, the resource path and domain questions from
   step 2, before any of it runs.
5. Runs the metrics via MCP tools, and the agentic pipeline too if domain literature
   was provided.
6. Writes an interpreted markdown report with scores, their directional meaning, and
   suggested next steps — without declaring a ready/not-ready verdict (that judgment
   is yours).
7. Offers to evaluate custom metrics or apply remedies to the dataset.

Supported file formats: CSV, Excel (``.xls`` / ``.xlsx`` / ``.xlsb`` / ``.xlsm``), JSON,
NumPy (``.npz``), HDF5 (``.h5``), Parquet.

----

.. _aidrin_skill_agentic:

Agentic Pipeline via MCP
-------------------------

The agentic pipeline is also available through MCP, letting Claude orchestrate the full
literature-grounded evaluation without you running any commands.

**What it does:** Takes domain-specific questions, retrieves relevant passages from
indexed PDFs (research papers, standards, regulations), generates Python analysis code
and runs it against your dataset, scores complexity, and produces remediation
recommendations — all grounded in your domain literature.

**When to use it:** When you have domain PDFs and want to evaluate the dataset against
field-specific standards rather than (or in addition to) generic quality metrics.

There are two ways to run it:

**Guided** (recommended for most cases)
   During a normal assessment (see `Running an Assessment`_ above), Claude asks up
   front whether you have domain literature. Give it a path and your domain questions,
   and Claude writes the config itself — dataset path, a short metadata description
   drawn from your stated intent and the inspected schema, your resource path, and your
   questions — then builds the index and runs the pipeline as part of the same session.
   No YAML to hand-write, and nothing runs before you've confirmed the plan.

**Standalone**
   Run it separately at any time, with full control over the config: point Claude at a
   config file you've authored yourself, or skip Claude entirely and run
   ``aidrin agentic build-index`` / ``aidrin agentic run`` from the command line (see
   :ref:`agentic_integration`). Use this when you want to re-run with a different
   config, tune settings the guided path doesn't ask about (retrieval ``top_k``, chunk
   size, per-stage models), or evaluate a dataset outside a full AIDRIN assessment.
   The rest of this section documents that config format.

Setup
~~~~~

**Install agentic dependencies:**

.. code-block:: bash

   pip install -e ".[agentic]"

**Set your API key:**

.. code-block:: bash

   export OPENAI_API_KEY="sk-..."   # or the key for your OpenAI-compatible endpoint

**Create an agentic config YAML.** All paths are resolved relative to the config file:

.. code-block:: yaml

   llm:
     base_url: "https://api.openai.com/v1"   # any OpenAI-compatible endpoint

   paths:
     data_loader: "./loader.py:load_dataset"  # Python function returning a DataFrame
     # OR: data_csv: "./data/mydata.csv"      # for plain CSV files
     metadata_csv: "./data/metadata.txt"      # required: plain-text dataset description

   vector_store:
     sources:
       - ./sources                            # directory containing domain PDFs
     embedding_model: text-embedding-ada-002
     vector_store_name: my_index
     chunk_size: 1000
     chunk_overlap: 200

   retrieval:
     enabled: true                            # false = skip RAG, use LLM knowledge only
     answer_model: gpt-4o
     top_k: 3
     max_workers: 4                           # questions run in parallel
     question:
       - "Does the age feature satisfy the HIPAA Safe Harbor de-identification standard?"
       - "What resampling rate is recommended by IEC 62056 for smart meter data?"

   executor:
     enabled: true
     max_attempts: 5
     model: gpt-4o
     temperature: 0.0

   complexity_scorer:
     enabled: true
     model: gpt-4o

   remediation:
     enabled: true
     model: gpt-4o

   output:
     save_log: true

.. note::

   ``paths.metadata_csv`` is **required**. It is a plain-text file describing your dataset
   (columns, units, provenance) — used to give the LLM structural context. Without it the
   pipeline will not start.

Running (standalone, with your own config)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tell Claude to run it:

.. code-block:: text

   Run an agentic evaluation using my config at /path/to/config.yaml

Claude will:

1. Call ``agentic_build_index`` to index your PDFs into a FAISS vector store (once; skipped
   automatically on subsequent runs if the index already exists).
2. Call ``agentic_run`` to execute the full pipeline.
3. Return a combined JSON result: ``profile``, ``queries`` (one entry per question with
   retrieval passages, generated code, execution result, complexity score, and remediation
   recommendations), and ``token_usage``.

To build the index separately first:

.. code-block:: text

   Build the agentic index using /path/to/config.yaml

Then run the pipeline, telling Claude to skip rebuilding the index:

.. code-block:: text

   Run the agentic pipeline with /path/to/config.yaml — skip the vector build.

For a full end-to-end example using a real dataset and literature, see the
:ref:`agentic_integration` section on the CLI Usage page.
