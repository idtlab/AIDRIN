# AIDRIN – AI Data Readiness Infrastructure

[![PyPI](https://img.shields.io/pypi/v/aidrin?logo=pypi&logoColor=white)](https://pypi.org/project/aidrin/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue?logo=python&logoColor=white)](https://pypi.org/project/aidrin/)
[![DOI](https://img.shields.io/badge/DOI-10.1145%2F3676288.3676296-orange)](https://doi.org/10.1145/3676288.3676296)

[![Tests](https://img.shields.io/github/actions/workflow/status/idtlab/AIDRIN/tests.yml?branch=develop&label=tests&logo=github)](https://github.com/idtlab/AIDRIN/actions/workflows/tests.yml)
[![Build](https://img.shields.io/github/actions/workflow/status/idtlab/AIDRIN/build.yml?branch=develop&label=build&logo=github)](https://github.com/idtlab/AIDRIN/actions/workflows/build.yml)
[![Docs](https://img.shields.io/readthedocs/aidrin?logo=readthedocs&logoColor=white)](https://aidrin.readthedocs.io/en/latest/)
[![Dependencies](https://img.shields.io/librariesio/github/idtlab/AIDRIN)](https://libraries.io/github/idtlab/AIDRIN)

**AIDRIN** (AI Data Readiness Infrastructure) is a lightweight, open-source tool designed to evaluate the readiness of datasets for AI and machine learning workflows. It assesses dataset quality, completeness, and structure through quantitative metrics, across six dimensions of data readiness.

There are four ways to use it:

- **Web interface**: an interactive dashboard, hosted at [aidrin.org](https://aidrin.org) or self-hosted.
- **Command line**: `aidrin data-quality data.csv` and friends, for pipelines and CI. Includes an agentic evaluation component for domain-aware question answering and remediation.
- **Python library**: `pip install aidrin`, for notebooks and scripts.
- **Claude Code**: an MCP server (`aidrin-mcp`) and skill, to assess datasets in plain language.

For installation, usage, and contribution guidelines, please refer to the [AIDRIN documentation](https://aidrin.readthedocs.io/en/latest/).

Please read our [Code of Conduct](./CODE_OF_CONDUCT.md) before contributing.
