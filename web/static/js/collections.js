"use strict";

let collectionFiles = [];
let collectionResult = null;
const collectionMessage = document.getElementById("collection-message");

document
  .getElementById("collection-clear")
  .addEventListener("click", async (event) => {
    event.target.disabled = true;
    try {
      await collectionResponse(
        await fetch("/collections/clear", { method: "POST" }),
      );
      collectionFiles = [];
      collectionResult = null;
      renderCollectionFiles();
      document.getElementById("collection-results").replaceChildren();
      document.getElementById("collection-download").classList.add("hidden");
      collectionMessage.textContent = "Collection uploads cleared.";
    } catch (error) {
      collectionMessage.textContent = error.message;
    } finally {
      event.target.disabled = false;
    }
  });

function collectionElement(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function selectedCollectionIds() {
  return Array.from(
    document.querySelectorAll("input[name='collection-file']:checked"),
    (input) => input.value,
  );
}

function renderCollectionFiles(
  selected = collectionFiles.map((file) => file.id),
) {
  const container = document.getElementById("collection-files");
  container.replaceChildren();
  if (!collectionFiles.length) container.textContent = "No files uploaded.";
  collectionFiles.forEach((file, index) => {
    const row = collectionElement(
      "div",
      undefined,
      "flex flex-wrap items-center gap-3",
    );
    const label = collectionElement("label", undefined, "flex-1");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "collection-file";
    checkbox.value = file.id;
    checkbox.checked = selected.includes(file.id);
    label.append(
      checkbox,
      document.createTextNode(` ${index + 1}. ${file.name}`),
    );
    row.append(label);
    for (const [label, step] of [
      ["Move up", -1],
      ["Move down", 1],
    ]) {
      const button = collectionElement(
        "button",
        label,
        "px-2 py-1 border rounded text-sm",
      );
      button.type = "button";
      button.disabled =
        index + step < 0 || index + step >= collectionFiles.length;
      button.setAttribute("aria-label", `${label}: ${file.name}`);
      button.addEventListener("click", () => {
        const selectedIds = selectedCollectionIds();
        [collectionFiles[index], collectionFiles[index + step]] = [
          collectionFiles[index + step],
          collectionFiles[index],
        ];
        renderCollectionFiles(selectedIds);
      });
      row.append(button);
    }
    container.append(row);
  });
  const columns = document.getElementById("collection-columns");
  columns.replaceChildren();
  const names = new Set(collectionFiles.flatMap((file) => file.columns));
  names.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    columns.append(option);
  });
}

async function collectionResponse(response) {
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || data.message || "The request failed.");
  return data;
}

document
  .getElementById("collection-upload")
  .addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.target.querySelector("button");
    button.disabled = true;
    collectionMessage.textContent = "Loading files…";
    try {
      const selected = selectedCollectionIds();
      const previous = new Set(collectionFiles.map((file) => file.id));
      const data = await collectionResponse(
        await fetch("/collections/files", {
          method: "POST",
          body: new FormData(event.target),
        }),
      );
      // Keep the user's order and selection when adding more files.
      const additions = data.files.filter((file) => !previous.has(file.id));
      collectionFiles.push(...additions);
      renderCollectionFiles([...selected, ...additions.map((file) => file.id)]);
      event.target.reset();
      collectionMessage.textContent = `${additions.length} file(s) added. Select files and configure checks.`;
    } catch (error) {
      collectionMessage.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

function collectionMetricRequests(form) {
  const selected = new FormData(form).getAll("metric");
  if (!selected.length) throw new Error("Select at least one check.");
  return selected.map((name) => {
    const request = { name };
    if (name === "grouped_time_series") {
      const groups = document
        .getElementById("collection-groups")
        .value.split(",")
        .map((value) => value.trim())
        .filter(Boolean);
      const sourceColumns = [];
      if (document.getElementById("collection-boundaries").checked) {
        sourceColumns.push("__aidrin_source_id");
        if (!groups.includes("__aidrin_source_id"))
          groups.unshift("__aidrin_source_id");
      }
      request.source_columns = sourceColumns;
      request.parameters = {
        group_columns: groups,
        timestamp_column: document
          .getElementById("collection-time")
          .value.trim(),
        expected_cadence: Number(
          document.getElementById("collection-cadence").value,
        ),
        time_kind: document.getElementById("collection-time-kind").value,
        tolerance: Number(
          document.getElementById("collection-tolerance").value,
        ),
      };
      for (const [id, key] of [
        ["collection-count", "expected_count"],
        ["collection-duration", "expected_duration"],
      ]) {
        const value = document.getElementById(id).value;
        if (value !== "") request.parameters[key] = Number(value);
      }
    }
    return request;
  });
}

function renderCollectionResult(result) {
  const container = document.getElementById("collection-results");
  container.replaceChildren();
  result.datasets.forEach((dataset, index) => {
    const section = collectionElement(
      "section",
      undefined,
      "p-4 border rounded-lg space-y-3",
    );
    const names = dataset.sources.map((source) => source.name).join(", ");
    section.append(
      collectionElement(
        "h2",
        `${index + 1}. ${names} — ${dataset.status}`,
        "text-lg font-semibold",
      ),
    );
    Object.entries(dataset.errors).forEach(([metric, message]) => {
      section.append(
        collectionElement(
          "p",
          `${metric}: ${message}`,
          "text-red-600 dark:text-red-400",
        ),
      );
    });
    Object.entries(dataset.metrics).forEach(([name, metric]) => {
      const details = document.createElement("details");
      details.append(
        collectionElement(
          "summary",
          name.replaceAll("_", " "),
          "cursor-pointer font-medium",
        ),
      );
      if (metric.format === "aidrin.grouped-time-series") {
        details.open = true;
        details.append(
          collectionElement(
            "p",
            `${metric.summary.group_count} groups; ${metric.summary.groups_with_findings} with findings; ${metric.summary.unassigned_rows} rows missing group keys.`,
          ),
        );
      }
      details.append(
        collectionElement(
          "pre",
          JSON.stringify(metric, null, 2),
          "text-xs overflow-auto max-h-96 p-3",
        ),
      );
      section.append(details);
    });
    const provenance = document.createElement("details");
    provenance.append(
      collectionElement("summary", "Source row mapping", "cursor-pointer"),
      collectionElement(
        "pre",
        JSON.stringify(dataset.sources, null, 2),
        "text-xs overflow-auto",
      ),
    );
    section.append(provenance);
    container.append(section);
  });
}

document.getElementById("collection-assess").addEventListener("change", () => {
  const enabled = document.querySelector(
    "input[name='metric'][value='grouped_time_series']",
  ).checked;
  document
    .getElementById("collection-sequence-options")
    .classList.toggle("hidden", !enabled);
  for (const id of ["collection-time", "collection-cadence"])
    document.getElementById(id).required = enabled;
});

document
  .getElementById("collection-assess")
  .addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.target.querySelector("button[type='submit']");
    button.disabled = true;
    collectionResult = null;
    document.getElementById("collection-download").classList.add("hidden");
    document.getElementById("collection-results").replaceChildren();
    collectionMessage.textContent = "Running checks…";
    try {
      const ids = selectedCollectionIds();
      if (!ids.length) throw new Error("Select at least one file.");
      const payload = {
        file_ids: ids,
        mode: new FormData(event.target).get("mode"),
        metrics: collectionMetricRequests(event.target),
      };
      collectionResult = await collectionResponse(
        await fetch("/collections/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }),
      );
      renderCollectionResult(collectionResult);
      collectionMessage.textContent = `${collectionResult.summary.datasets} dataset(s) assessed; ${collectionResult.summary.datasets_with_errors} with errors. Findings are shown separately from execution errors.`;
      document.getElementById("collection-download").classList.remove("hidden");
    } catch (error) {
      collectionMessage.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

document.getElementById("collection-download").addEventListener("click", () => {
  if (!collectionResult) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(collectionResult, null, 2)], {
      type: "application/json",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "aidrin-collection-results.json";
  link.click();
  URL.revokeObjectURL(url);
});

fetch("/collections/files")
  .then(collectionResponse)
  .then((data) => {
    collectionFiles = data.files;
    renderCollectionFiles();
  })
  .catch((error) => {
    collectionMessage.textContent = error.message;
  });
