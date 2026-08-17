# Globus Remote Execution for the CLI, MCP, and Skill: Design Spec

**Date:** 2026-07-30
**Base branch:** `develop`
**Suggested branch:** `feature/globus-remote-cli`

## Purpose

The AIDRIN web interface can run metrics on a remote Globus Compute endpoint
(`web/globus.py`, `web/routes/globus.py`, `aidrin/compute/remote.py`). The
headless surfaces cannot: `aidrin/headless/cli.py` and `aidrin/mcp/server.py`
only ever execute metrics against a local file path, and every piece of Globus
auth lives inside a Flask session.

This spec defines a headless path to the same machinery, so a user (or the
`aidrin` skill acting on their behalf) can assess a dataset that lives on a
remote machine without moving the data and without opening the web UI.

## Context: what already exists on `develop`

1. **`aidrin/compute/remote.py`** holds `remote_metric_runner` and
   `remote_env_probe`. These live in the `aidrin` package rather than in `web`
   on purpose: Globus Compute serialises a *reference* to the function, and the
   worker reconstructs it by importing the module. The endpoint has `aidrin`
   installed but not the Flask app.
2. **`web/globus.py`** holds the OAuth2 redirect flow (browser to Flask
   callback), `get_compute_client`, `register_function`,
   `check_endpoint_compatibility`, `submit_metric`, and `check_task`.
3. **`aidrin/headless/`** holds `api.py` (the programmatic surface:
   `run_metric`, `summarize_dataset`, `run_data_quality`, `run_batch_metrics`),
   `cli.py`, `config.py`, `runners.py`, and `METRIC_REGISTRY`.
4. **`aidrin/mcp/server.py`** wraps the headless API as MCP tools.
5. **`.claude/skills/aidrin/SKILL.md`** drives AIDRIN through MCP when
   available and the CLI otherwise. It is local-only today.
6. `pyproject.toml` already declares the `globus` extra
   (`globus-compute-sdk>=2.3.0`, `globus-sdk>=3.20.0`).

## Goal

`aidrin remote summarize /scratch/proj/data.csv` produces the same JSON on
stdout as `aidrin summarize` does locally, having executed on a configured
Globus Compute endpoint, with the endpoint remembered between invocations.

## Non-goals

- **Globus Transfer.** The dataset is assumed to already be on a filesystem the
  endpoint can see. Nothing is staged, listed, or moved.
- **Remote file discovery.** The remote path is supplied by the user, exactly
  as in the web UI today. A bad path surfaces as a metric error.
- **Custom metrics and remedies remotely.** The custom script lives on the
  client machine and the endpoint cannot import it. Rejected with a clear
  message; shipping the source in the payload is a possible follow-up.
- **The agentic pipeline remotely.** It needs local PDFs, a vector store, and
  API credentials.
- **Refactoring `web/globus.py`.** The web path stays as it is. The new client
  module is written so the web can be thinned onto it later, but that is a
  separate change.

## Architecture

### The seam: a headless-shaped remote entry point

`remote_metric_runner` speaks the web's vocabulary. Its dispatch table is keyed
by web metric names (`duplicates`, `summary_statistics`, `data_quality`,
`fairness`) and takes web-shaped `params` dicts. The CLI's `METRIC_REGISTRY`
uses different names (`duplicity`, `outliers_custom`) and different argument
names, and the two evolve independently.

Routing the CLI through `remote_metric_runner` would therefore require a
translation table between two registries, which is a standing maintenance
liability: a metric added to the CLI silently fails remotely until someone
remembers to extend the mapping.

Instead, add a **second** entry point beside it that speaks the headless API's
vocabulary:

```python
# aidrin/compute/remote.py

def remote_headless_runner(command, kwargs):
    """Execute an aidrin.headless.api call on the remote endpoint.

    Runs ON the Globus Compute endpoint. Imports are inside the body so a bare
    module import on the worker stays cheap, matching remote_metric_runner.
    """
    import matplotlib
    matplotlib.use("Agg")

    from aidrin.headless import api

    dispatch = {
        "run_metric": api.run_metric,
        "summarize": api.summarize_dataset,
        "data_quality": api.run_data_quality,
        "batch": api.run_batch_metrics,
    }
    fn = dispatch.get(command)
    if fn is None:
        return {"Error": f"Unknown remote command: {command}",
                "ErrorType": "UnknownCommand"}
    try:
        return fn(**kwargs)
    except Exception as exc:
        return {"Error": str(exc), "ErrorType": type(exc).__name__}
```

Every headless API signature takes plain JSON-serialisable arguments, so the
CLI's remote path is a pass-through with no name mapping at all. There remains
exactly one registry (`METRIC_REGISTRY`) governing metric names and arguments,
and it is the one the endpoint itself consults.

Errors are returned as an `Error`/`ErrorType` dict rather than raised, matching
the convention the local CLI and MCP server already use and that SKILL.md
already instructs the agent to check.

### Module layout

| File | Change | Approx. size |
|---|---|---|
| `aidrin/compute/remote.py` | add `remote_headless_runner` | +40 lines |
| `aidrin/compute/client.py` | **new**: auth, probe, submit, poll, cancel | ~180 lines |
| `aidrin/compute/profiles.py` | **new**: named-profile config read/write | ~120 lines |
| `aidrin/headless/cli.py` | add the `remote` subcommand group | +150 lines |
| `aidrin/mcp/server.py` | optional `endpoint`/`profile` on run tools | +40 lines |
| `.claude/skills/aidrin/SKILL.md` | remote section + table column | docs |
| `docs/` | remote usage page | docs |

### Data flow

```
aidrin remote summarize /scratch/data.csv --profile nersc
  │
  ├─ profiles.resolve()          → endpoint uuid (flag > profile > env > project > user)
  ├─ client.get_client()         → globus_compute_sdk.Client() (SDK-cached tokens)
  ├─ client.register()           → function uuid for remote_headless_runner (cached)
  ├─ client.submit(command="summarize", kwargs={...})
  │        └─ endpoint: import aidrin.headless.api → summarize_dataset()
  ├─ client.poll(task_id, timeout)   [or return task id when --async]
  ├─ _maybe_save_images(result)  ← LOCAL post-processing, unchanged code
  └─ json.dumps(result) → stdout
```

## Component detail

### 1. `aidrin/compute/client.py` (new)

Roughly the useful half of `web/globus.py`, minus the OAuth redirect flow.

- `is_available()`: mirrors `web/globus.is_globus_available()`, returning False
  when `globus-compute-sdk` is not installed so the `remote` command group can
  print an actionable `pip install 'aidrin[globus]'` message instead of an
  ImportError traceback.
- `get_client()`: constructs `globus_compute_sdk.Client()` with no authorizer.
  The SDK runs its own Native App login on first use and caches tokens under
  `~/.globus_compute/`, shared with the `globus-compute-endpoint` CLI the user
  is likely to already have. AIDRIN owns no credential store.
- `login()` / `logout()` / `whoami()`: thin wrappers over the SDK's login
  manager, surfaced as `aidrin remote login|logout|status`.
- `register(force=False)`: registers `remote_headless_runner`, caching the
  function UUID per process, matching `web/globus.register_function`.
- `probe(endpoint_id, timeout=30)`: submits `remote_env_probe` and returns the
  endpoint's `aidrin` and Python versions, or a structured failure.
- `submit(endpoint_id, command, kwargs)`: returns a task id string.
- `poll(task_id, timeout, interval)`: blocks, returning the result or raising
  `RemoteTimeout`.
- `cancel(task_id)`: used by the Ctrl-C handler and `remote task --cancel`.

### 2. `aidrin/compute/profiles.py` (new)

Named profiles, stored as JSON.

```json
{
  "default": "nersc",
  "profiles": {
    "nersc": {"endpoint": "3f2b...c1", "aidrin_version": "0.9.2",
              "configured": "2026-07-30"},
    "alcf":  {"endpoint": "9ac4...7e", "aidrin_version": "0.9.1",
              "configured": "2026-07-30"}
  }
}
```

- User file: `~/.aidrin/config.json` (override the directory with
  `AIDRIN_CONFIG_DIR`).
- Project file: `./.aidrin.json`, written by `configure --local`.
- Resolution order, first hit wins: `--endpoint` flag, `--profile` name,
  `AIDRIN_GLOBUS_ENDPOINT` env var, project file default, user file default.
- A project file's `profiles` are merged over the user file's, so a project can
  add or shadow a name without redefining the rest.
- Written with mode `0600`. Endpoint UUIDs are not secrets, but the file sits
  next to future config and there is no reason to make it world-readable.

### 3. `aidrin/headless/cli.py`

The `remote` group reuses the existing parser rather than redefining it.
`main()` recognises a leading `remote` token, pulls the remote-only flags out of
`argv` with an `add_help=False` pre-parser and `parse_known_args`, and hands the
remainder to the existing parser untouched. `aidrin remote summarize` therefore
accepts byte-for-byte the same arguments as `aidrin summarize`, forever, with no
second command table to maintain and no restructuring of the parser assembly.

`aidrin remote list` means "list profiles", not "list metrics": management
subcommands are matched before the parser sees anything. `aidrin remote check`
covers the interrogate-the-endpoint case.

Management commands:

```
aidrin remote configure --name nersc --endpoint <uuid> [--default] [--local]
aidrin remote list
aidrin remote remove <name>
aidrin remote check [--profile nersc]
aidrin remote login | logout | status
aidrin remote task <task-id> [--wait] [--cancel]
```

Execution commands (any existing subcommand), with the shared flags
`--profile`, `--endpoint`, `--async`, `--timeout` (default 600s):

```
aidrin remote summarize <remote-path> [...]
aidrin remote data-quality <remote-path> [...]
aidrin remote run <metric> <remote-path> [...]
aidrin remote batch <config>
```

Behaviour:

- Blocking by default. Progress messages (`submitted task <id>`, elapsed time)
  go to **stderr**; only the result JSON goes to stdout, so stdout is identical
  to a local run and every existing script and skill instruction keeps working.
- `--async` prints the task id to stdout and exits 0.
- Ctrl-C during a blocking wait cancels the remote task, then exits 130.
- Exit codes match the local commands.
- `configure` runs `probe` before saving and refuses to save if the probe
  fails, so a wrong or unreachable endpoint or a worker without `aidrin`
  installed is diagnosed at setup time rather than as a serialisation traceback
  after a queue wait. The probed `aidrin` version is stored; every subsequent
  remote command warns on stderr if the local version's minor differs.
- `aidrin remote run custom ...` and `aidrin remote agentic ...` exit 2 with an
  explanation and a pointer to the local equivalent.

### 4. `batch` over a remote endpoint

`run_batch_metrics` runs on the endpoint, so `file_path` inside the config must
be a path the endpoint can see. `configure` does not rewrite paths. The config
file itself is read locally and its parsed dict is sent as `kwargs`, so the
endpoint needs no access to the config file.

### 5. Visualisations and payload size

Globus Compute limits a task result to about 10 MB, and visualisation payloads
are base64 PNGs. Remote submissions therefore default to `save_images=False`
and `strip_visualizations=True`.

With `--save-images`, the submission asks for visualisation payloads in the
result, and the **existing local** `_maybe_save_images` in
`aidrin/headless/api.py` writes them under `--image-dir` on the client. Two
consequences worth stating plainly: a remote run never writes files on the
endpoint, and images land in exactly the place a local run would put them.

If a result exceeds the size limit, the error is caught and re-raised as a
message naming `--save-images` as the likely cause.

### 6. `aidrin/mcp/server.py`

`summarize_dataset`, `run_data_quality_check`, `run_aidrin_metric`, and
`run_batch` gain optional `endpoint: str | None` and `profile: str | None`
parameters. When either is set the call routes through
`aidrin.compute.client`; otherwise the local path is untouched. Blocking only,
with the same default timeout: an MCP tool call has no place to hand back a
task id.

Add one read-only tool, `list_remote_profiles()`, so the agent can discover
what is configured instead of asking the user for a UUID.

### 7. `.claude/skills/aidrin/SKILL.md`

- Preflight (step 1) additionally calls `list_remote_profiles()` (MCP) or
  `aidrin remote list` (CLI). If a profile exists, the agent asks once whether
  this dataset is local or on that endpoint, then keeps that choice for the
  session.
- The MCP/CLI table gains a remote column, for example
  `run_aidrin_metric(..., profile="nersc")` / `aidrin remote run <metric> ...`.
- A short "Remote datasets" section states: the path is on the remote machine
  and the skill cannot list it, so ask the user for the full path; custom
  metrics, remedies, and the agentic pipeline are local-only; results and
  images come back to the client.
- Steps 3 through 8 of the workflow are unchanged, because the arguments and
  the JSON are identical.

## Error handling

| Condition | Surfaced as |
|---|---|
| `globus-compute-sdk` not installed | `aidrin remote ...` exits 2: `pip install 'aidrin[globus]'` |
| Not logged in | SDK login prompt; `--async` in a non-TTY exits 2 pointing at `aidrin remote login` |
| No endpoint resolved | exit 2 naming every resolution source in order |
| Probe fails at configure | not saved; reports whether it was auth, endpoint, or a missing `aidrin` on the worker |
| Endpoint offline at run time | exit 1 with the endpoint status from the SDK |
| Version skew (minor differs) | warning on stderr, run proceeds |
| Metric raises on the worker | `{"Error": ..., "ErrorType": ...}` in stdout JSON, matching local convention |
| Timeout | exit 1, prints the task id and the `aidrin remote task <id>` command to recover the result |
| Result too large | exit 1 naming `--save-images` |
| Ctrl-C | cancel the task, exit 130 |

## Testing

Unit, no Globus required:

- `remote_headless_runner` called directly: dispatches to each of the four API
  functions, returns `Error`/`ErrorType` on an unknown command and on an
  exception. This is the test that proves local and remote share one registry.
- `profiles.py`: resolution precedence across all five sources, project file
  merging over the user file, `--default` handling, `remove` of a default,
  file mode.
- `client.py` against a stubbed compute client: submit, poll to completion,
  timeout, cancel, version-skew warning, missing-SDK path.
- `cli.py`: `remote` subparsers accept the same arguments as their local
  counterparts (assert programmatically over `METRIC_REGISTRY` rather than by
  hand, so a new metric cannot drift), `--async` output shape, exit codes.
- MCP: `endpoint`/`profile` route to the client, absence routes locally.

Integration, extend `tests/integration/test_globus.py`, skipped without
credentials:

- `configure` against a real endpoint stores the probed version.
- `aidrin summarize <file>` locally and `aidrin remote summarize <file>` on an
  endpoint holding the same file produce equal JSON. This is the acceptance
  test for the whole feature.

## Risks

1. **Version skew.** A metric added locally does not exist on an endpoint
   running an older `aidrin`. Mitigated by probing at configure time, storing
   the version, and warning on every run when the minor differs. Not fully
   solvable without pinning the endpoint environment.
2. **Serialisation.** `remote_headless_runner` is resolved by module import on
   the worker, so `aidrin.headless.api` must be importable there. The probe
   already proves `aidrin` imports; extend `remote_env_probe` to import
   `aidrin.headless.api` specifically so the probe covers the real dependency.
3. **Duplicated Globus logic.** `web/globus.py` and `aidrin/compute/client.py`
   will overlap for a while. Accepted deliberately to keep this change out of
   the web path; noted as a follow-up.
4. **Silent local fallback.** If endpoint resolution ever fell through to a
   local run, a user could believe a remote dataset was assessed when a local
   file of the same name was. Explicitly forbidden: `aidrin remote` never runs
   locally, and fails instead.

## Implementation order

1. `remote_headless_runner` plus its unit tests, and the `remote_env_probe`
   extension. Testable with no Globus at all.
2. `profiles.py` plus unit tests.
3. `client.py` plus unit tests against a stub.
4. `cli.py`: extract `_add_metric_subcommands`, verify the local CLI is
   unchanged, then add the `remote` group.
5. Real-endpoint integration check, including the local-versus-remote JSON
   equality test.
6. MCP parameters and `list_remote_profiles`.
7. SKILL.md and docs.

Steps 1 to 4 deliver the feature the user asked for. Steps 6 and 7 are what
make the skill able to use it.
