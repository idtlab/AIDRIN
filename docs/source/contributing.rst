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
- **Include tests** for new features (unit, integration, examples).
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

Thank you for contributing to AIDRIN!
