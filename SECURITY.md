# Security Policy

## Reporting a vulnerability

Please do not open a public issue for security problems.

Report privately through GitHub's private vulnerability reporting:
https://github.com/idtlab/AIDRIN/security/advisories/new

If you cannot use GitHub, email security@aidrin.org. Include the affected
component, a minimal reproduction, and the impact you believe it has.

We credit reporters in the release notes unless asked not to.

## Supported versions

AIDRIN uses calendar versioning (`vYYYY.MM.N`). Only the latest release on
PyPI receives security fixes. Fixes land on `develop` and ship in the next
release; we do not backport.

## Scope

In scope: the `aidrin` Python package and CLI, the MCP server, the web UI,
the worker, the Docker images, and the `aidrin` agent skill under
`aidrin/skill/`.

The following are by design and are not vulnerabilities on their own:

- **Custom metrics and remedies execute user-supplied Python.**
  `aidrin run custom`, `run_custom_metric` and `run_custom_remedy` load and
  run the module the user points them at. Only run modules you wrote or
  reviewed.
- **The agentic pipeline executes LLM-generated code** against the dataset
  and sends the dataset profile and retrieved document text to the configured
  LLM endpoint. Run it in an environment you have chosen for that purpose and
  supply the API key through the environment, not a config file.
- **The MCP server and CLI trust the local user.** They read and write files
  on the host they run on with that user's permissions. They are not meant to
  be exposed to untrusted clients.
- **Remote execution (Globus Compute)** runs on endpoints the user configured
  and returns metric results only.

## Dependencies

Dependabot monitors `pyproject.toml` and `uv.lock`. Reports about a
dependency should go to that project; tell us if AIDRIN needs a version bump
to pick up the fix.
