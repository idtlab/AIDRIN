/**
 * inspector.js — Single-page inspector logic for AIDRIN
 *
 * Handles: panel switching, sidebar toggling, parameterized form submission,
 * FAIR assessment submission, CodeMirror lazy init, and inspector initialization.
 */

// ==================== Panel Switching ====================

let activePanel = "data-overview";
let codeMirrorEditor = null;
let lastMetricResult = null; // Store last result for JSON download

/**
 * Show a metric panel by ID, hiding all others.
 * @param {string} panelId - The panel name (e.g., 'data-quality', 'fairness')
 * @param {boolean} pushHistory - Whether to push a new history entry (default true).
 *                                Set to false when restoring from popstate to avoid loops.
 */
function showPanel(panelId, pushHistory) {
  if (pushHistory === undefined) pushHistory = true;

  // Validate the panel exists, fall back to data-overview
  const panel = document.getElementById("panel-" + panelId);
  if (!panel) panelId = "data-overview";
  const validPanel = document.getElementById("panel-" + panelId);

  // Hide all panels
  document.querySelectorAll(".metric-panel").forEach((p) => {
    p.classList.add("hidden");
  });

  // Show the selected panel
  if (validPanel) {
    validPanel.classList.remove("hidden");
    activePanel = panelId;
  }

  // Hide results from previous metric and reset
  const resultsSection = document.getElementById("results-section");
  if (resultsSection) resultsSection.style.display = "none";
  const metricsDiv = document.getElementById("metrics");
  if (metricsDiv) metricsDiv.innerHTML = "";
  const buttonsContainer = document.getElementById("buttonsContainer");
  if (buttonsContainer) buttonsContainer.style.display = "none";

  // Check for cached results and restore them
  _restoreCachedResult(panelId);

  // Highlight active sidebar item
  document.querySelectorAll(".sidebar-metric-item").forEach((btn) => {
    btn.classList.remove("bg-black/10", "dark:bg-white/10", "font-semibold");
  });

  // Update URL hash and browser history
  if (pushHistory && location.hash !== "#" + panelId) {
    history.pushState({ panel: panelId }, "", "#" + panelId);
  }

  // Lazy init CodeMirror for custom metrics
  if (panelId === "custom-metrics" && !codeMirrorEditor) {
    initCodeMirror();
  }

  // Close mobile sidebar after selection
  const sidebar = document.getElementById("sidebar");
  if (sidebar && window.innerWidth < 640) {
    sidebar.classList.add("-translate-x-full");
  }
}

// Panel ID → backend cache metric name mapping
const _panelCacheMap = {
  "data-quality": "data_quality",
  fairness: "fairness",
  "correlation-analysis": "correlation_analysis",
  "feature-relevance": "feature_relevance",
  "class-imbalance": "class_imbalance",
  "privacy-preservation": "privacy_preservation",
  "hipaa-compliance": "hipaa_compliance",
};

/**
 * Check if there are cached results for the given panel and display them.
 */
function _restoreCachedResult(panelId) {
  const metricName = _panelCacheMap[panelId];
  if (!metricName) return; // no caching for data-overview, fair-assessment, custom-metrics

  // Restore form state from sessionStorage
  const savedForm = sessionStorage.getItem("aidrin_form_" + panelId);
  if (savedForm) {
    try {
      _restoreFormState(panelId, JSON.parse(savedForm));
    } catch (e) {
      debugLog("Form restore error:", e);
    }
  }

  fetch("/cached-result/" + metricName)
    .then((r) => r.json())
    .then((resp) => {
      if (resp.cached && resp.data && activePanel === panelId) {
        lastMetricResult = resp.data;
        const resultsSection = document.getElementById("results-section");
        if (resultsSection) resultsSection.style.display = "block";
        const hasLLMCache =
          resp.llm_explanations &&
          Object.keys(resp.llm_explanations).length > 0;
        renderWorkspaceResults(resp.data, { skipLLM: hasLLMCache });

        // Restore cached LLM explanations instead of re-calling the LLM
        if (hasLLMCache) {
          setTimeout(() => {
            _restoreLLMExplanations(resp.llm_explanations);
          }, 200);
        }
      }
    })
    .catch((err) => debugLog("Cache restore error:", err));
}

/**
 * Restore cached LLM explanations into already-rendered result cards.
 * Finds LLM placeholder divs and fills them with the cached text,
 * preventing duplicate LLM API calls.
 */
function _restoreLLMExplanations(explanations) {
  // Find all LLM placeholder containers in the results
  const containers = document.querySelectorAll('[id^="llm-"]');
  containers.forEach((container) => {
    // The container was placed after a result card whose type is in the heading
    const card = container.closest(
      ".p-5.mb-4.bg-white, .p-5.mb-4.dark\\:bg-gray-800",
    );
    if (!card) return;
    const heading = card.querySelector("h3");
    if (!heading) return;
    const resultType = heading.textContent.trim();

    if (explanations[resultType]) {
      const cached = explanations[resultType];
      _renderLLMCallout(container, cached.explanation, cached.model);
    }
  });
}

/**
 * Restore form inputs from a saved state object.
 */
function _restoreFormState(panelId, state) {
  const panel = document.getElementById("panel-" + panelId);
  if (!panel) return;

  for (const [key, value] of Object.entries(state)) {
    if (!value) continue;

    // Checkboxes with name matching the key
    const checkboxes = panel.querySelectorAll(
      `input[type="checkbox"][name="${key}"]`,
    );
    if (checkboxes.length > 0) {
      const values = Array.isArray(value) ? value : [value];
      checkboxes.forEach((cb) => {
        cb.checked = values.includes(cb.value);
      });
      continue;
    }

    // Select dropdowns
    const select = panel.querySelector(`select[name="${key}"]`);
    if (select) {
      // Handle multi-select
      if (select.multiple) {
        const values = typeof value === "string" ? value.split(",") : [value];
        Array.from(select.options).forEach((opt) => {
          opt.selected = values.includes(opt.value);
        });
      } else {
        select.value = value;
      }
      continue;
    }

    // Text/hidden inputs
    const input = panel.querySelector(
      `input[name="${key}"]:not([type="checkbox"])`,
    );
    if (input) {
      input.value = value;
    }
  }
}

// Handle browser back/forward buttons
window.addEventListener("popstate", function (e) {
  if (e.state && e.state.panel) {
    showPanel(e.state.panel, false);
  } else {
    // Read from hash or fall back to data-overview
    const hash = location.hash.replace("#", "");
    showPanel(hash || "data-overview", false);
  }
});

// ==================== Sidebar Toggle ====================

/**
 * Toggle a sidebar pillar group open/closed.
 * @param {string} groupId - The ID of the <ul> element to toggle
 */
function toggleSidebarGroup(groupId) {
  const group = document.getElementById(groupId);
  if (!group) return;

  group.classList.toggle("hidden");

  // Rotate arrow
  const arrow = document.getElementById(groupId + "-arrow");
  if (arrow) {
    arrow.classList.toggle("rotate-180");
  }
}

// Mobile sidebar toggle
document.addEventListener("DOMContentLoaded", function () {
  const sidebarToggle = document.getElementById("sidebar-toggle");
  const sidebar = document.getElementById("sidebar");
  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener("click", function () {
      sidebar.classList.toggle("-translate-x-full");
    });
  }
});

// ==================== Form Submission ====================

/**
 * Prevent duplicate submissions while a request is already in flight (issue #108).
 * Disables the button and adds an `.is-submitting` class for the duration of the
 * returned promise, restoring everything in `.finally()` so it recovers on both
 * success and error. Handlers that return `undefined` (early validation returns)
 * release the guard in the next microtask.
 *
 * @param {HTMLElement|null} button - The button that was clicked.
 * @param {Function} taskFn - Submit function; should `return` its fetch promise.
 * @returns {Promise|undefined} The guarded task promise, or `undefined` if a
 *   submission for this button is already running.
 */
function withSubmitGuard(button, taskFn) {
  if (!button) {
    // No button to guard against; just run the task.
    return Promise.resolve().then(taskFn);
  }
  if (button.dataset.submitting === "true") {
    // A request triggered by this button is already running — ignore the click.
    return;
  }
  button.dataset.submitting = "true";
  // Capture the live text color so the spinner inherits the theme (works for
  // dark/light mode, blue-on-white buttons, etc.) — the label is hidden via
  // `color: transparent` in `.is-submitting`, so currentColor alone wouldn't
  // do (it would be transparent too).
  button.style.setProperty(
    "--aidrin-spinner-color",
    getComputedStyle(button).color,
  );
  button.disabled = true;
  button.classList.add("is-submitting");

  return Promise.resolve()
    .then(taskFn)
    .finally(() => {
      button.dataset.submitting = "false";
      button.disabled = false;
      button.classList.remove("is-submitting");
      button.style.removeProperty("--aidrin-spinner-color");
    });
}

/**
 * Submit a metric form to a specific URL from the workspace.
 * Wraps the existing submitForm() logic but POSTs to a parameterized URL.
 * @param {string} targetUrl - The metric endpoint URL (e.g., '/data-quality')
 */
function workspaceSubmit(targetUrl) {
  // Clear previous results before submitting new ones
  const resultsSection = document.getElementById("results-section");
  if (resultsSection) resultsSection.style.display = "none";
  const metricsDiv = document.getElementById("metrics");
  if (metricsDiv) metricsDiv.innerHTML = "";
  const buttonsContainer = document.getElementById("buttonsContainer");
  if (buttonsContainer) buttonsContainer.style.display = "none";

  // In Globus mode, route through Globus Compute instead of local endpoint
  if (window.AIDRIN_GLOBUS_MODE) {
    const gPanel = document.getElementById("panel-" + activePanel);
    const gForm = gPanel ? gPanel.querySelector("form") : null;
    const gFormData = gForm ? new FormData(gForm) : new FormData();

    // Map route URLs to remote_metric_runner metric names
    const urlToMetrics = {
      "/data-quality": ["completeness", "outliers", "duplicates"],
      "/fairness": ["representation_rate", "statistical_rates"],
      "/feature-relevance": ["feature_relevance"],
      "/correlation-analysis": ["correlations"],
      "/class-imbalance": ["class_distribution"],
      "/privacy-preservation": [
        "k_anonymity",
        "l_diversity",
        "t_closeness",
        "entropy_risk",
      ],
      "/hipaa-compliance": ["hipaa"],
    };

    let remoteName = urlToMetrics[targetUrl]
      ? urlToMetrics[targetUrl][0]
      : targetUrl.replace("/", "");
    let remoteParams = {};
    let remoteDisplayName = "";

    // Map metric names to display names
    const metricDisplayMap = {
      completeness: "Completeness",
      outliers: "Outliers",
      duplicates: "Duplicity",
      representation_rate: "Representation Rate",
      statistical_rates: "Statistical Rate",
      feature_relevance: "Feature Relevance",
      correlations: "Correlation Analysis",
      class_distribution: "Class Imbalance",
      k_anonymity: "k-Anonymity",
      l_diversity: "l-Diversity",
      t_closeness: "t-Closeness",
      entropy_risk: "Entropy Risk",
      hipaa: "HIPAA Compliance",
    };

    if (targetUrl === "/data-quality") {
      remoteName = "data_quality";
      const selected = [];
      const selectedNames = [];
      if (gFormData.get("completeness") === "yes") {
        selected.push("completeness");
        selectedNames.push("Completeness");
      }
      if (gFormData.get("outliers") === "yes") {
        selected.push("outliers");
        selectedNames.push("Outliers");
      }
      if (gFormData.get("duplicity") === "yes") {
        selected.push("duplicates");
        selectedNames.push("Duplicity");
      }
      if (selected.length === 0) {
        if (typeof showToast === "function")
          showToast("Please select at least one metric", "error");
        return;
      }
      remoteParams = { selected: selected };
      remoteDisplayName = selectedNames.join(", ");
    } else if (targetUrl === "/feature-relevance") {
      remoteName = "feature_relevance";
      remoteDisplayName = "Feature Relevance";
      // Collect selected features and target from the form
      const catCols = Array.from(
        gFormData.getAll("categorical features for feature relevancy"),
      ).join(",");
      const numCols = Array.from(
        gFormData.getAll("numerical features for feature relevancy"),
      ).join(",");
      const target = gFormData.get("target for feature relevance");
      if (!target) {
        if (typeof showToast === "function")
          showToast("Please select a target feature", "error");
        return;
      }
      remoteParams = {
        target_col: target,
        cat_cols: catCols ? catCols.split(",") : [],
        num_cols: numCols ? numCols.split(",") : [],
      };
    } else if (targetUrl === "/correlation-analysis") {
      remoteName = "correlations";
      remoteDisplayName = "Correlation Analysis";
      const catCols = Array.from(
        gFormData.getAll("categorical features for correlation analysis"),
      ).join(",");
      const numCols = Array.from(
        gFormData.getAll("numerical features for correlation analysis"),
      ).join(",");
      const columns = (catCols ? catCols.split(",") : []).concat(
        numCols ? numCols.split(",") : [],
      );
      remoteParams = { columns: columns };
    } else if (targetUrl === "/fairness") {
      remoteName = "fairness";
      const selectedFairness = [];
      const selectedNames = [];
      remoteParams = { selected: [] };

      if (gFormData.get("representation rate") === "yes") {
        remoteParams.selected.push("representation_rate");
        remoteParams.rep_columns = [
          gFormData.get("features for representation rate"),
        ];
        selectedNames.push("Representation Rate");
      }
      if (gFormData.get("statistical rate") === "yes") {
        remoteParams.selected.push("statistical_rates");
        remoteParams.sensitive_attr = gFormData.get(
          "features for statistical rate",
        );
        remoteParams.y_true = gFormData.get("target for statistical rate");
        selectedNames.push("Statistical Rate");
      }
      if (remoteParams.selected.length === 0) {
        if (typeof showToast === "function")
          showToast("Please select at least one metric", "error");
        return;
      }
      remoteDisplayName = selectedNames.join(", ");
    } else if (targetUrl === "/class-imbalance") {
      remoteName = "class_distribution";
      remoteDisplayName = "Class Imbalance";
      remoteParams = {
        column: gFormData.get("target features for class imbalance"),
      };
    } else if (targetUrl === "/privacy-preservation") {
      // Privacy has multiple sub-metrics — check which are selected
      // For now, run k-anonymity if selected (most common)
      if (gFormData.get("k-anonymity") === "yes") {
        remoteName = "k_anonymity";
        remoteDisplayName = "k-Anonymity";
        remoteParams = {
          quasi_ids: Array.from(
            gFormData.getAll("quasi identifiers for k-anonymity"),
          ),
        };
      } else if (gFormData.get("l-diversity") === "yes") {
        remoteName = "l_diversity";
        remoteDisplayName = "l-Diversity";
        remoteParams = {
          quasi_ids: Array.from(
            gFormData.getAll("quasi identifiers for l-diversity"),
          ),
          sensitive_col: gFormData.get("sensitive attribute for l-diversity"),
        };
      } else if (gFormData.get("t-closeness") === "yes") {
        remoteName = "t_closeness";
        remoteDisplayName = "t-Closeness";
        remoteParams = {
          quasi_ids: Array.from(
            gFormData.getAll("quasi identifiers for t-closeness"),
          ),
          sensitive_col: gFormData.get("sensitive attribute for t-closeness"),
        };
      } else if (gFormData.get("entropy risk") === "yes") {
        remoteName = "entropy_risk";
        remoteDisplayName = "Entropy Risk";
        remoteParams = {
          quasi_ids: Array.from(
            gFormData.getAll("quasi identifiers for entropy risk"),
          ),
        };
      }
    } else {
      remoteDisplayName = metricDisplayMap[remoteName] || remoteName;
    }

    submitGlobusMetric(remoteName, remoteParams, remoteDisplayName);
    return;
  }

  // Local mode: find the active form
  const panel = document.getElementById("panel-" + activePanel);
  if (!panel) return;

  const form = panel.querySelector("form");
  if (!form) return;

  const formData = new FormData(form);

  // Replicate main.js submitForm() field name remapping:
  // The backend expects short names for multi-value checkbox fields,
  // but the form uses longer descriptive names. Concatenate and remap.
  const fieldRemaps = {
    "numerical features for feature relevancy": "numerical features",
    "categorical features for feature relevancy": "categorical features",
    "numerical features for correlation analysis": "numerical features",
    "categorical features for correlation analysis": "categorical features",
    checkboxValues: "correlation columns",
  };

  // Collect multi-value checkbox fields and remap them
  const collectedMulti = {};
  for (const [longName, shortName] of Object.entries(fieldRemaps)) {
    const values = formData.getAll(longName);
    if (values.length > 0) {
      collectedMulti[shortName] = values.join(",");
    }
  }

  // Build processed form data
  const processedFormData = new FormData();
  const remapLongNames = new Set(Object.keys(fieldRemaps));
  for (const [key, value] of formData.entries()) {
    // Skip empty file inputs
    if (form.querySelector(`input[type="file"][name="${key}"]`) && !value.name)
      continue;
    // Skip fields that will be remapped
    if (remapLongNames.has(key)) continue;
    processedFormData.append(key, value);
  }
  // Add remapped fields
  for (const [shortName, joined] of Object.entries(collectedMulti)) {
    processedFormData.set(shortName, joined);
  }

  // Save form state for cache restore
  try {
    const formState = {};
    for (const [key, value] of formData.entries()) {
      if (formState[key]) {
        // Multi-value: convert to array
        if (!Array.isArray(formState[key])) formState[key] = [formState[key]];
        formState[key].push(value);
      } else {
        formState[key] = value;
      }
    }
    sessionStorage.setItem(
      "aidrin_form_" + activePanel,
      JSON.stringify(formState),
    );
  } catch (e) {
    debugLog("Form state save error:", e);
  }

  // Show the results section and set loading state
  if (resultsSection) resultsSection.style.display = "block";

  _beginServerProcessing();
  _setSubmitButtonsDisabled(true);

  const resultsContainer = document.getElementById("metrics");
  if (resultsContainer) {
    resultsContainer.innerHTML = `
      <div class="text-center py-8">
        <div role="status" class="inline-block">
          <svg class="w-8 h-8 text-gray-200 animate-spin dark:text-gray-600 fill-blue-600" viewBox="0 0 100 101"><path d="M100 50.59c0 27.61-22.39 50-50 50S0 78.2 0 50.59 22.39.59 50 .59s50 22.39 50 50zm-90.92 0c0 22.6 18.32 40.92 40.92 40.92s40.92-18.32 40.92-40.92S72.6 9.67 50 9.67 9.08 28 9.08 50.59z" fill="currentColor"/><path d="M93.97 39.04c2.43-.64 3.93-3.13 3.04-5.5A50 50 0 0048.44.58c-2.5.23-4.21 2.53-3.73 5l.02.1a3.89 3.89 0 004.57 3.13A41.1 41.1 0 0188.18 37.2a3.88 3.88 0 005.79 1.84z" fill="currentFill"/></svg>
        </div>
        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">Processing metric...</p>
      </div>`;
  }

  // POST to the metric endpoint.
  // Return the promise so withSubmitGuard re-enables the button when it settles.
  return fetch(targetUrl + "?return_type=json", {
    method: "POST",
    body: processedFormData,
  })
    .then((response) => {
      if (response.ok) {
        return response.json();
      } else {
        throw new Error(`Unexpected response from server (${response.status})`);
      }
    })
    .then((data) => {
      // Store for download
      lastMetricResult = data;

      // Handle special error formats from some endpoints (feature relevance, correlation)
      if (data.trigger === "correlationError") {
        const msg = data.error || "An error occurred with the analysis";
        console.error("[inspector] correlationError:", msg);
        const m = document.getElementById("metrics");
        if (m)
          m.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">${msg}</div>`;
        _setSubmitButtonsDisabled(false);
        _endServerProcessing();
        return;
      }
      if (data.message && !data.trigger && Object.keys(data).length <= 2) {
        const m = document.getElementById("metrics");
        if (m)
          m.innerHTML = `<div class="p-4 text-sm text-yellow-800 rounded-lg bg-yellow-50 dark:bg-yellow-900/20 dark:text-yellow-300" role="alert">${data.message}</div>`;
        _setSubmitButtonsDisabled(false);
        _endServerProcessing();
        return;
      }

      // Render sync results first (sets innerHTML), then start async polling (appends)
      renderWorkspaceResults(data);
      // handleAsyncResults acquires one processing token per async task; release
      // this request's own token unconditionally so the count reflects only the
      // tasks still running (the last task to finish re-enables Clear session).
      handleAsyncResults(data);
      if (!_responseHasAsyncTasks(data)) {
        _setSubmitButtonsDisabled(false);
      }
      _endServerProcessing();
    })
    .catch((error) => {
      console.error("Error:", error);
      const m = document.getElementById("metrics");
      if (m)
        m.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">${error.message || String(error)}</div>`;
      _setSubmitButtonsDisabled(false);
      _endServerProcessing();
    });
}

/**
 * Render metric results in a two-column layout.
 * Left column: visualization image. Right column: description + scores table.
 * Falls back to single column if no visualization.
 */
function renderWorkspaceResults(data, options) {
  const skipLLM = options && options.skipLLM;
  const metrics = document.getElementById("metrics");
  if (!metrics) return;

  let html = "";

  for (const [type, results] of Object.entries(data)) {
    if (typeof results !== "object" || results === null) continue;

    // Skip async tasks — they're handled by handleAsyncResults/pollAsyncMetric
    if (results.is_async && results.task_id) continue;

    // Extract parts
    const description = results.Description || "";
    const error = results.Error || "";
    const visualizations = [];
    const scores = {};

    for (const [key, value] of Object.entries(results)) {
      if (
        key === "Description" ||
        key === "Error" ||
        key === "Graph interpretation"
      )
        continue;
      if (
        key.toLowerCase().includes("visualization") &&
        typeof value === "string" &&
        value.length > 100
      ) {
        visualizations.push({
          key,
          src: value.startsWith("data:")
            ? value
            : `data:image/png;base64,${value}`,
        });
      } else {
        scores[key] = value;
      }
    }

    // Skip empty result cards (no viz, no scores, no error)
    const hasViz = visualizations.length > 0;
    const hasScores = Object.keys(scores).length > 0;
    if (!hasViz && !hasScores && !error) continue;

    // Card wrapper — Flowbite card
    html += `<div class="p-5 mb-4 bg-white border border-gray-200 rounded-lg shadow-sm dark:bg-gray-800 dark:border-gray-700">`;

    // Header
    html += `<h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">${type}</h3>`;

    if (error) {
      html += `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">${error}</div>`;
    } else {
      if (description) {
        html += `<p class="text-sm text-gray-600 dark:text-gray-400 mb-4 leading-relaxed">${description}</p>`;
      }

      // Graph interpretation — rendered as a distinct callout below the plot/scores
      const interpretation = results["Graph interpretation"];

      // Two-column layout: visualization | scores
      const pairId = "result-pair-" + Math.random().toString(36).substr(2, 6);

      if (hasViz || hasScores) {
        html += `<div class="grid gap-4" style="grid-template-columns: ${hasViz && hasScores ? "1fr 1fr" : "1fr"};">`;

        // Left: visualizations
        if (hasViz) {
          html += `<div class="flex flex-col items-center gap-4">`;
          for (const viz of visualizations) {
            const isHeatmap = /correlation|heatmap/i.test(viz.key);
            const imgStyle = isHeatmap
              ? ' style="max-width:500px; max-height:500px; object-fit:contain;"'
              : "";
            html += `<img src="${viz.src}" alt="${viz.key}" class="rounded-lg ${isHeatmap ? "" : "w-full"}"${imgStyle} data-pair="${pairId}" onload="syncScoresHeight('${pairId}')" />`;
          }
          html += `</div>`;
        }

        // Right: scores (height synced to plot via JS)
        if (hasScores) {
          html += `<div id="${pairId}-scores" class="overflow-auto" style="min-height: 400px; max-height: 500px;">`;
          html += renderScoresSection(scores);
          html += `</div>`;
        }

        html += `</div>`; // close grid
      }

      // Graph interpretation callout (if present)
      if (
        interpretation &&
        typeof interpretation === "string" &&
        !interpretation.includes("No visualization available")
      ) {
        html += `<div class="flex items-start gap-2.5 p-4 mt-4 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50">
          <svg class="w-5 h-5 shrink-0 mt-0.5 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z"/></svg>
          <div>
            <div class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">Interpretation</div>
            <p class="text-gray-700 dark:text-gray-300 leading-relaxed">${interpretation}</p>
          </div>
        </div>`;
      }

      // AI Explanation placeholder (filled async if LLM is configured)
      if (window.AIDRIN_LLM_ENABLED && (hasViz || hasScores)) {
        const llmId = "llm-" + pairId;
        html += `<div id="${llmId}" class="mt-3"></div>`;
        if (!skipLLM) {
          // Schedule async LLM call after DOM is updated
          const _llmType = type,
            _llmDesc = description,
            _llmViz = [...visualizations],
            _llmScores = { ...scores };
          setTimeout(() => {
            requestLLMExplanation(
              llmId,
              _llmType,
              _llmDesc,
              _llmViz,
              _llmScores,
            );
          }, 100);
        }
      }

      // Raw JSON toggle
      const rawJson = {};
      for (const [k, v] of Object.entries(results)) {
        if (!k.toLowerCase().includes("visualization")) rawJson[k] = v;
      }
      html += `<details class="mt-4 border-t border-gray-200 dark:border-gray-700 pt-3">`;
      html += `<summary class="cursor-pointer inline-flex items-center gap-1.5 text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors">`;
      html += `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/></svg>`;
      html += `View raw JSON</summary>`;
      html += `<pre class="mt-2 p-4 bg-gray-50 dark:bg-gray-900 rounded-lg text-xs text-gray-700 dark:text-gray-300 overflow-auto" style="max-height: 300px; white-space: pre-wrap; word-break: break-word;">${escapeHtml(JSON.stringify(rawJson, null, 2))}</pre>`;
      html += `</details>`;
    }

    html += `</div>`; // close card
  }

  // Don't show "no results" if there are async tasks being polled
  const hasAsync = Object.values(data).some(
    (r) => typeof r === "object" && r !== null && r.is_async,
  );
  if (!html && !hasAsync) {
    html =
      '<p class="text-center text-sm py-4" style="color: var(--textColorSecondary);">No results returned.</p>';
  }

  metrics.innerHTML = html;

  const buttonsContainer = document.getElementById("buttonsContainer");
  if (buttonsContainer) buttonsContainer.style.display = "flex";
}

/**
 * Render scores section. Detects structure and picks the best layout:
 * - Flat dict of {key: primitive} → compact key-value table
 * - Nested dict → collapsible tree with indented sections
 * - Array → numbered list
 * - Scalar → inline value
 */
function renderScoresSection(scores, depth) {
  depth = depth || 0;
  let html = "";

  for (const [key, value] of Object.entries(scores)) {
    // Flat dict of {feature: number} → Flowbite striped table
    if (isObject(value) && isFlatDict(value) && Object.keys(value).length > 0) {
      const count = Object.keys(value).length;
      html += `<div class="mb-4">`;
      if (depth === 0) {
        html += `<h4 class="text-xs font-semibold mb-2 uppercase tracking-wider text-gray-500 dark:text-gray-400">${key} <span class="normal-case font-normal">(${count})</span></h4>`;
      }
      html += `<div class="relative overflow-x-auto rounded-lg shadow-sm">`;
      html += `<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">`;
      html += `<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400"><tr>`;
      html += `<th scope="col" class="px-4 py-2.5">Name</th>`;
      html += `<th scope="col" class="px-4 py-2.5 text-right">Value</th>`;
      html += `</tr></thead><tbody>`;
      let rowIdx = 0;
      for (const [k, v] of Object.entries(value)) {
        const stripe =
          rowIdx % 2 === 0
            ? "bg-white dark:bg-gray-800"
            : "bg-gray-50 dark:bg-gray-700/50";
        html += `<tr class="${stripe} border-b dark:border-gray-700">`;
        html += `<td class="px-4 py-2 font-medium text-gray-900 dark:text-white whitespace-nowrap">${k}</td>`;
        html += `<td class="px-4 py-2 text-right font-mono text-xs">${formatValue(v)}</td>`;
        html += `</tr>`;
        rowIdx++;
      }
      html += `</tbody></table></div></div>`;
    }
    // Nested dict → collapsible Flowbite accordion-style section
    else if (isObject(value) && Object.keys(value).length > 0) {
      const isDeep = Object.values(value).some((v) => isObject(v));
      if (isDeep || Object.keys(value).length > 5) {
        html += `<details class="mb-3 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden" ${depth === 0 ? "open" : ""}>`;
        html += `<summary class="cursor-pointer flex items-center justify-between px-4 py-2.5 text-sm font-medium text-gray-900 dark:text-white bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors">`;
        html += `${key}<svg class="w-3 h-3 shrink-0 ml-2" viewBox="0 0 10 6"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M1 1l4 4 4-4"/></svg>`;
        html += `</summary>`;
        html += `<div class="p-4 border-t border-gray-200 dark:border-gray-700">`;
        html += renderScoresSection(value, depth + 1);
        html += `</div></details>`;
      } else {
        html += `<div class="mb-4">`;
        html += `<h4 class="text-xs font-semibold mb-2 uppercase tracking-wider text-gray-500 dark:text-gray-400">${key}</h4>`;
        html += renderScoresSection(value, depth + 1);
        html += `</div>`;
      }
    }
    // Array
    else if (Array.isArray(value)) {
      html += `<div class="mb-4">`;
      html += `<h4 class="text-xs font-semibold mb-2 uppercase tracking-wider text-gray-500 dark:text-gray-400">${key} <span class="normal-case font-normal">(${value.length})</span></h4>`;
      if (value.length > 0 && typeof value[0] !== "object") {
        html += `<p class="text-sm text-gray-700 dark:text-gray-300">${value.map(formatValue).join(", ")}</p>`;
      } else {
        value.forEach((item, i) => {
          if (isObject(item)) {
            html += `<details class="mb-1 ml-2 border-l-2 border-gray-200 dark:border-gray-600 pl-3">`;
            html += `<summary class="cursor-pointer text-sm text-gray-700 dark:text-gray-300">[${i}]</summary>`;
            html += `<div class="mt-1">${renderScoresSection(item, depth + 1)}</div>`;
            html += `</details>`;
          } else {
            html += `<div class="text-sm text-gray-700 dark:text-gray-300">${formatValue(item)}</div>`;
          }
        });
      }
      html += `</div>`;
    }
    // Special: remedy download link
    else if (
      key === "apply_remedy" &&
      typeof value === "string" &&
      value.includes("/download-remedy/")
    ) {
      html += `<div class="flex justify-between items-center px-4 py-2.5 text-sm border-b border-gray-200 dark:border-gray-700">`;
      html += `<span class="font-medium text-gray-900 dark:text-white">Remedied Dataset</span>`;
      html += `<a href="${value}" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white rounded-lg bg-green-600 hover:bg-green-700 focus:ring-4 focus:ring-green-300 dark:bg-green-500 dark:hover:bg-green-600 transition-colors">`;
      html += `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>`;
      html += `Download CSV</a>`;
      html += `</div>`;
    }
    // Scalar → Flowbite list-group style row
    else {
      html += `<div class="flex justify-between items-center px-4 py-2.5 text-sm border-b border-gray-200 dark:border-gray-700 last:border-b-0">`;
      html += `<span class="font-medium text-gray-900 dark:text-white">${key}</span>`;
      html += `<span class="font-mono text-xs text-gray-500 dark:text-gray-400">${formatValue(value)}</span>`;
      html += `</div>`;
    }
  }

  return html;
}

// ==================== Globus Compute ====================

/** Switch between Upload and Globus tabs on the landing page. */
function switchUploadTab(tab) {
  const localPanel = document.getElementById("local-upload");
  const globusPanel = document.getElementById("globus-panel");
  const tabLocal = document.getElementById("tab-local");
  const tabGlobus = document.getElementById("tab-globus");

  if (!localPanel || !globusPanel) {
    console.error("switchUploadTab: missing elements", {
      localPanel: !!localPanel,
      globusPanel: !!globusPanel,
    });
    return;
  }

  const activeClass =
    "border-blue-600 text-blue-600 dark:text-blue-500 dark:border-blue-500";
  const inactiveClass =
    "border-transparent text-gray-500 hover:text-gray-600 hover:border-gray-300 dark:text-gray-400";

  if (tab === "globus") {
    localPanel.classList.add("hidden");
    globusPanel.classList.remove("hidden");
    tabLocal.className = `upload-tab flex-1 py-2.5 text-sm font-medium text-center border-b-2 ${inactiveClass}`;
    tabGlobus.className = `upload-tab flex-1 py-2.5 text-sm font-medium text-center border-b-2 ${activeClass}`;
  } else {
    localPanel.classList.remove("hidden");
    globusPanel.classList.add("hidden");
    tabLocal.className = `upload-tab flex-1 py-2.5 text-sm font-medium text-center border-b-2 ${activeClass}`;
    tabGlobus.className = `upload-tab flex-1 py-2.5 text-sm font-medium text-center border-b-2 ${inactiveClass}`;
  }
}

/** Fetch summary statistics via Globus Compute and render in data overview. */
function fetchGlobusSummary() {
  const endpointId = window.AIDRIN_GLOBUS_ENDPOINT;
  const filePath = window.AIDRIN_GLOBUS_FILE_PATH;
  const fileName = window.AIDRIN_GLOBUS_FILE_NAME;
  const fileType = window.AIDRIN_GLOBUS_FILE_TYPE;

  if (!endpointId || !filePath) return;

  _beginServerProcessing();

  fetch("/globus/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      endpoint_id: endpointId,
      file_path: filePath,
      file_name: fileName,
      file_type: fileType,
      metric_name: "summary_statistics",
      params: {},
    }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        const loading = document.getElementById("globus-summary-loading");
        if (loading)
          loading.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400">${data.error}</div>`;
        _endServerProcessing();
        return;
      }
      // Cached result — render immediately without polling
      if (data.status === "completed" && data.result) {
        renderGlobusSummary(data.result);
        _endServerProcessing();
        return;
      }
      if (data.task_id) {
        pollGlobusSummary(data.task_id);
      } else {
        _endServerProcessing();
      }
    })
    .catch((err) => {
      const loading = document.getElementById("globus-summary-loading");
      if (loading)
        loading.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400">Failed to connect: ${err.message}</div>`;
      _endServerProcessing();
    });
}

/** Render Globus summary data (used by both cached and polled paths). */
function renderGlobusSummary(data) {
  const loading = document.getElementById("globus-summary-loading");
  const content = document.getElementById("globus-summary-content");
  if (loading) loading.style.display = "none";

  if (data.error) {
    if (content)
      content.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400">${data.error}</div>`;
    _unlockGlobusSidebar();
    return;
  }

  if (content) {
    let html = `
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <div class="p-4 bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 rounded-lg text-center">
          <div class="text-3xl font-bold text-gray-900 dark:text-white">${(data.records_count || 0).toLocaleString()}</div>
          <div class="text-xs font-medium text-gray-500 dark:text-gray-400 mt-1 uppercase tracking-wide">Records</div>
        </div>
        <div class="p-4 bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 rounded-lg text-center">
          <div class="text-3xl font-bold text-gray-900 dark:text-white">${data.features_count || 0}</div>
          <div class="text-xs font-medium text-gray-500 dark:text-gray-400 mt-1 uppercase tracking-wide">Features</div>
        </div>
        <div class="p-4 bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 rounded-lg text-center">
          <div class="text-3xl font-bold text-gray-900 dark:text-white">${(data.numerical_features || []).length}</div>
          <div class="text-xs font-medium text-gray-500 dark:text-gray-400 mt-1 uppercase tracking-wide">Numerical</div>
        </div>
        <div class="p-4 bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 rounded-lg text-center">
          <div class="text-3xl font-bold text-gray-900 dark:text-white">${(data.categorical_features || []).length}</div>
          <div class="text-xs font-medium text-gray-500 dark:text-gray-400 mt-1 uppercase tracking-wide">Categorical</div>
        </div>
      </div>
    `;

    if (data.summary_statistics) {
      const features = Object.keys(data.summary_statistics);
      const allStats =
        features.length > 0
          ? Object.keys(data.summary_statistics[features[0]])
          : [];
      const preferredOrder = [
        "count",
        "min",
        "25th percentile",
        "50th percentile",
        "mean",
        "75th percentile",
        "max",
        "std",
      ];
      const statKeys = preferredOrder
        .filter((s) => allStats.includes(s))
        .concat(allStats.filter((s) => !preferredOrder.includes(s)));

      html += '<div class="relative overflow-x-auto rounded-lg shadow-sm">';
      html +=
        '<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">';
      html +=
        '<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400"><tr>';
      html += '<th scope="col" class="px-4 py-3">Feature</th>';
      statKeys.forEach((s) => {
        html += `<th scope="col" class="px-4 py-3 text-right">${s}</th>`;
      });
      html += "</tr></thead><tbody>";
      features.forEach((feat, i) => {
        const stripe =
          i % 2 === 0
            ? "bg-white dark:bg-gray-800"
            : "bg-gray-50 dark:bg-gray-700/50";
        html += `<tr class="${stripe} border-b dark:border-gray-700">`;
        html += `<td class="px-4 py-2 font-medium text-gray-900 dark:text-white whitespace-nowrap">${feat}</td>`;
        statKeys.forEach((s) => {
          html += `<td class="px-4 py-2 font-mono text-xs text-right">${data.summary_statistics[feat][s] ?? "—"}</td>`;
        });
        html += "</tr>";
      });
      html += "</tbody></table></div>";
    }

    content.innerHTML = html;
  }

  // Render histograms if available
  if (data.histograms && typeof renderWorkspaceHistograms === "function") {
    var wh = document.getElementById("workspace-histograms");
    if (wh) {
      wh.style.display = "block";
      renderWorkspaceHistograms(data.histograms);
    }
  }

  // Populate feature dropdowns for metric panels
  if (data.all_features && typeof populateWorkspaceDropdowns === "function") {
    populateWorkspaceDropdowns(data);
  }

  _unlockGlobusSidebar();
}

function _unlockGlobusSidebar() {
  var sidebarMetrics = document.getElementById("sidebar-metrics");
  if (sidebarMetrics)
    sidebarMetrics.classList.remove("opacity-50", "pointer-events-none");
  var loadingMsg = document.getElementById("sidebar-loading-msg");
  if (loadingMsg) loadingMsg.remove();
}

/** Poll for Globus summary statistics and render when complete. */
function pollGlobusSummary(taskId) {
  let attempts = 0;
  const maxAttempts = 120;

  const poll = () => {
    attempts++;
    fetch(`/globus/check-task/${taskId}`)
      .then((r) => r.json())
      .then((response) => {
        if (response.status === "completed" && response.result) {
          renderGlobusSummary(response.result);
          _endServerProcessing();
          // Cache the result so page reloads don't re-fetch
          fetch("/globus/cache-summary", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(response.result),
          }).catch(() => {}); // Best-effort cache
        } else if (response.status === "failed") {
          const loading = document.getElementById("globus-summary-loading");
          if (loading)
            loading.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400">${response.error || "Failed to load summary"}</div>`;
          _unlockGlobusSidebar();
          _endServerProcessing();
        } else if (attempts < maxAttempts) {
          setTimeout(poll, 2000);
        } else {
          _endServerProcessing();
        }
      })
      .catch((err) => {
        if (attempts < maxAttempts) setTimeout(poll, 3000);
        else _endServerProcessing();
      });
  };

  setTimeout(poll, 1000);
}

/** Disconnect from Globus — clear tokens. */
function disconnectGlobus() {
  fetch("/globus/disconnect", { method: "POST" })
    .then(() => window.location.reload())
    .catch((err) => console.error("Globus disconnect error:", err));
}

/** Load a remote dataset via Globus Compute. */
function loadGlobusDataset() {
  const endpointId = document
    .getElementById("globus-endpoint-id")
    ?.value?.trim();
  const filePath = document.getElementById("globus-file-path")?.value?.trim();
  const fileType = document.getElementById("globus-file-type")?.value;

  if (!endpointId || !filePath) {
    if (typeof showToast === "function")
      showToast("Please fill in endpoint UUID and file path", "error");
    return;
  }

  // Disable the form to prevent double-clicking
  const loadBtn = document.querySelector(
    '#globusForm button[onclick*="loadGlobusDataset"]',
  );
  const inputs = document.querySelectorAll(
    "#globusForm input, #globusForm select",
  );
  if (loadBtn) {
    loadBtn.disabled = true;
    loadBtn.classList.add("opacity-50", "cursor-not-allowed");
    loadBtn.textContent = "Connecting...";
  }
  inputs.forEach((el) => {
    el.disabled = true;
    el.classList.add("opacity-50");
  });

  const fileName = filePath.split("/").pop();

  if (typeof showToast === "function")
    showToast("Connecting to remote endpoint...", "info");

  fetch("/globus/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      endpoint_id: endpointId,
      file_path: filePath,
      file_name: fileName,
      file_type: fileType,
      metric_name: "completeness",
      params: {},
    }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        _reEnableGlobusForm();
        if (typeof showToast === "function") showToast(data.error, "error");
        return;
      }
      // Reload the page — session now has globus file info,
      // inspector will show sidebar + panels
      window.location.href = "/inspector";
    })
    .catch((err) => {
      _reEnableGlobusForm();
      if (typeof showToast === "function")
        showToast("Failed to connect: " + err.message, "error");
    });
}

function _reEnableGlobusForm() {
  const loadBtn = document.querySelector(
    '#globusForm button[onclick*="loadGlobusDataset"]',
  );
  const inputs = document.querySelectorAll(
    "#globusForm input, #globusForm select",
  );
  if (loadBtn) {
    loadBtn.disabled = false;
    loadBtn.classList.remove("opacity-50", "cursor-not-allowed");
    loadBtn.textContent = "Load Remote Dataset";
  }
  inputs.forEach((el) => {
    el.disabled = false;
    el.classList.remove("opacity-50");
  });
}

let _globusSubmitInProgress = false;
let _serverProcessingCount = 0;

/** True while summary load, metric POST, or async polling is in flight. */
window.isAidrinServerProcessing = function () {
  return _serverProcessingCount > 0;
};

function _beginServerProcessing() {
  _serverProcessingCount++;
  _syncProcessingUI();
}

function _endServerProcessing() {
  if (_serverProcessingCount > 0) _serverProcessingCount--;
  _syncProcessingUI();
}

/** Disable or enable all submit buttons in metric panels. */
function _setSubmitButtonsDisabled(disabled) {
  document
    .querySelectorAll('.metric-panel button[onclick*="workspaceSubmit"]')
    .forEach((btn) => {
      btn.disabled = disabled;
      if (disabled) {
        btn.classList.add("opacity-50", "cursor-not-allowed");
      } else {
        btn.classList.remove("opacity-50", "cursor-not-allowed");
      }
    });
}

/** Disable or enable Clear session buttons in the top bar and mobile file chip. */
function _setClearSessionButtonsDisabled(disabled) {
  document.querySelectorAll('button[onclick="clearFile()"]').forEach((btn) => {
    btn.disabled = disabled;
    if (disabled) {
      btn.classList.add(
        "opacity-50",
        "cursor-not-allowed",
        "pointer-events-none",
      );
      btn.setAttribute("aria-disabled", "true");
      btn.title = "Please wait — server is processing";
    } else {
      btn.classList.remove(
        "opacity-50",
        "cursor-not-allowed",
        "pointer-events-none",
      );
      btn.removeAttribute("aria-disabled");
      if (btn.getAttribute("aria-label") === "Clear uploaded file") {
        btn.title = "Clear file";
      } else if (btn.getAttribute("aria-label") === "New session") {
        btn.title = "Clear session and start over";
      } else {
        btn.removeAttribute("title");
      }
    }
  });
}

function _syncProcessingUI() {
  _setClearSessionButtonsDisabled(_serverProcessingCount > 0);
}

/** Called when a metric or Globus task finishes (success or failure). */
function _globusTaskDone() {
  _globusSubmitInProgress = false;
  _setSubmitButtonsDisabled(false);
  _endServerProcessing();
}

function _responseHasAsyncTasks(data) {
  return Object.values(data || {}).some(
    (v) => typeof v === "object" && v !== null && v.is_async && v.task_id,
  );
}

/** Submit a metric to run on a remote Globus Compute endpoint. */
function submitGlobusMetric(metricName, params, displayName) {
  if (_globusSubmitInProgress) {
    if (typeof showToast === "function")
      showToast(
        "A task is already running on the remote endpoint. Please wait.",
        "info",
      );
    return;
  }

  const endpointId = window.AIDRIN_GLOBUS_ENDPOINT || "";
  const filePath = window.AIDRIN_GLOBUS_FILE_PATH || "";
  const fileName = window.AIDRIN_GLOBUS_FILE_NAME || "";
  const fileType = window.AIDRIN_GLOBUS_FILE_TYPE || "";

  if (!endpointId || !filePath) {
    if (typeof showToast === "function")
      showToast("No remote file configured", "error");
    return;
  }

  // Block further submissions and disable submit / clear-session controls
  _globusSubmitInProgress = true;
  _beginServerProcessing();
  _setSubmitButtonsDisabled(true);

  // Show results section with spinner
  const resultsSection = document.getElementById("results-section");
  if (resultsSection) resultsSection.style.display = "block";

  fetch("/globus/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      endpoint_id: endpointId,
      file_path: filePath,
      file_name: fileName,
      file_type: fileType,
      metric_name: metricName,
      params: params || {},
    }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        _globusTaskDone();
        const m = document.getElementById("metrics");
        if (m)
          m.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">${data.error}</div>`;
        return;
      }
      if (data.task_id && data.is_async) {
        // Reuse existing async polling — but use Globus check endpoint
        pollAsyncMetric(
          data.task_id,
          displayName || metricName,
          null,
          "/globus/check-task/",
        );
      } else {
        _globusTaskDone();
      }
    })
    .catch((err) => {
      _globusTaskDone();
      if (typeof showToast === "function")
        showToast("Globus submit error: " + err.message, "error");
    });
}

// ==================== Layout Helpers ====================

/**
 * Sync the scores panel max-height to match the rendered plot image height.
 * Called via onload on result plot images.
 */
function syncScoresHeight(pairId) {
  const img = document.querySelector(`img[data-pair="${pairId}"]`);
  const scores = document.getElementById(`${pairId}-scores`);
  if (img && scores) {
    const imgHeight = img.offsetHeight;
    const minHeight = 400;
    scores.style.maxHeight = Math.max(imgHeight, minHeight) + "px";
  }
}

// ==================== Async Task Polling ====================

/**
 * Check if any metric results contain async tasks and start polling them.
 */
function handleAsyncResults(data) {
  for (const [type, results] of Object.entries(data)) {
    if (
      typeof results === "object" &&
      results !== null &&
      results.is_async &&
      results.task_id
    ) {
      // One token per task; released by pollAsyncMetric on every terminal path.
      _beginServerProcessing();
      pollAsyncMetric(results.task_id, type, results.cache_key);
    }
  }
}

/**
 * Poll an async metric task until complete, showing progress inline.
 */
function pollAsyncMetric(taskId, metricName, cacheKey, checkUrlBase) {
  checkUrlBase = checkUrlBase || "/check-and-update-task/";
  // Find or create a placeholder in the results area
  const resultsSection = document.getElementById("results-section");
  if (resultsSection) resultsSection.style.display = "block";

  const metricsDiv = document.getElementById("metrics");
  if (!metricsDiv) {
    _globusTaskDone();
    return;
  }

  // Human-readable metric names for the spinner card
  const metricDisplayNames = {
    data_quality: "Data Quality",
    completeness: "Completeness",
    outliers: "Outliers",
    duplicates: "Duplicity",
    correlations: "Correlation Analysis",
    feature_relevance: "Feature Relevance",
    representation_rate: "Representation Rate",
    statistical_rates: "Statistical Rates",
    class_distribution: "Class Imbalance",
    k_anonymity: "k-Anonymity",
    l_diversity: "l-Diversity",
    t_closeness: "t-Closeness",
    entropy_risk: "Entropy Risk",
    hipaa: "HIPAA Compliance",
    privacy_preservation: "Privacy Preservation",
    fairness: "Fairness",
    Completeness: "Completeness",
  };
  const displayName = metricDisplayNames[metricName] || metricName;

  // Create a placeholder card for this async metric
  const placeholderId = `async-${taskId}`;
  let existing = document.getElementById(placeholderId);
  if (!existing) {
    const card = document.createElement("div");
    card.id = placeholderId;
    card.className =
      "p-5 mb-4 bg-white border border-gray-200 rounded-lg shadow-sm dark:bg-gray-800 dark:border-gray-700";
    card.innerHTML = `
      <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">${displayName}</h3>
      <div class="flex items-center gap-3">
        <svg class="w-5 h-5 text-gray-300 animate-spin dark:text-gray-600 fill-blue-600" viewBox="0 0 100 101"><path d="M100 50.59c0 27.61-22.39 50-50 50S0 78.2 0 50.59 22.39.59 50 .59s50 22.39 50 50zm-90.92 0c0 22.6 18.32 40.92 40.92 40.92s40.92-18.32 40.92-40.92S72.6 9.67 50 9.67 9.08 28 9.08 50.59z" fill="currentColor"/><path d="M93.97 39.04c2.43-.64 3.93-3.13 3.04-5.5A50 50 0 0048.44.58c-2.5.23-4.21 2.53-3.73 5l.02.1a3.89 3.89 0 004.57 3.13A41.1 41.1 0 0188.18 37.2a3.88 3.88 0 005.79 1.84z" fill="currentFill"/></svg>
        <div>
          <p class="text-sm text-gray-700 dark:text-gray-300">${checkUrlBase.includes("globus") ? "Running on Globus Compute Endpoint..." : "Processing..."}</p>
          <div class="w-48 bg-gray-200 rounded-full h-1.5 dark:bg-gray-700 mt-1">
            <div id="${placeholderId}-bar" class="bg-blue-600 h-1.5 rounded-full transition-all" style="width: 0%"></div>
          </div>
        </div>
      </div>
    `;
    metricsDiv.appendChild(card);
  }

  // Start polling
  let attempts = 0;
  const maxAttempts = 150; // 5 minutes at 2s intervals

  const poll = () => {
    attempts++;
    const checkUrl = checkUrlBase.includes("globus")
      ? `${checkUrlBase}${taskId}`
      : `${checkUrlBase}${taskId}/${encodeURIComponent(metricName)}`;
    fetch(checkUrl)
      .then((r) => r.json())
      .then((response) => {
        const card = document.getElementById(placeholderId);
        if (!card) {
          _globusTaskDone();
          return;
        }

        if (response.status === "completed") {
          // Update stored result for download
          if (lastMetricResult) {
            lastMetricResult[metricName] = response.result;
          }

          // Check if result is a multi-metric bundle (e.g., data_quality returns
          // {Completeness: {...}, Outliers: {...}, Duplicity: {...}})
          // vs a single metric result (has Description/Visualization at top level)
          const result = response.result;
          const isBundle =
            typeof result === "object" &&
            result !== null &&
            !result.Description &&
            !result.Error &&
            Object.values(result).some(
              (v) =>
                typeof v === "object" &&
                v !== null &&
                (v.Description || v.Error),
            );

          const tempDiv = document.createElement("div");
          if (isBundle) {
            // Render each sub-metric as its own card (matches local renderWorkspaceResults)
            let html = "";
            for (const [subType, subResult] of Object.entries(result)) {
              if (typeof subResult === "object" && subResult !== null) {
                html += buildResultCard(subType, subResult);
              }
            }
            tempDiv.innerHTML = html;
          } else {
            tempDiv.innerHTML = buildResultCard(metricName, result);
          }

          // Replace placeholder with all rendered cards
          const fragment = document.createDocumentFragment();
          while (tempDiv.firstChild) fragment.appendChild(tempDiv.firstChild);
          card.replaceWith(fragment);
          _globusTaskDone();
        } else if (response.status === "failed") {
          _globusTaskDone();
          card.innerHTML = `
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">${metricName}</h3>
            <div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">
              ${response.error || "Task failed"}
            </div>`;
        } else if (response.status === "processing") {
          // Update progress bar
          const progress = response.progress || {};
          const pct =
            progress.total > 0
              ? Math.round((progress.current / progress.total) * 100)
              : 0;
          const bar = document.getElementById(`${placeholderId}-bar`);
          if (bar) bar.style.width = `${pct}%`;

          const statusText = card.querySelector("p");
          if (statusText)
            statusText.textContent = progress.status || "Processing...";

          if (attempts < maxAttempts) {
            setTimeout(poll, 2000);
          } else {
            _globusTaskDone();
          }
        } else {
          // Unknown/terminal status — release the token so Clear session can't
          // stay disabled forever.
          _globusTaskDone();
        }
      })
      .catch((err) => {
        console.error("Polling error:", err);
        if (attempts < maxAttempts) {
          setTimeout(poll, 3000);
        } else {
          _globusTaskDone();
        }
      });
  };

  setTimeout(poll, 1000); // First poll after 1s
}

/**
 * Build a single result card HTML string for a completed metric.
 * Reuses the same rendering logic as renderWorkspaceResults but for one entry.
 */
function buildResultCard(type, results) {
  if (typeof results !== "object" || results === null) return "";

  const description = results.Description || "";
  const error = results.Error || "";
  const interpretation = results["Graph interpretation"];
  const visualizations = [];
  const scores = {};

  for (const [key, value] of Object.entries(results)) {
    if (
      key === "Description" ||
      key === "Error" ||
      key === "Graph interpretation"
    )
      continue;
    if (
      key.toLowerCase().includes("visualization") &&
      typeof value === "string" &&
      value.length > 100
    ) {
      visualizations.push({
        key,
        src: value.startsWith("data:")
          ? value
          : `data:image/png;base64,${value}`,
      });
    } else {
      scores[key] = value;
    }
  }

  let html = `<div class="p-5 mb-4 bg-white border border-gray-200 rounded-lg shadow-sm dark:bg-gray-800 dark:border-gray-700">`;
  html += `<h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">${type}</h3>`;

  if (error) {
    html += `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">${error}</div>`;
  } else {
    if (description) {
      html += `<p class="text-sm text-gray-600 dark:text-gray-400 mb-4 leading-relaxed">${description}</p>`;
    }

    const hasViz = visualizations.length > 0;
    const hasScores = Object.keys(scores).length > 0;

    const asyncPairId =
      "result-pair-" + Math.random().toString(36).substr(2, 6);
    if (hasViz || hasScores) {
      html += `<div class="grid gap-4" style="grid-template-columns: ${hasViz && hasScores ? "1fr 1fr" : "1fr"};">`;
      if (hasViz) {
        html += `<div class="flex flex-col items-center gap-4">`;
        for (const viz of visualizations) {
          const isHeatmap = /correlation|heatmap/i.test(viz.key);
          const imgStyle = isHeatmap
            ? ' style="max-width:500px; max-height:500px; object-fit:contain;"'
            : "";
          html += `<img src="${viz.src}" alt="${viz.key}" class="rounded-lg ${isHeatmap ? "" : "w-full"}"${imgStyle} data-pair="${asyncPairId}" onload="syncScoresHeight('${asyncPairId}')" />`;
        }
        html += `</div>`;
      }
      if (hasScores) {
        html += `<div id="${asyncPairId}-scores" class="overflow-auto" style="min-height: 400px; max-height: 500px;">${renderScoresSection(scores)}</div>`;
      }
      html += `</div>`;
    }

    if (
      interpretation &&
      typeof interpretation === "string" &&
      !interpretation.includes("No visualization available")
    ) {
      html += `<div class="flex items-start gap-2.5 p-4 mt-4 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50">
        <svg class="w-5 h-5 shrink-0 mt-0.5 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z"/></svg>
        <div>
          <div class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">Interpretation</div>
          <p class="text-gray-700 dark:text-gray-300 leading-relaxed">${interpretation}</p>
        </div>
      </div>`;
    }

    // AI Explanation placeholder (filled async if LLM is configured)
    if (window.AIDRIN_LLM_ENABLED && (hasViz || hasScores)) {
      const llmId = "llm-async-" + Math.random().toString(36).substr(2, 6);
      html += `<div id="${llmId}" class="mt-3"></div>`;
      setTimeout(() => {
        requestLLMExplanation(llmId, type, description, visualizations, scores);
      }, 100);
    }
  }

  html += `</div>`;
  return html;
}

// ==================== Toast Notifications ====================

/**
 * Show a Flowbite-style toast notification that auto-dismisses.
 * @param {string} message - The message to display
 * @param {string} type - 'success', 'error', or 'info'
 * @param {number} duration - Auto-dismiss in ms (default 4000)
 */
function showToast(message, type, duration) {
  type = type || "info";
  duration = duration || 4000;

  const colors = {
    success: {
      bg: "bg-green-100 dark:bg-green-800",
      text: "text-green-500 dark:text-green-200",
      icon: '<path d="M10 .5a9.5 9.5 0 1 0 9.5 9.5A9.51 9.51 0 0 0 10 .5Zm3.707 8.207-4 4a1 1 0 0 1-1.414 0l-2-2a1 1 0 0 1 1.414-1.414L9 10.586l3.293-3.293a1 1 0 0 1 1.414 1.414Z"/>',
    },
    error: {
      bg: "bg-red-100 dark:bg-red-800",
      text: "text-red-500 dark:text-red-200",
      icon: '<path d="M10 .5a9.5 9.5 0 1 0 9.5 9.5A9.51 9.51 0 0 0 10 .5Zm3.707 8.207-4 4a1 1 0 0 1-1.414 0l-2-2a1 1 0 0 1 1.414-1.414L9 10.586l3.293-3.293a1 1 0 0 1 1.414 1.414Z"/>',
    },
    info: {
      bg: "bg-blue-100 dark:bg-blue-800",
      text: "text-blue-500 dark:text-blue-200",
      icon: '<path d="M10 .5a9.5 9.5 0 1 0 9.5 9.5A9.51 9.51 0 0 0 10 .5ZM9.5 4a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3ZM12 15H8a1 1 0 0 1 0-2h1v-3H8a1 1 0 0 1 0-2h2a1 1 0 0 1 1 1v4h1a1 1 0 0 1 0 2Z"/>',
    },
  };
  const c = colors[type] || colors.info;

  const toast = document.createElement("div");
  toast.className = `fixed top-4 right-4 z-[9999] flex items-center w-full max-w-xs p-4 text-gray-500 bg-white rounded-lg shadow-lg dark:text-gray-400 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 transition-all`;
  toast.style.opacity = "0";
  toast.style.transform = "translateY(-8px)";
  toast.innerHTML = `
    <div class="inline-flex items-center justify-center shrink-0 w-8 h-8 ${c.text} ${c.bg} rounded-lg">
      <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">${c.icon}</svg>
    </div>
    <div class="ml-3 text-sm font-normal">${message}</div>
    <button type="button" class="ml-auto -mx-1.5 -my-1.5 bg-white text-gray-400 hover:text-gray-900 rounded-lg focus:ring-2 focus:ring-gray-300 p-1.5 hover:bg-gray-100 inline-flex items-center justify-center h-8 w-8 dark:text-gray-500 dark:hover:text-white dark:bg-gray-800 dark:hover:bg-gray-700" onclick="this.parentElement.remove()">
      <svg class="w-3 h-3" fill="none" viewBox="0 0 14 14"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/></svg>
    </button>
  `;

  document.body.appendChild(toast);

  // Animate in
  requestAnimationFrame(() => {
    toast.style.transition = "opacity 0.3s, transform 0.3s";
    toast.style.opacity = "1";
    toast.style.transform = "translateY(0)";
  });

  // Auto-dismiss
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(-8px)";
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ==================== JSON Download ====================

/** Override main.js downloadJSON to use inspector's stored result. */
function downloadJSON() {
  if (!lastMetricResult) return;
  // Strip base64 visualization blobs to keep download small
  const clean = {};
  for (const [k, v] of Object.entries(lastMetricResult)) {
    if (typeof v === "object" && v !== null) {
      const inner = {};
      for (const [ik, iv] of Object.entries(v)) {
        if (
          typeof iv === "string" &&
          iv.length > 1000 &&
          ik.toLowerCase().includes("visualization")
        )
          continue;
        inner[ik] = iv;
      }
      clean[k] = inner;
    } else {
      clean[k] = v;
    }
  }
  const blob = new Blob([JSON.stringify(clean, null, 2)], {
    type: "application/json",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "result.json";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}

// ==================== Checkbox Helpers ====================

/** Toggle all checkboxes in a container on or off. */
function toggleAllCheckboxes(btn, containerId, checked) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
    if (!cb.disabled) cb.checked = checked;
  });
  updateCheckboxCount(containerId);
}

/** Update the "N selected / M features" counter. */
function updateCheckboxCount(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const all = el.querySelectorAll('input[type="checkbox"]');
  const checked = el.querySelectorAll('input[type="checkbox"]:checked');
  const counter = document.getElementById(containerId + "-count");
  if (counter) {
    if (checked.length === 0) {
      counter.textContent = `${all.length} features`;
    } else {
      counter.textContent = `${checked.length} / ${all.length} selected`;
    }
  }
}

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
function isFlatDict(obj) {
  return Object.values(obj).every((v) => typeof v !== "object" || v === null);
}
function formatValue(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number")
    return Number.isInteger(v) ? v.toString() : v.toFixed(4);
  return String(v);
}
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ==================== FAIR Assessment ====================

function submitFairAssessment() {
  const form = document.getElementById("form-fair-assessment");
  if (!form) return;

  const formData = new FormData(form);
  const resultContainer = document.getElementById("fair-result-container");
  if (resultContainer)
    resultContainer.innerHTML = '<p class="text-center">Processing...</p>';

  // Return the promise so withSubmitGuard re-enables the button when it settles.
  return fetch("/fair-assessment", { method: "POST", body: formData })
    .then((response) => response.json())
    .then((data) => {
      if (!resultContainer) return;

      // Check for error response
      if (data.error) {
        resultContainer.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">${data.error}</div>`;
        return;
      }

      let html = "";

      // Compliance summary bar — extract from FAIR Compliance Checks
      const checks = data["FAIR Compliance Checks"] || {};
      const totalCheck = checks["Total Checks"] || "";
      const totalMatch = totalCheck.match(/(\d+)\/(\d+)/);
      const totalPassed = totalMatch ? parseInt(totalMatch[1]) : 0;
      const totalExpected = totalMatch ? parseInt(totalMatch[2]) : 1;
      const totalPct = Math.round((totalPassed / totalExpected) * 100);

      html += `<div class="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-sm p-5 mb-4">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-base font-semibold text-gray-900 dark:text-white">FAIR Compliance</h3>
          <span class="text-sm font-medium text-gray-500 dark:text-gray-400">${totalPassed}/${totalExpected} checks passed</span>
        </div>
        <div class="w-full bg-gray-200 rounded-full h-2.5 dark:bg-gray-700 mb-4">
          <div class="bg-blue-600 h-2.5 rounded-full" style="width: ${totalPct}%"></div>
        </div>
        <div class="grid grid-cols-4 gap-3">`;

      // Per-principle mini bars
      const fairKeys = ["Findable", "Accessible", "Interoperable", "Reusable"];
      fairKeys.forEach((k) => {
        const checkStr = checks[`${k} Checks`] || "0/0";
        const m = checkStr.match(/(\d+)\/(\d+)/);
        const passed = m ? parseInt(m[1]) : 0;
        const total = m ? parseInt(m[2]) : 1;
        const pct = Math.round((passed / total) * 100);
        html += `<div class="text-center">
          <div class="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">${k}</div>
          <div class="text-lg font-bold text-gray-900 dark:text-white">${passed}/${total}</div>
          <div class="w-full bg-gray-200 rounded-full h-1.5 dark:bg-gray-700 mt-1">
            <div class="bg-blue-600 h-1.5 rounded-full" style="width: ${pct}%"></div>
          </div>
        </div>`;
      });
      html += "</div></div>";

      // FAIR principle details as collapsible accordions
      html += '<div class="space-y-2 mb-4">';
      fairKeys.forEach((k) => {
        let val = "—";
        let checkStr = checks[`${k} Checks`] || "";
        if (data[k] !== undefined && typeof data[k] === "object") {
          val = renderFairValue(data[k]);
        } else if (data[k] !== undefined) {
          val = `<div class="py-2 text-sm text-gray-700 dark:text-gray-300">${data[k]}</div>`;
        }
        html += `<details class="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
          <summary class="cursor-pointer flex items-center justify-between px-4 py-3 text-sm font-medium text-gray-900 dark:text-white bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors">
            <span>${k}</span>
            <span class="text-xs text-gray-400 dark:text-gray-500">${checkStr}</span>
          </summary>
          <div class="px-4 py-3 border-t border-gray-200 dark:border-gray-700">${val}</div>
        </details>`;
      });
      html += "</div>";

      // Other data (FAIR Compliance Checks, Other, Original Metadata)
      const extraKeys = Object.keys(data).filter(
        (k) => !fairKeys.includes(k) && k !== "Pie chart",
      );
      if (extraKeys.length > 0) {
        html +=
          '<div class="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-sm p-4">';
        html +=
          '<h3 class="text-base font-semibold text-gray-900 dark:text-white mb-3">Detailed Results</h3>';
        extraKeys.forEach((k) => {
          const val = data[k];
          if (typeof val === "object" && val !== null) {
            html += `<details class="mb-2 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
              <summary class="cursor-pointer flex items-center justify-between px-4 py-2.5 text-sm font-medium text-gray-900 dark:text-white bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors">
                ${k}
                <svg class="w-3 h-3 shrink-0 ml-2" viewBox="0 0 10 6"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M1 1l4 4 4-4"/></svg>
              </summary>
              <div class="p-4 border-t border-gray-200 dark:border-gray-700">
                <pre class="text-xs text-gray-600 dark:text-gray-400 overflow-auto" style="max-height: 300px; white-space: pre-wrap; word-break: break-word;">${escapeHtml(JSON.stringify(val, null, 2))}</pre>
              </div>
            </details>`;
          } else {
            html += `<div class="flex justify-between items-center px-4 py-2.5 text-sm border-b border-gray-200 dark:border-gray-700">
              <span class="font-medium text-gray-900 dark:text-white">${k}</span>
              <span class="text-gray-500 dark:text-gray-400">${val ?? "—"}</span>
            </div>`;
          }
        });
        html += "</div>";
      }

      resultContainer.innerHTML = html;
    })
    .catch((error) => {
      console.error("Error:", error);
      if (resultContainer)
        resultContainer.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">Error: ${error.message}</div>`;
    });
}

/** Render a FAIR value object as readable HTML with pass/fail badges */
function renderFairValue(obj) {
  if (typeof obj !== "object" || obj === null) return String(obj ?? "—");
  let html = "";
  for (const [k, v] of Object.entries(obj)) {
    if (typeof v === "object" && v !== null) {
      html += `<div class="mt-1.5"><span class="text-xs font-medium text-gray-700 dark:text-gray-300">${k}</span>${renderFairValue(v)}</div>`;
    } else {
      const strVal = String(v);
      const isFail =
        strVal.includes("CHECK FAILED") ||
        v === false ||
        v === "Fail" ||
        v === "No";
      let badge = "";
      if (isFail) {
        badge =
          '<span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">&#10007; Missing</span>';
      } else {
        // Truncate long values
        const display =
          strVal.length > 60 ? strVal.substring(0, 57) + "..." : strVal;
        badge = `<span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" title="${escapeHtml(strVal)}">&#10003; Found</span>`;
      }
      html += `<div class="flex items-center justify-between py-1.5 text-xs border-b border-gray-100 dark:border-gray-700 last:border-b-0">
        <span class="text-gray-600 dark:text-gray-400 mr-2">${k}</span>${badge}</div>`;
    }
  }
  return html;
}

// ==================== Custom Metrics ====================

function initCodeMirror() {
  const textarea = document.getElementById("metricCodeEditor");
  if (!textarea || codeMirrorEditor) return;

  codeMirrorEditor = CodeMirror.fromTextArea(textarea, {
    mode: "python",
    lineNumbers: true,
    theme: "eclipse",
    indentUnit: 4,
    tabSize: 4,
    lineWrapping: true,
    matchBrackets: true,
  });

  codeMirrorEditor.refresh();

  // Load existing code
  fetch("/load-custom-metric")
    .then((r) => r.text())
    .then((code) => codeMirrorEditor.setValue(code))
    .catch((err) => console.error("Error loading custom metric:", err));
}

function saveCustomMetricFile() {
  if (!codeMirrorEditor) return;
  const code = codeMirrorEditor.getValue();
  const applyRemedy = document.getElementById("apply_remedy")?.checked
    ? "yes"
    : "no";

  const formData = new FormData();
  formData.append("metric_code", code);
  formData.append("apply_remedy", applyRemedy);

  fetch("/save-custom-metric-text", { method: "POST", body: formData })
    .then((r) => r.json())
    .then((data) => {
      if (data.message) {
        // Enable submit button after successful save
        const submitBtn = document.getElementById("custom-metrics-submit");
        if (submitBtn) {
          submitBtn.disabled = false;
        }
      }
      showToast(data.message || data.error, data.error ? "error" : "success");
    })
    .catch((err) => showToast("Error saving file: " + err, "error"));
}

function submitCustomMetric() {
  if (!codeMirrorEditor) return;

  const resultsSection = document.getElementById("results-section");
  if (resultsSection) resultsSection.style.display = "block";
  const metricsDiv = document.getElementById("metrics");
  if (metricsDiv) {
    metricsDiv.innerHTML = `
      <div class="text-center py-8">
        <div role="status" class="inline-block">
          <svg class="w-8 h-8 text-gray-200 animate-spin dark:text-gray-600 fill-blue-600" viewBox="0 0 100 101"><path d="M100 50.59c0 27.61-22.39 50-50 50S0 78.2 0 50.59 22.39.59 50 .59s50 22.39 50 50zm-90.92 0c0 22.6 18.32 40.92 40.92 40.92s40.92-18.32 40.92-40.92S72.6 9.67 50 9.67 9.08 28 9.08 50.59z" fill="currentColor"/><path d="M93.97 39.04c2.43-.64 3.93-3.13 3.04-5.5A50 50 0 0048.44.58c-2.5.23-4.21 2.53-3.73 5l.02.1a3.89 3.89 0 004.57 3.13A41.1 41.1 0 0188.18 37.2a3.88 3.88 0 005.79 1.84z" fill="currentFill"/></svg>
        </div>
        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">Processing custom metric...</p>
      </div>`;
  }

  const formData = new FormData();
  formData.append("metric_code", codeMirrorEditor.getValue());
  formData.append(
    "apply_remedy",
    document.getElementById("apply_remedy")?.checked ? "yes" : "no",
  );

  // Return the promise so withSubmitGuard re-enables the button when it settles.
  return fetch("/custom-metrics?return_type=json", {
    method: "POST",
    body: formData,
  })
    .then((response) => {
      if (response.ok) return response.json();
      throw new Error(`Server error (${response.status})`);
    })
    .then((data) => {
      lastMetricResult = data;
      renderWorkspaceResults(data);
    })
    .catch((error) => {
      console.error("Error:", error);
      if (metricsDiv)
        metricsDiv.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">${error.message}</div>`;
    });
}

// ==================== Histograms ====================

/**
 * Render histogram images in the data overview panel.
 * @param {Object} histograms - Dict of {column_theme: base64_img} from /summary-statistics
 */
function renderWorkspaceHistograms(histograms) {
  const container = document.getElementById("workspace-histograms");
  if (!container) return;

  // Always use the light variant — CSS filter handles dark mode
  const columns = {};
  for (const [key, base64] of Object.entries(histograms)) {
    if (key.endsWith("_light")) {
      const colName = key.slice(0, -"_light".length);
      columns[colName] = base64;
    }
  }

  if (Object.keys(columns).length === 0) {
    container.innerHTML = "";
    return;
  }

  let html =
    '<h3 class="text-sm font-semibold text-gray-900 dark:text-white mb-3 uppercase tracking-wide">Feature Distributions</h3>';
  html += '<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">';

  for (const [colName, base64] of Object.entries(columns)) {
    html += `
      <div class="bg-white dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 rounded-lg overflow-hidden">
        <img src="data:image/png;base64,${base64}" alt="Distribution of ${colName}" class="w-full" />
        <div class="px-3 py-2 text-xs text-center font-medium text-gray-600 dark:text-gray-400 border-t border-gray-200 dark:border-gray-600">${colName}</div>
      </div>
    `;
  }

  html += "</div>";
  container.innerHTML = html;
}

// ==================== Workspace Init ====================

/**
 * Initialize the workspace after file upload.
 * Fetches summary statistics and populates feature dropdowns.
 */
function initWorkspace() {
  // Restore panel from URL hash, or default to data-overview
  const hash = location.hash.replace("#", "");
  const initialPanel =
    hash && document.getElementById("panel-" + hash) ? hash : "data-overview";
  showPanel(initialPanel, false); // false = don't push to history on init
  // Replace current history entry so back button works from the first panel
  history.replaceState({ panel: initialPanel }, "", "#" + initialPanel);

  // Fetch summary statistics and feature list (disable clear session while loading)
  let initPending = 2;
  const initTaskDone = () => {
    if (--initPending === 0) _endServerProcessing();
  };
  _beginServerProcessing();

  fetch("/summary-statistics")
    .then((r) => r.json())
    .then((data) => {
      const container = document.getElementById("workspace-summary");
      if (!container) return;

      if (data.success) {
        let html = `
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
            <div class="p-4 bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 rounded-lg text-center">
              <div class="text-3xl font-bold text-gray-900 dark:text-white">${data.records_count.toLocaleString()}</div>
              <div class="text-xs font-medium text-gray-500 dark:text-gray-400 mt-1 uppercase tracking-wide">Records</div>
            </div>
            <div class="p-4 bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 rounded-lg text-center">
              <div class="text-3xl font-bold text-gray-900 dark:text-white">${data.features_count}</div>
              <div class="text-xs font-medium text-gray-500 dark:text-gray-400 mt-1 uppercase tracking-wide">Features</div>
            </div>
            <div class="p-4 bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 rounded-lg text-center">
              <div class="text-3xl font-bold text-gray-900 dark:text-white">${data.numerical_features?.length || 0}</div>
              <div class="text-xs font-medium text-gray-500 dark:text-gray-400 mt-1 uppercase tracking-wide">Numerical</div>
            </div>
            <div class="p-4 bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-600 rounded-lg text-center">
              <div class="text-3xl font-bold text-gray-900 dark:text-white">${data.categorical_features?.length || 0}</div>
              <div class="text-xs font-medium text-gray-500 dark:text-gray-400 mt-1 uppercase tracking-wide">Categorical</div>
            </div>
          </div>
        `;

        // Summary statistics table — pivoted: rows = features, columns = stats
        if (data.summary_statistics) {
          const features = Object.keys(data.summary_statistics);
          const allStats =
            features.length > 0
              ? Object.keys(data.summary_statistics[features[0]])
              : [];
          // Preferred order
          const preferredOrder = [
            "count",
            "min",
            "25th percentile",
            "50th percentile",
            "mean",
            "75th percentile",
            "max",
            "std",
          ];
          const statKeys = preferredOrder
            .filter((s) => allStats.includes(s))
            .concat(allStats.filter((s) => !preferredOrder.includes(s)));

          html += '<div class="relative overflow-x-auto rounded-lg shadow-sm">';
          html +=
            '<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">';
          html +=
            '<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400"><tr>';
          html += '<th scope="col" class="px-4 py-3">Feature</th>';
          statKeys.forEach((s) => {
            html += `<th scope="col" class="px-4 py-3 text-right">${s}</th>`;
          });
          html += "</tr></thead><tbody>";

          features.forEach((feat, i) => {
            const stripe =
              i % 2 === 0
                ? "bg-white dark:bg-gray-800"
                : "bg-gray-50 dark:bg-gray-700/50";
            html += `<tr class="${stripe} border-b dark:border-gray-700">`;
            html += `<td class="px-4 py-2 font-medium text-gray-900 dark:text-white whitespace-nowrap">${feat}</td>`;
            statKeys.forEach((s) => {
              html += `<td class="px-4 py-2 font-mono text-xs text-right">${data.summary_statistics[feat][s] ?? "—"}</td>`;
            });
            html += "</tr>";
          });

          html += "</tbody></table></div>";
        }

        container.innerHTML = html;

        // Render histograms in the data overview panel
        if (data.histograms) {
          renderWorkspaceHistograms(data.histograms);
        }
      } else {
        container.innerHTML = `
          <div class="flex items-start gap-2 p-3 text-sm rounded-lg bg-amber-50 text-amber-800 dark:bg-amber-900/20 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
            <svg class="w-4 h-4 mt-0.5 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"/></svg>
            <span>${data.message}</span>
          </div>`;
      }
    })
    .catch((err) => {
      const container = document.getElementById("workspace-summary");
      if (container)
        container.innerHTML = `<p class="text-sm" style="color: red;">Error loading summary: ${err.message}</p>`;
    })
    .finally(initTaskDone);

  // Populate feature dropdowns via /feature-set (same as metric.js does)
  fetch("/feature-set", { method: "POST" })
    .then((r) => r.json())
    .then((data) => {
      if (data.success && typeof populateWorkspaceDropdowns === "function") {
        populateWorkspaceDropdowns(data);
      }
    })
    .catch((err) => console.error("Error fetching features:", err))
    .finally(initTaskDone);

  // Feature relevance: disable target feature in checkbox lists
  const targetDropdown = document.getElementById(
    "all-features-dropdown-feature-relevance",
  );
  if (targetDropdown) {
    targetDropdown.addEventListener("change", function () {
      const target = this.value;
      // In both cat and num checkbox containers, disable the checkbox matching the target
      ["catFeaturesCheckbox1", "numFeaturesCheckbox1"].forEach(
        (containerId) => {
          const container = document.getElementById(containerId);
          if (!container) return;
          container.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
            if (cb.value === target) {
              cb.checked = false;
              cb.disabled = true;
              cb.closest("label").style.opacity = "0.4";
            } else {
              cb.disabled = false;
              cb.closest("label").style.opacity = "1";
            }
          });
        },
      );
    });
  }

  // Handle FAIR assessment file input UI
  const fairFile = document.getElementById("fair-file");
  const fairLabel = document.getElementById("fairFileLabel");
  const fairIcon = document.getElementById("fairUploadIcon");
  if (fairFile && fairLabel) {
    fairFile.addEventListener("change", () => {
      if (fairFile.files.length) {
        fairLabel.textContent = fairFile.files[0].name;
        if (fairIcon) {
          fairIcon.innerHTML =
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>';
          fairIcon.classList.remove("text-gray-400");
          fairIcon.classList.add("text-green-500");
        }
      } else {
        fairLabel.textContent = "JSON metadata file";
        if (fairIcon) {
          fairIcon.innerHTML =
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>';
          fairIcon.classList.remove("text-green-500");
          fairIcon.classList.add("text-gray-400");
        }
      }
    });
  }
}

/**
 * Populate all feature dropdowns and checkbox containers in the workspace.
 * Called after /feature-set returns data.
 */
function populateWorkspaceDropdowns(data) {
  const allFeatures = data.all_features || [];
  const catFeatures = data.categorical_features || [];
  const numFeatures = data.numerical_features || [];
  const classImbalanceFeatures = data.class_imbalance_features || [];

  // Helper: populate a <select> dropdown
  function fillDropdown(id, features) {
    const el = document.getElementById(id);
    if (!el) return;
    // Keep the first disabled option
    while (el.options.length > 1) el.remove(1);
    features.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f;
      opt.textContent = f;
      el.appendChild(opt);
    });
  }

  /**
   * Populate a checkbox container with a compact chip/pill layout.
   * Includes a select-all toggle. Scrollable when many features.
   */
  function fillCheckboxContainer(id, features, nameAttr) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = "";

    if (features.length === 0) {
      el.innerHTML =
        '<p class="text-xs text-gray-400 dark:text-gray-500 py-2">No features available</p>';
      return;
    }

    // Wrapper with max-height scroll
    const wrapper = document.createElement("div");
    wrapper.className =
      "border border-gray-200 dark:border-gray-700 rounded-lg p-2 overflow-y-auto overflow-x-hidden";
    wrapper.style.maxHeight = "300px";

    // Select all / none controls
    const controls = document.createElement("div");
    controls.className =
      "flex items-center gap-3 mb-2 pb-2 border-b border-gray-200 dark:border-gray-700";
    controls.innerHTML = `
      <button type="button" class="text-xs text-blue-600 dark:text-blue-400 hover:underline cursor-pointer" onclick="toggleAllCheckboxes(this, '${id}', true)">Select all</button>
      <button type="button" class="text-xs text-gray-500 dark:text-gray-400 hover:underline cursor-pointer" onclick="toggleAllCheckboxes(this, '${id}', false)">Clear</button>
      <span class="text-xs text-gray-400 dark:text-gray-500 ml-auto" id="${id}-count">${features.length} features</span>
    `;
    wrapper.appendChild(controls);

    // Chip grid
    const grid = document.createElement("div");
    grid.className = "flex flex-wrap gap-1.5";

    features.forEach((f) => {
      const label = document.createElement("label");
      label.className =
        "inline-block px-3 py-1.5 rounded-md text-sm cursor-pointer transition-colors border border-gray-200 dark:border-gray-600 hover:border-blue-400 dark:hover:border-blue-500 has-[:checked]:bg-blue-50 has-[:checked]:border-blue-500 has-[:checked]:text-blue-700 dark:has-[:checked]:bg-blue-900/30 dark:has-[:checked]:border-blue-400 dark:has-[:checked]:text-blue-300";
      label.style.cssText =
        "max-width: 200px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;";
      label.title = f;

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.name = nameAttr;
      cb.value = f;
      cb.style.cssText =
        "width: 14px; height: 14px; min-width: 14px; vertical-align: middle; margin-right: 6px;";
      cb.className =
        "shrink-0 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500 dark:focus:ring-blue-600 dark:bg-gray-700 dark:border-gray-600";
      cb.addEventListener("change", () => updateCheckboxCount(id));

      label.appendChild(cb);
      label.appendChild(document.createTextNode(f));
      grid.appendChild(label);
    });

    wrapper.appendChild(grid);
    el.appendChild(wrapper);
  }

  // Fairness dropdowns
  fillDropdown("allFeaturesDropdownRepRate", allFeatures);
  fillDropdown("allFeaturesDropdownStatRate1", allFeatures);
  fillDropdown("allFeaturesDropdownStatRate2", allFeatures);
  fillDropdown("allFeaturesDropdownCondDemoDis1", allFeatures);
  fillDropdown("allFeaturesDropdownCondDemoDis2", allFeatures);

  // Feature Relevance
  fillDropdown("all-features-dropdown-feature-relevance", allFeatures);
  fillCheckboxContainer(
    "catFeaturesCheckbox1",
    catFeatures,
    "categorical features for feature relevancy",
  );
  fillCheckboxContainer(
    "numFeaturesCheckbox1",
    numFeatures,
    "numerical features for feature relevancy",
  );

  // Correlation Analysis (separate containers — unique IDs to avoid conflicts)
  fillCheckboxContainer(
    "corrCatFeaturesCheckbox",
    catFeatures,
    "categorical features for correlation analysis",
  );
  fillCheckboxContainer(
    "corrNumFeaturesCheckbox",
    numFeatures,
    "numerical features for correlation analysis",
  );

  // Privacy dropdowns
  fillDropdown("allFeaturesDropdownMMS", allFeatures);
  fillDropdown("allFeaturesDropdownMMM", allFeatures);
  fillDropdown("lDiversitySensitiveDropdown", allFeatures);
  fillDropdown("tClosenessSensitiveDropdown", allFeatures);
  fillCheckboxContainer(
    "numFeaturesCheckbox2",
    numFeatures,
    "numerical features to add noise",
  );
  fillCheckboxContainer(
    "catFeaturesCheckbox2",
    catFeatures,
    "quasi identifiers to measure single attribute risk score",
  );
  fillCheckboxContainer(
    "catFeaturesCheckbox3",
    catFeatures,
    "quasi identifiers to measure multiple attribute risk score",
  );
  fillCheckboxContainer(
    "entropyRiskQIsCheckbox",
    allFeatures,
    "quasi identifiers for entropy risk",
  );
  fillCheckboxContainer(
    "kAnonymityQIsCheckbox",
    allFeatures,
    "quasi identifiers for k-anonymity",
  );
  fillCheckboxContainer(
    "lDiversityQIsCheckbox",
    allFeatures,
    "quasi identifiers for l-diversity",
  );
  fillCheckboxContainer(
    "tClosenessQIsCheckbox",
    allFeatures,
    "quasi identifiers for t-closeness",
  );

  // Class Imbalance
  fillDropdown("all-features-dropdown-class-imbalance", classImbalanceFeatures);

  // HIPAA
  fillCheckboxContainer(
    "hipaa-identifiers-checkbox",
    allFeatures,
    "HIPAA identifiers for HIPAA compliance",
  );

  // Distance metrics for class imbalance — render as chips + sync to hidden select
  const distChips = document.getElementById("class-imbalance-distance-chips");
  const distSelect = document.getElementById(
    "class-imbalance-distance-dropdown",
  );
  if (distChips && distChips.children.length === 0) {
    const distances = [
      { value: "EU", label: "Euclidean Distance", short: "EU" },
      { value: "CH", label: "Chi-Squared Distance", short: "CH" },
      { value: "KL", label: "KL Divergence", short: "KL" },
      { value: "HE", label: "Hellinger Distance", short: "HE" },
      { value: "TV", label: "Total Variation", short: "TV" },
      { value: "CS", label: "Cosine Similarity", short: "CS" },
    ];

    // Also populate hidden select for form submission
    if (distSelect) {
      distances.forEach((d) => {
        const opt = document.createElement("option");
        opt.value = d.value;
        opt.textContent = d.label;
        distSelect.appendChild(opt);
      });
    }

    distances.forEach((d) => {
      const label = document.createElement("label");
      label.className =
        "inline-flex items-center px-3 py-1.5 rounded-md text-sm cursor-pointer transition-colors border border-gray-200 dark:border-gray-600 hover:border-blue-400 dark:hover:border-blue-500 has-[:checked]:bg-blue-50 has-[:checked]:border-blue-500 has-[:checked]:text-blue-700 dark:has-[:checked]:bg-blue-900/30 dark:has-[:checked]:border-blue-400 dark:has-[:checked]:text-blue-300";

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = d.value;
      cb.className =
        "w-3.5 h-3.5 shrink-0 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500 dark:focus:ring-blue-600 dark:bg-gray-700 dark:border-gray-600";
      cb.style.marginRight = "8px";
      // Sync checkbox to hidden select
      cb.addEventListener("change", () => {
        if (distSelect) {
          Array.from(distSelect.options).forEach((opt) => {
            opt.selected =
              distChips.querySelector(`input[value="${opt.value}"]`)?.checked ||
              false;
          });
        }
      });

      const text = document.createElement("span");
      text.className =
        "select-none text-gray-700 dark:text-gray-300 whitespace-nowrap";
      text.textContent = `${d.short} — ${d.label}`;

      label.appendChild(cb);
      label.appendChild(text);
      distChips.appendChild(label);
    });
  }
}

// ==================== LLM Explanation ====================

/**
 * Request an AI explanation for a metric result from the configured LLM.
 * Inserts a spinner, then replaces it with the explanation callout.
 */
/**
 * Render an LLM explanation callout into a container element.
 */
function _renderLLMCallout(container, explanation, model) {
  const modelTag = model
    ? `<span class="ml-2 font-normal normal-case tracking-normal text-purple-400 dark:text-purple-500">(${model})</span>`
    : "";
  container.innerHTML = `
    <div class="flex items-start gap-2.5 p-4 text-sm rounded-lg border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-900/20">
      <svg class="w-5 h-5 shrink-0 mt-0.5 text-purple-400 dark:text-purple-500" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z"/></svg>
      <div>
        <div class="text-xs font-semibold uppercase tracking-wide text-purple-500 dark:text-purple-400 mb-1">AI Explanation${modelTag}</div>
        <p class="text-gray-700 dark:text-gray-300 leading-relaxed">${explanation}</p>
      </div>
    </div>`;
}

function requestLLMExplanation(
  containerId,
  metricName,
  description,
  visualizations,
  scores,
) {
  const container = document.getElementById(containerId);
  if (!container) return;

  // Show loading spinner
  container.innerHTML = `
    <div class="flex items-center gap-2 p-3 mt-2 text-sm text-purple-600 dark:text-purple-400">
      <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      Generating AI explanation...
    </div>`;

  // Get the first visualization base64 (strip data: prefix for the API)
  let vizBase64 = "";
  if (visualizations && visualizations.length > 0) {
    const src = visualizations[0].src || "";
    vizBase64 = src.startsWith("data:") ? src.split(",")[1] || "" : src;
  }

  // Build scores summary — strip large values (like base64 blobs)
  let scoresData = null;
  if (scores && Object.keys(scores).length > 0) {
    scoresData = {};
    for (const [k, v] of Object.entries(scores)) {
      if (typeof v === "string" && v.length > 500) continue;
      scoresData[k] = v;
    }
  }

  fetch("/llm/explain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      metric_name: metricName,
      description: description,
      visualization: vizBase64,
      scores: scoresData,
    }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.explanation) {
        _renderLLMCallout(container, data.explanation, data.model);

        // Cache the explanation server-side for restore on panel revisit
        const cacheMetric = _panelCacheMap[activePanel];
        if (cacheMetric) {
          fetch("/llm/cache-explanation", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              metric_name: cacheMetric,
              result_type: metricName,
              explanation: data.explanation,
              model: data.model || "",
            }),
          }).catch(() => {});
        }
      } else {
        const errMsg = data.error || "No explanation returned";
        container.innerHTML = `
          <div class="flex items-center gap-2 p-3 text-sm text-yellow-700 dark:text-yellow-400 rounded-lg bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800">
            <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"/></svg>
            AI explanation unavailable: ${errMsg}
          </div>`;
        debugLog("LLM explanation unavailable:", errMsg);
      }
    })
    .catch((err) => {
      container.innerHTML = `
        <div class="flex items-center gap-2 p-3 text-sm text-yellow-700 dark:text-yellow-400 rounded-lg bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800">
          <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"/></svg>
          AI explanation error: ${err.message || err}
        </div>`;
      debugLog("LLM explanation error:", err);
    });
}

// ==================== LLM Settings ====================

function openLLMSettings() {
  const modal = document.getElementById("llm-settings-modal");
  if (modal) modal.classList.remove("hidden");
}

function closeLLMSettings() {
  const modal = document.getElementById("llm-settings-modal");
  if (modal) modal.classList.add("hidden");
}

function _getLLMFormValues() {
  const apiBase = document.getElementById("llm-api-base").value.trim();
  const apiKey = document.getElementById("llm-api-key").value.trim();
  const model = document.getElementById("llm-model").value.trim();
  const temp = parseFloat(document.getElementById("llm-temperature").value);
  return {
    api_base: apiBase || "https://api.openai.com/v1",
    api_key: apiKey,
    model: model || "gpt-4o-mini",
    temperature: isNaN(temp) ? 0.5 : temp,
  };
}

function testLLMConnection() {
  const statusEl = document.getElementById("llm-settings-status");
  const testBtn = document.getElementById("llm-test-btn");
  const saveBtn = document.getElementById("llm-save-btn");
  const config = _getLLMFormValues();

  if (
    !config.api_key ||
    config.api_key === "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"
  ) {
    if (statusEl) {
      statusEl.className = "mt-3 text-sm text-red-600 dark:text-red-400";
      statusEl.textContent = "Please enter your API key.";
      statusEl.classList.remove("hidden");
    }
    return;
  }

  // Disable buttons during test
  if (testBtn) {
    testBtn.disabled = true;
    testBtn.textContent = "Testing...";
  }
  if (saveBtn) saveBtn.disabled = true;

  fetch("/llm/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  })
    .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
    .then(({ ok, data }) => {
      if (testBtn) {
        testBtn.disabled = false;
        testBtn.textContent = "Test";
      }
      if (ok && data.success) {
        if (saveBtn) saveBtn.disabled = false;
        if (statusEl) {
          statusEl.className =
            "mt-3 text-sm text-green-600 dark:text-green-400";
          statusEl.textContent = "Connection successful. You can now save.";
          statusEl.classList.remove("hidden");
        }
      } else {
        if (saveBtn) saveBtn.disabled = true;
        if (statusEl) {
          statusEl.className = "mt-3 text-sm text-red-600 dark:text-red-400";
          statusEl.textContent =
            "Test failed: " + (data.error || "Unknown error");
          statusEl.classList.remove("hidden");
        }
      }
    })
    .catch((err) => {
      if (testBtn) {
        testBtn.disabled = false;
        testBtn.textContent = "Test";
      }
      if (saveBtn) saveBtn.disabled = true;
      if (statusEl) {
        statusEl.className = "mt-3 text-sm text-red-600 dark:text-red-400";
        statusEl.textContent = "Connection error: " + err.message;
        statusEl.classList.remove("hidden");
      }
    });
}

function saveLLMSettings() {
  const statusEl = document.getElementById("llm-settings-status");
  const config = _getLLMFormValues();

  fetch("/llm/configure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        window.AIDRIN_LLM_ENABLED = true;
        if (statusEl) {
          statusEl.className =
            "mt-3 text-sm text-green-600 dark:text-green-400";
          statusEl.textContent =
            "Settings saved. AI explanations are now enabled.";
          statusEl.classList.remove("hidden");
        }
        setTimeout(() => closeLLMSettings(), 1500);
      } else {
        if (statusEl) {
          statusEl.className = "mt-3 text-sm text-red-600 dark:text-red-400";
          statusEl.textContent = data.error || "Failed to save settings.";
          statusEl.classList.remove("hidden");
        }
      }
    })
    .catch((err) => {
      if (statusEl) {
        statusEl.className = "mt-3 text-sm text-red-600 dark:text-red-400";
        statusEl.textContent = "Connection error: " + err.message;
        statusEl.classList.remove("hidden");
      }
    });
}

function disconnectLLM() {
  fetch("/llm/disconnect", { method: "POST" }).then(() => {
    window.AIDRIN_LLM_ENABLED = false;
    closeLLMSettings();
    showToast("LLM disconnected", "info");
  });
}
