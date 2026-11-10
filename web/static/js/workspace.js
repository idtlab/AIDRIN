async function fetchWorkspaceDataset(url, options = {}) {
  const fileId =
    document.getElementById("panels-container")?.dataset.workspaceFileId;
  if (!fileId || new URL(url, location.href).origin !== location.origin)
    return fetch(url, options);
  const headers = new Headers(options.headers);
  headers.set("X-AIDRIN-Workspace-File", fileId);
  const response = await fetch(url, { ...options, headers });
  if (response.headers.has("X-AIDRIN-Workspace-Stale")) {
    throw new Error((await response.json()).message);
  }
  return response;
}

function filterWorkspaceFiles(search) {
  const query = search.value.trim().toLowerCase();
  search
    .closest("details")
    .querySelectorAll("[data-workspace-option]")
    .forEach((row) => {
      row.hidden = !row.textContent.toLowerCase().includes(query);
    });
}

async function loadWorkspaceOverview() {
  const panel = document.getElementById("panel-batch-overview");
  if (!panel || panel.dataset.loaded) return;
  panel.dataset.loaded = "true";
  const status = document.getElementById("workspace-batch-status");
  status.textContent = "Loading file summaries…";
  try {
    const response = await fetch(panel.dataset.summaryUrl);
    if (!response.ok) throw new Error("Could not load file summaries.");
    const { files, totals } = await response.json();
    const count = files.length;
    const failed = files.filter((file) => file.error).length;
    const number = new Intl.NumberFormat();
    const size = (bytes) => `${number.format(bytes)} bytes`;
    status.textContent = [
      `${count} ${count === 1 ? "file" : "files"}`,
      `${number.format(totals.records)} rows counted`,
      files.some((file) => file.size == null)
        ? `${size(totals.size)} counted`
        : size(totals.size),
      failed ? `${failed} without a summary` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    const summaries = new Map(files.map((file) => [file.id, file]));
    for (const row of panel.querySelectorAll("[data-workspace-file]")) {
      const file = summaries.get(row.dataset.workspaceFile);
      if (!file) continue;
      for (const cell of row.querySelectorAll("[data-workspace-column]")) {
        const key = cell.dataset.workspaceColumn;
        const value = file[key];
        if (value != null) {
          cell.textContent =
            key === "size"
              ? size(value)
              : typeof value === "number"
                ? number.format(value)
                : value;
        }
      }
    }
  } catch (error) {
    delete panel.dataset.loaded;
    status.textContent =
      "Could not load file summaries. Reopen Batch Overview to retry.";
  }
}

function syncCollectionSelection() {
  const selection = document.getElementById("collection-selection");
  if (!selection) return;
  const form = selection.form;
  const checked = [
    ...form.querySelectorAll(
      '.material-checkbox input[type="checkbox"]:checked',
    ),
  ];
  const eligible = checked.some((input) =>
    input.hasAttribute("data-collection-metric"),
  );
  selection.hidden = !eligible;
  selection.disabled = !eligible;
  const scope = document.getElementById("collection-scope").value;
  const mode = document.getElementById("collection-mode").value;
  const settings = document.getElementById("collection-settings");
  settings.hidden = scope === "active";
  document.getElementById("collection-mode").disabled = settings.hidden;
  document.getElementById("collection-scope-note").hidden = !checked.some(
    (input) => !input.hasAttribute("data-collection-metric"),
  );
  document.getElementById("collection-file-actions").hidden =
    scope !== "selected";
  const fileList = document.getElementById("collection-file-list");
  fileList.hidden =
    scope === "active" || (scope === "all" && mode !== "stacked");
  for (const row of fileList.children) {
    const checkbox = row.querySelector('input[type="checkbox"]');
    checkbox.disabled = scope !== "selected";
    checkbox.hidden = checkbox.disabled;
    row.querySelector('input[type="hidden"]').disabled = scope !== "all";
    for (const button of row.querySelectorAll("[data-move-file]")) {
      button.hidden = mode !== "stacked";
      button.disabled =
        button.dataset.moveFile === "-1"
          ? !row.previousElementSibling
          : !row.nextElementSibling;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("form-data-quality");
  const selection = document.getElementById("collection-selection");
  if (!selection) return;
  form.addEventListener("change", syncCollectionSelection);
  selection.addEventListener("click", (event) => {
    const bulk = event.target.closest("[data-select-collection-files]");
    const move = event.target.closest("[data-move-file]");
    if (bulk) {
      for (const checkbox of selection.querySelectorAll(
        '[name="collection_file_id"]',
      )) {
        checkbox.checked = bulk.dataset.selectCollectionFiles === "all";
      }
    } else if (move) {
      const row = move.closest("[data-collection-file]");
      if (move.dataset.moveFile === "-1")
        row.previousElementSibling?.before(row);
      else row.nextElementSibling?.after(row);
    } else {
      return;
    }
    selection.dispatchEvent(new Event("change", { bubbles: true }));
  });
  syncCollectionSelection();
});

function renderWorkspaceCollection(result) {
  const stacked = result.mode === "stacked";
  const count = result.summary.selected_files;
  const scope = `${stacked ? "Stacked rows" : "Independent"} · ${count} ${count === 1 ? "file" : "files"}`;
  let html = `<p class="mb-2 text-sm">${escapeHtml(scope)}</p>`;
  if (stacked) {
    html +=
      '<details class="mb-2 text-sm"><summary class="cursor-pointer">Source rows in stack order</summary><ol class="list-decimal pl-5">';
    for (const source of result.datasets[0].sources) {
      const row = `${source.name} · ${source.row_count} rows starting at data row ${source.start_row + 1}`;
      html += `<li>${escapeHtml(row)}</li>`;
    }
    html += "</ol></details>";
  }
  for (const dataset of result.datasets) {
    const name = stacked ? "Stacked dataset" : dataset.sources[0].name;
    html += `<details class="mb-2 rounded border border-gray-200 p-3 dark:border-gray-700" ${stacked || result.datasets.length === 1 ? "open" : ""}>
      <summary class="cursor-pointer font-medium">${escapeHtml(name)}${dataset.status !== "ok" ? " · Check errors" : ""}</summary>`;
    for (const [metric, values] of Object.entries(dataset.metrics)) {
      html += `<section class="mt-3"><h4 class="mb-2 font-medium">${escapeHtml(prettyResultTitle(metric))}</h4>${renderScoresSection(values)}</section>`;
    }
    for (const [metric, error] of Object.entries(dataset.errors)) {
      html += `<p class="mt-2 text-sm text-red-700 dark:text-red-400">${escapeHtml(`${prettyResultTitle(metric)}: ${error}`)}</p>`;
    }
    html += "</details>";
  }
  return html;
}

async function importGlobusDirectory() {
  const button = document.getElementById("globus-import-directory");
  const status = document.getElementById("globus-import-status");
  const endpoint = document.getElementById("globus-endpoint-id");
  const path = document.getElementById("globus-file-path");
  const directory = path.value.trim();
  const endpointId = endpoint.value.trim();
  if (!directory || !endpointId) {
    status.textContent = "Enter an endpoint and a directory path.";
    (endpointId ? path : endpoint).focus();
    return;
  }

  const controls = [...button.form.querySelectorAll("button, input, select")];
  for (const control of controls) control.disabled = true;
  status.textContent = "Finding and summarizing files on the Compute endpoint…";
  try {
    const response = await fetch("/globus/import-directory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint_id: endpointId, directory }),
    });
    const started = await response.json();
    if (!response.ok)
      throw new Error(started.error || "Unable to start directory discovery.");
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      const poll = await fetch(
        `/globus/check-task/${encodeURIComponent(started.task_id)}`,
      );
      const result = await poll.json();
      if (!poll.ok || result.status === "failed")
        throw new Error(result.error || "Unable to import the directory.");
      if (result.status === "completed") {
        window.history.replaceState(null, "", "/inspector#batch-overview");
        window.location.reload();
        return;
      }
    }
  } catch (error) {
    status.textContent = error.message;
    for (const control of controls) control.disabled = false;
  }
}

function restoreCollectionSelection(state) {
  const list = document.getElementById("collection-file-list");
  const order =
    state.collection_scope === "all"
      ? state.collection_file_order
      : state.collection_file_id;
  if (list && order) {
    const ids = Array.isArray(order) ? order : [order];
    const rows = new Map(
      [...list.children].map((row) => [
        row.querySelector('[name="collection_file_id"]').value,
        row,
      ]),
    );
    list.prepend(...ids.map((id) => rows.get(id)).filter(Boolean));
  }
  syncCollectionSelection();
}
