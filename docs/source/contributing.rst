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

Where the Optional Features Live
=================================

Installation and use of the optional extras are documented in
:ref:`web_installation` and :ref:`web_usage`. This is the code map.

**Globus Compute** (``pip install -e ".[globus]"``)

- ``aidrin/compute/remote.py``: serialises the metric call and submits it to
  the endpoint
- ``web/routes/globus.py`` registers the ``/globus`` routes: ``/auth``,
  ``/callback``, ``/status``, ``/disconnect``, ``/check-endpoint``, ``/submit``,
  ``/cache-summary``, ``/check-task/<task_id>``
- ``web/globus.py``: Globus Auth client and token handling
- ``web/templates/_components/globus_panel.html``: the Remote (Globus) tab

Reads ``GLOBUS_CLIENT_ID``, and ``GLOBUS_CLIENT_SECRET`` for the confidential
client flow.

Globus worker file-reference policy
-----------------------------------

The endpoint process environment and worker environment are distinct. Put the
AIDRIN environment activation and file-reference policy in ``worker_init`` so
they run in each worker process. Configure
``AIDRIN_FILE_REFERENCE_ALLOWED_ROOTS`` as a JSON array of existing absolute
directories and set the positive scan cap with
``AIDRIN_FILE_REFERENCE_WEB_SCAN_LIMIT``. The example provider configuration
is in ``examples/globus/aidrin-local-provider.yaml``.

Scheduler-backed providers must activate the same AIDRIN environment and
expose the configured paths on every allocated worker node. For containerized
workers, mount every allowed root at exactly the configured path using
``container_cmd_options`` (for example,
``-v /data/project:/data/project:ro``).

For a file-reference validation demo, place a manifest and its referenced
files below a configured worker root, load the manifest by its worker-visible
path, and use the **Data Structure** panel to enable validation. Select exact
targets or a full-match regular expression, the worker root, and an optional
relative base subdirectory. Globus Connect and Globus Transfer are not part of
this workflow: Compute reads paths already visible to its workers. The CLI, Python API, and MCP interfaces
continue to validate paths on their own host.

**LLM explanations** (``pip install -e ".[llm]"``)

- ``web/llm.py``: optional-dependency detection and ``explain_metric()``
- ``web/routes/llm.py`` registers the ``/llm`` routes: ``/configure``,
  ``/test``, ``/explain``, ``/status``, ``/disconnect``, ``/cache-explanation``
- ``web/templates/_components/llm_settings.html``: the settings modal

When the ``openai`` package is not installed the feature is hidden in the UI
with zero overhead, so guard any new code paths the same way. LLM calls happen
server-side *after* the metric result is rendered, and the explanation loads
asynchronously so it never blocks results. API keys live in the server-side
Flask session only. Never surface them in client-side JavaScript or logs.


Debugging the Web Interface
============================

AIDRIN's web interface includes debug logging that is disabled by default to keep the browser console clean. To enable verbose logging during development:

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
