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
