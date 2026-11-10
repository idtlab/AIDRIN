"""Frontend behavior of the remote HDF5 dataset picker (PR #291 review).

The flows here run the real ``inspector.js`` functions under Node against a
stub DOM and a stub ``fetch``, because the bugs they cover are all about state
that outlives one interaction: which file a dataset selection belongs to, which
picker a pending connect came from, and what happens on a refused request.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSPECTOR_JS = REPO_ROOT / "web" / "static" / "js" / "inspector.js"
NODE_TIMEOUT = 30

requires_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node is required to run inspector.js"
)


def _source():
    return INSPECTOR_JS.read_text(encoding="utf-8")


def _slice(source, start_marker, end_marker):
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def _run_node(script):
    completed = subprocess.run(
        ["node", "-e", script],
        text=True,
        capture_output=True,
        check=True,
        timeout=NODE_TIMEOUT,
    )
    return json.loads(completed.stdout)


# --------------------------------------------------------------------------
# Globus connect / dataset selection flows
# --------------------------------------------------------------------------

# Stub DOM: only ids the page actually renders resolve, so a lookup that
# reaches for an element from the other panel gets null, as in the browser.
_DOM_STUB = """
const log = [];
const vals = {
  "globus-endpoint-id": "ep-1",
  "globus-file-path": "/data/A.h5",
  "globus-file-type": ".h5",
};
const makeClassList = () => {
  const set = new Set();
  return {
    names: set,
    add: (...c) => c.forEach((x) => set.add(x)),
    remove: (...c) => c.forEach((x) => set.delete(x)),
    toggle: (c, on) => (on ? set.add(c) : set.delete(c)),
    contains: (c) => set.has(c),
  };
};
const makeEl = (id) => ({
  id,
  innerHTML: "",
  textContent: "",
  style: {},
  disabled: false,
  classList: makeClassList(),
  get value() { return vals[id]; },
  contains(other) { return other === this; },
  replaceChildren(...nodes) {
    this.innerHTML = nodes.map((n) => n.textContent).join("");
  },
  querySelector: () => null,
  querySelectorAll: () => [],
  remove() {},
});
const els = {};
const el = (id) => (els[id] = els[id] || makeEl(id));
const document = {
  getElementById: (id) => (PRESENT.has(id) ? el(id) : null),
  querySelector: () => el("load-btn"),
  querySelectorAll: () => [],
  createElement: () => makeEl("created"),
};
const window = { location: {} };
const setTimeout = (fn) => queueMicrotask(fn);
const showToast = (msg, kind) => log.push(`TOAST ${kind} ${msg}`);
const clearGlobusDiscoveryCache = () => {};
const clearWorkspaceFeatureDropdowns = () => log.push("DROPDOWNS CLEARED");
const fetchGlobusSummary = () => log.push("SUMMARY REFETCHED");
const renderHdf5DatasetPicker = (container, data) =>
  log.push(`PICKER ${container.id} ${data.message || ""}`.trim());
const escapeHtml = (v) => String(v);
const tick = async () => { for (let i = 0; i < 40; i++) await null; };
const jsonResponse = (body, ok = true) =>
  Promise.resolve({ ok, json: () => Promise.resolve(body) });
let endpointCheckGates = [];
let submitError = null;
let clearStatus = { ok: true, body: { success: true } };
const fetch = (url, opts) => {
  const body = opts && opts.body ? JSON.parse(opts.body) : {};
  if (url === "/globus/check-endpoint") {
    // Held open so a stale picker can be clicked mid-check.
    return new Promise((resolve) =>
      endpointCheckGates.push(() =>
        resolve(jsonResponse({ compatible: true })),
      ),
    );
  }
  if (url === "/filter-file" || url === "/globus/filter-datasets") {
    log.push(`FILTER ${url} keys=${JSON.stringify(body.keys || [])}`);
    return jsonResponse({ success: true });
  }
  if (url === "/globus/clear-dataset-selection") {
    return jsonResponse(clearStatus.body, clearStatus.ok);
  }
  if (body.metric_name === "file_inventory") {
    return jsonResponse({
      status: "completed",
      result: {
        success: true,
        type: "multi_dataset",
        datasets: [{ path: "/a", shape: [10], ndim: 1 }],
      },
    });
  }
  log.push(
    `SUBMIT ${body.metric_name} file=${body.file_path} ` +
      `keys=${JSON.stringify(body.selected_keys || [])}`,
  );
  return submitError
    ? jsonResponse({ error: submitError }, false)
    : jsonResponse({ task_id: "task-1" });
};
const releaseEndpointCheck = async () => {
  endpointCheckGates.splice(0).forEach((gate) => gate());
  await tick();
};
const done = (extra) =>
  process.stdout.write(JSON.stringify(Object.assign({ log }, extra || {})));
"""


def _connect_flow_script(present, driver):
    source = _source()
    code = "\n".join(
        (
            _slice(
                source,
                "function _globusSelectedKeysList",
                "\n/** Fetch summary statistics via Globus",
            ),
            _slice(source, "function loadGlobusDataset()", "\nlet _globusSubmitInProgress"),
            _slice(
                source,
                "function selectHdf5Datasets(",
                "\nfunction clearWorkspaceFeatureDropdowns",
            ),
            _slice(
                source,
                "function returnToHdf5DatasetPicker()",
                "\n/**\n * Fetch summary statistics from the backend",
            ),
            _slice(source, "function renderGlobusSummary(data)", "\n/** Poll for Globus summary"),
        )
    )
    return f"const PRESENT = new Set({json.dumps(present)});\n{_DOM_STUB}\n{code}\n{driver}"


UPLOAD_PAGE = [
    "globus-endpoint-id",
    "globus-file-path",
    "globus-file-type",
    "globus-hdf5-picker",
]
WORKSPACE_PAGE = ["workspace-summary", "workspace-histograms", "sidebar-metrics"]


@requires_node
def test_a_stale_picker_cannot_submit_its_keys_with_another_file():
    """Clicking a leftover picker while a new Load is mid endpoint-check must
    not leave its keys for the new file's submit to pick up."""
    result = _run_node(
        _connect_flow_script(
            UPLOAD_PAGE,
            """
(async () => {
  loadGlobusDataset();
  await releaseEndpointCheck();           // picker for A is rendered
  vals["globus-file-path"] = "/data/B.h5";
  loadGlobusDataset();                    // endpoint check for B in flight
  // A fresh Load must retire A's picker at once: it lives outside #globusForm,
  // so disabling the form does not disable its button.
  const retired = {
    pending: window._globusPendingConnect,
    hidden: el("globus-hdf5-picker").classList.contains("hidden"),
    emptied: el("globus-hdf5-picker").innerHTML === "",
  };
  selectHdf5Datasets(["/a"], el("globus-hdf5-picker"));  // click A's picker
  await tick();
  await releaseEndpointCheck();
  done({ retired });
})();
""",
        )
    )
    assert result["retired"] == {"pending": None, "hidden": True, "emptied": True}, result
    carried = [
        line
        for line in result["log"]
        if "file=/data/B.h5" in line and "keys=[]" not in line
    ]
    assert carried == [], result["log"]
    # B still gets its own picker, so the user picks for the file they named.
    pickers = [line for line in result["log"] if line.startswith("PICKER")]
    assert len(pickers) == 2, result["log"]


@requires_node
def test_loading_another_file_after_a_failed_submit_reopens_the_picker():
    """Keys from A must not be inherited by B: the picker opens again."""
    result = _run_node(
        _connect_flow_script(
            UPLOAD_PAGE,
            """
(async () => {
  loadGlobusDataset();
  await releaseEndpointCheck();
  submitError = "endpoint rejected the task";
  selectHdf5Datasets(["/a"], el("globus-hdf5-picker"));
  await tick();                           // A's submit fails, keys linger
  submitError = null;
  vals["globus-file-path"] = "/data/B.h5";
  loadGlobusDataset();
  await releaseEndpointCheck();
  done({ keys: window.AIDRIN_GLOBUS_SELECTED_KEYS });
})();
""",
        )
    )
    submits = [line for line in result["log"] if line.startswith("SUBMIT")]
    assert submits == ["SUBMIT completeness file=/data/A.h5 keys=[\"/a\"]"], result["log"]
    # Two picker renders: one for A, one for B after the keys were dropped.
    assert len([line for line in result["log"] if line.startswith("PICKER")]) == 2, result["log"]
    assert result["keys"] == [], result


@requires_node
def test_reloading_the_same_file_keeps_its_dataset_selection():
    """The stamp exists so a retry of the same file skips the picker; without
    it every failed submit would cost another inventory and re-tick."""
    result = _run_node(
        _connect_flow_script(
            UPLOAD_PAGE,
            """
(async () => {
  loadGlobusDataset();
  await releaseEndpointCheck();
  submitError = "endpoint rejected the task";
  selectHdf5Datasets(["/a"], el("globus-hdf5-picker"));
  await tick();
  submitError = null;
  loadGlobusDataset();                    // same endpoint, path and type
  await releaseEndpointCheck();
  done({ owner: window._globusSelectedKeysFor });
})();
""",
        )
    )
    submits = [line for line in result["log"] if line.startswith("SUBMIT")]
    assert submits == [
        'SUBMIT completeness file=/data/A.h5 keys=["/a"]',
        'SUBMIT completeness file=/data/A.h5 keys=["/a"]',
    ], result["log"]
    assert len([line for line in result["log"] if line.startswith("PICKER")]) == 1, result["log"]
    assert result["owner"] == {
        "endpointId": "ep-1",
        "filePath": "/data/A.h5",
        "fileType": ".h5",
    }, result


@requires_node
def test_a_refused_clear_keeps_the_session_selection_and_shows_why():
    """401 from /globus/clear-dataset-selection: no silent reset, no wiped
    dropdowns, and the reason reaches the panel."""
    result = _run_node(
        _connect_flow_script(
            WORKSPACE_PAGE,
            """
(async () => {
  window.AIDRIN_GLOBUS_MODE = true;
  window.AIDRIN_GLOBUS_SELECTED_KEYS = ["/a"];
  clearStatus = { ok: false, body: { error: "Not authenticated with Globus" } };
  returnToHdf5DatasetPicker();
  await tick();
  done({
    keys: window.AIDRIN_GLOBUS_SELECTED_KEYS,
    panel: el("workspace-summary").innerHTML,
  });
})();
""",
        )
    )
    assert result["keys"] == ["/a"], result
    assert "Not authenticated with Globus" in result["panel"], result
    assert "DROPDOWNS CLEARED" not in result["log"], result["log"]
    assert "SUMMARY REFETCHED" not in result["log"], result["log"]


@requires_node
def test_a_successful_clear_reopens_the_picker():
    """The success path still resets and refetches, so the guard above cannot
    pass by blocking everything."""
    result = _run_node(
        _connect_flow_script(
            WORKSPACE_PAGE,
            """
(async () => {
  window.AIDRIN_GLOBUS_MODE = true;
  window.AIDRIN_GLOBUS_SELECTED_KEYS = ["/a"];
  returnToHdf5DatasetPicker();
  await tick();
  done({ keys: window.AIDRIN_GLOBUS_SELECTED_KEYS });
})();
""",
        )
    )
    assert result["keys"] == [], result
    assert "DROPDOWNS CLEARED" in result["log"], result["log"]
    assert "SUMMARY REFETCHED" in result["log"], result["log"]


@requires_node
def test_metrics_end_up_locked_while_a_dataset_selection_is_pending():
    """Returning to the picker is an unlocked-to-locked transition, so the
    classes must be present when renderGlobusSummary returns."""
    result = _run_node(
        _connect_flow_script(
            WORKSPACE_PAGE,
            """
(async () => {
  const sidebar = el("sidebar-metrics");
  sidebar.classList.remove("opacity-50", "pointer-events-none");
  renderGlobusSummary({
    needs_dataset_selection: true,
    datasets: [{ path: "/a" }],
    message: "pick datasets",
  });
  done({ classes: [...sidebar.classList.names].sort() });
})();
""",
        )
    )
    assert result["classes"] == ["opacity-50", "pointer-events-none"], result
    assert any(line.startswith("PICKER") for line in result["log"]), result["log"]


# --------------------------------------------------------------------------
# Remote task polling
# --------------------------------------------------------------------------


def _poll_script(responses):
    """`responses` is a cycle of per-call directives: "fail", or a JSON body."""
    poller = _slice(
        _source(),
        "function _globusPollTaskResult(taskId)",
        "\nfunction _globusRunRemoteMetric",
    )
    return f"""
const setTimeout = (fn) => queueMicrotask(fn);
const responses = {json.dumps(responses)};
let calls = 0;
const fetch = () => {{
  const directive = responses[calls % responses.length];
  calls++;
  if (directive === "fail") return Promise.reject(new Error("network blip"));
  return Promise.resolve({{ json: () => Promise.resolve(directive) }});
}};
{poller}
_globusPollTaskResult("task-1").then(
  (result) => process.stdout.write(JSON.stringify({{ ok: true, calls, result }})),
  (err) => process.stdout.write(
    JSON.stringify({{ ok: false, calls, error: err.message }}),
  ),
);
"""


PROCESSING = {"status": "processing"}
COMPLETED = {"status": "completed", "result": {"ok": 1}}


@requires_node
def test_remote_task_poll_retries_a_dropped_request():
    """Two failed fetches mid-poll must not abort the connect flow."""
    result = _run_node(_poll_script(["fail", "fail", COMPLETED]))
    assert result == {"ok": True, "calls": 3, "result": {"ok": 1}}, result


@requires_node
def test_remote_task_poll_gives_up_on_a_down_server():
    """A server that stays down must surface before the full attempt budget,
    or the Globus form sits disabled for minutes with no message."""
    result = _run_node(_poll_script(["fail"]))
    assert result["ok"] is False, result
    assert result["error"] == "network blip", result
    assert result["calls"] == 4, result


@requires_node
def test_occasional_blips_do_not_accumulate_into_a_give_up():
    """The give-up cap counts consecutive failures: a blip every other poll is
    a working connection and must run to the attempt budget, not fail fast."""
    result = _run_node(_poll_script(["fail", PROCESSING]))
    assert result["ok"] is False, result
    # It polled out the whole attempt budget rather than stopping at the
    # consecutive-failure cap. Which message wins depends on whether the last
    # attempt was a blip or a status read, so only the count is asserted.
    assert result["calls"] > 100, result


@requires_node
def test_a_refused_poll_is_reported_instead_of_polled_to_the_timeout():
    """401 from /globus/check-task carries an error and no status; treating it
    as 'still processing' hid it behind a four-minute timeout."""
    result = _run_node(_poll_script([{"error": "Not authenticated with Globus"}]))
    assert result["ok"] is False, result
    assert result["error"] == "Not authenticated with Globus", result
    assert result["calls"] == 1, result


# --------------------------------------------------------------------------
# Source-level guard: no behavioral coverage without a real DOM
# --------------------------------------------------------------------------


def test_picker_resolves_its_controls_inside_its_own_container():
    """The picker binds checkboxes through `container`, so its button, hint and
    error must resolve the same way: a document-wide lookup of an id the markup
    repeats per mount point would reach another picker's copy."""
    body = _slice(
        _source(),
        "function renderHdf5DatasetPicker(container, data)",
        "\nfunction selectHdf5Datasets",
    )
    for element_id in (
        "hdf5-load-selected",
        "hdf5-selection-hint",
        "hdf5-selection-error",
    ):
        assert f'container.querySelector("#{element_id}")' in body
    assert "document.getElementById(" not in body
    assert "document.querySelector" not in body
