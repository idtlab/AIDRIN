=======================
Contributing to AIDRIN
=======================

We welcome your contributions to AIDRIN! This guide outlines the essential steps and rules to follow when contributing.

Quick Start
============

1. Fork the repository.
2. Create a branch from ``develop``.
   Do **not** create branches in the main repo without prior discussion.
3. Work on your changes.
4. Install and run **pre-commit** hooks:

   .. code-block:: bash

      pip install pre-commit
      pre-commit install
      pre-commit run --all-files

5. Submit a pull request to ``develop`` with all required items (see below).

Coding Standards
=================

- Follow **PEP8** style; our CI enforces it.
- Run `pre-commit` to auto-format and lint your code before committing.
- **Include tests** for new features (unit, integration, examples). See :ref:`testing` for how to run the test suite.
- **Document your code** using proper docstrings:

  - **L1 (mandatory)**: summary, params, returns, exceptions, TODOs
  - **L2 (optional)**: algorithms, data structures, complex logic

Pull Request Guidelines
========================

Every PR **must**:

- Be linked to an issue.
- Use the default **PR template**.
- Pass **all CI checks**.
- Include **tests** and **documentation** if applicable.
- Be updated with the latest ``develop``.

**Merging Rules:**

- ``develop`` branch: 1 approval required
- ``main`` branch: 2 approvals required
- Default to **Squash and Merge**

Issues and Labels
==================

Before you begin:

- Make sure your issue is labeled properly.
- Use the correct **issue template** (bug, feature, install, usage).
- Every change starts with an issue.

OpenTelemetry (Optional)
=========================

AIDRIN supports optional OpenTelemetry tracing for monitoring metric evaluation performance.

**Installation (from local source):**

.. code-block:: bash

   # From the project root:
   pip install -e ".[telemetry]"

   # Or with dev tools as well:
   pip install -e ".[telemetry,dev]"

When the telemetry packages are not installed (plain ``pip install -e .``), all tracing
is a no-op with zero overhead.

**Configuration** via environment variables:

- ``OTEL_EXPORTER_OTLP_ENDPOINT`` — collector endpoint (e.g., ``http://localhost:4317``). If not set, traces go to console.
- ``OTEL_SERVICE_NAME`` — service name (defaults to ``aidrin``).

**What gets traced:**

- Every HTTP request (automatic via Flask instrumentation)
- Each metric evaluation with attributes: ``metric.name``, ``metric.pillar``, ``metric.duration_ms``
- File metadata: ``file.name``, ``file.type``

**Quick test (console output):**

.. code-block:: bash

   pip install -e ".[telemetry]"
   flask --app 'web:create_app()' run --debug

Run a metric and observe trace spans printed to the terminal.

**Test with Jaeger:**

.. code-block:: bash

   # Start Jaeger (Docker)
   docker run -d --name jaeger \
     -p 16686:16686 -p 4317:4317 \
     jaegertracing/all-in-one:latest

   # Start AIDRIN with OTLP exporter
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
   flask --app 'web:create_app()' run --debug

   # Open Jaeger UI at http://localhost:16686, select service "aidrin"

**Verify installation:**

.. code-block:: python

   # With OTel installed:
   python -c "from web.telemetry import get_tracer; print(type(get_tracer()).__name__)"
   # → "Tracer"

   # Without OTel:
   # → "_NoOpTracer"


Globus Compute (Optional)
==========================

AIDRIN supports remote metric execution via Globus Compute, allowing you to
evaluate large datasets without transferring files to the AIDRIN server.

**Installation:**

.. code-block:: bash

   pip install -e ".[globus]"

**Setup:**

1. Register an application at https://developers.globus.org/
2. Set the environment variable:

   .. code-block:: bash

      export GLOBUS_CLIENT_ID=<your-client-id>

3. The remote Globus Compute endpoint must have ``aidrin`` installed:

   .. code-block:: bash

      pip install aidrin

**Setting up a Globus Compute Endpoint:**

On the remote machine where your data is located:

.. code-block:: bash

   # Install the endpoint software and aidrin
   pip install globus-compute-endpoint aidrin

   # Configure a new endpoint
   globus-compute-endpoint configure aidrin-endpoint

   # Start the endpoint
   globus-compute-endpoint start aidrin-endpoint

   # Get the endpoint UUID (copy this for the inspector)
   globus-compute-endpoint list

For local testing, you can run an endpoint on the same machine:

.. code-block:: bash

   pip install globus-compute-endpoint
   globus-compute-endpoint configure test-local
   globus-compute-endpoint start test-local

Stop an endpoint with ``globus-compute-endpoint stop <name>``.

**Requirements for the remote endpoint:**

- ``aidrin`` must be installed (``pip install aidrin``)
- Network access to authenticate with Globus
- The file path entered in the inspector must be accessible from the endpoint machine

**Usage:**

1. In the inspector, select the "Remote (Globus)" tab
2. Click "Sign in with Globus" (redirects to Globus Auth)
3. Paste the Globus Compute endpoint UUID
4. Enter the file path as it exists on the remote machine (e.g., ``/home/user/data/adult.csv``)
5. Select the file type and click "Load Remote Dataset"
6. Run metrics as usual — computation happens on the remote endpoint, only results travel back


LLM Explanations (Optional)
============================

AIDRIN supports optional AI-generated explanations of metric results using any
OpenAI-compatible API (OpenAI, Azure OpenAI, Ollama, vLLM, etc.).

**Installation:**

.. code-block:: bash

   pip install -e ".[llm]"

When the ``openai`` package is not installed, the feature is hidden in the UI
with zero overhead.

**How it works:**

1. Click the sparkle icon in the top-right toolbar to open the AI settings.
2. Enter the API base URL, API key, and model name.
3. Click **Test** to verify the connection. If successful, click **Save**.
4. From that point on, every metric result will show an "AI Explanation"
   callout below the results with a short LLM-generated interpretation.

**Configuration details:**

- **API Base URL** — the base URL of the OpenAI-compatible API
  (default: ``https://api.openai.com/v1``). For Ollama, use
  ``http://localhost:11434/v1``.
- **API Key** — your API key. Stored in the server-side Flask session only;
  never exposed in client-side JavaScript or logs.
- **Model** — the model identifier (e.g., ``gpt-4o-mini``, ``llama3``,
  ``claude-3-haiku-20240307``).

**What gets sent to the LLM:**

- The metric name and description (context)
- The metric scores/values (JSON)
- The plot image (base64 PNG), if the model supports vision

If the model does not support vision (returns empty with an image), AIDRIN
automatically retries with text-only input. The model name is displayed in
the explanation callout for transparency.

**Architecture:**

- ``web/llm.py`` — optional dependency detection and ``explain_metric()``
- ``web/routes/llm.py`` — Flask routes: ``/llm/configure``, ``/llm/test``,
  ``/llm/explain``, ``/llm/status``, ``/llm/disconnect``
- ``web/templates/_components/llm_settings.html`` — settings modal
- LLM calls happen server-side, after the metric result is rendered;
  the explanation loads asynchronously without blocking results

**Testing with Ollama (local, no API key needed):**

.. code-block:: bash

   # Install and start Ollama
   ollama serve
   ollama pull llama3

   # In AIDRIN settings:
   # API Base URL: http://localhost:11434/v1
   # API Key: ollama  (any non-empty string)
   # Model: llama3


Debugging the Web Interface
============================

AIDRIN's inspector UI includes debug logging that is disabled by default to keep the browser console clean. To enable verbose logging during development:

1. Open the browser's developer console (F12 → Console).
2. Run:

   .. code-block:: javascript

      localStorage.setItem("aidrin_debug", "true");

3. Reload the page. All internal log messages will now appear prefixed with ``[aidrin]``.

To disable debug logging again:

   .. code-block:: javascript

      localStorage.removeItem("aidrin_debug");

This affects ``main.js`` debug output. Errors (``console.error``) are always shown regardless of this setting.

Thank you for contributing to AIDRIN!
