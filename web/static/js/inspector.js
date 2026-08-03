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
let customOutlierTargets = [];
let fileReferenceTargets = [];
let customOutlierRuleCounter = 0;

function isFileReferenceTarget(target) {
  const dtype = String(target?.dtype || "").toLowerCase();
  if (target?.target_type === "hdf5_dataset") {
    return (
      dtype.includes("string") ||
      dtype.includes("object") ||
      dtype.includes("bytes") ||
      /(^|[|<>])[su]\d*/i.test(dtype)
    );
  }
  return ["object", "string", "str", "category", "bytes"].some((name) =>
    dtype.includes(name),
  );
}

function targetPickerElements(picker) {
  return {
    button: picker?.querySelector("[data-target-picker-button]"),
    summary: picker?.querySelector("[data-target-picker-summary]"),
    menu: picker?.querySelector("[data-target-picker-menu]"),
    search: picker?.querySelector("[data-target-picker-search]"),
    options: picker?.querySelector("[data-target-picker-options]"),
    empty: picker?.querySelector("[data-target-picker-empty]"),
  };
}

function selectedTargetPickerInputs(picker) {
  return Array.from(
    picker?.querySelectorAll("[data-target-picker-option-input]:checked") || [],
  );
}

function updateTargetPickerSummary(picker) {
  const { summary } = targetPickerElements(picker);
  if (!summary) return;
  const selected = selectedTargetPickerInputs(picker);
  const placeholder = picker.dataset.placeholder || "Select a target...";
  if (selected.length === 0) summary.textContent = placeholder;
  else if (picker.dataset.multiple === "true") {
    summary.textContent = `${selected.length} target${selected.length === 1 ? "" : "s"} selected`;
  } else summary.textContent = selected[0].dataset.displayLabel;
}

function setTargetPickerOpen(picker, open) {
  const { button, menu, search } = targetPickerElements(picker);
  if (!button || !menu) return;
  const shouldOpen = Boolean(open) && !button.disabled;
  menu.classList.toggle("hidden", !shouldOpen);
  button.setAttribute("aria-expanded", String(shouldOpen));
  if (shouldOpen) search?.focus();
}

function setTargetPickerEnabled(picker, enabled) {
  const { button, search } = targetPickerElements(picker);
  if (button) button.disabled = !enabled;
  if (search) search.disabled = !enabled;
  picker
    ?.querySelectorAll("[data-target-picker-option-input]")
    .forEach((input) => (input.disabled = !enabled));
  if (!enabled) setTargetPickerOpen(picker, false);
}

function filterTargetPicker(picker, query) {
  const normalized = String(query || "")
    .trim()
    .toLowerCase();
  let visible = 0;
  picker?.querySelectorAll("[data-target-picker-option]").forEach((option) => {
    const matches = !normalized || option.dataset.search.includes(normalized);
    option.classList.toggle("hidden", !matches);
    if (matches) visible += 1;
  });
  targetPickerElements(picker).empty?.classList.toggle("hidden", visible !== 0);
}

function initTargetPicker(picker) {
  const { button, search } = targetPickerElements(picker);
  if (!picker || !button || picker.dataset.initialized === "true") return;
  picker.dataset.initialized = "true";
  button.addEventListener("click", () => {
    setTargetPickerOpen(
      picker,
      button.getAttribute("aria-expanded") !== "true",
    );
  });
  search?.addEventListener("input", () =>
    filterTargetPicker(picker, search.value),
  );
  document.addEventListener("click", (event) => {
    if (!picker.contains(event.target)) setTargetPickerOpen(picker, false);
  });
  picker.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setTargetPickerOpen(picker, false);
      button.focus();
    }
  });
}

function setTargetPickerOptionSelected(option, selected) {
  option.setAttribute("aria-selected", String(selected));
  option.classList.toggle("bg-blue-50", selected);
  option.classList.toggle("dark:bg-blue-900/30", selected);
  option.classList.toggle("bg-gray-50", !selected);
  option.classList.toggle("dark:bg-gray-800", !selected);
}

function renderTargetPicker(picker, targets, options = {}) {
  if (!picker) return;
  initTargetPicker(picker);
  const elements = targetPickerElements(picker);
  const selected = new Set(
    selectedTargetPickerInputs(picker).map((input) => input.value),
  );
  elements.options?.replaceChildren();
  targets.forEach((target) => {
    const label = document.createElement("label");
    label.dataset.targetPickerOption = "true";
    label.dataset.search =
      `${target.name} ${target.display_label || ""}`.toLowerCase();
    label.setAttribute("role", "option");
    label.className =
      "flex cursor-pointer items-center gap-2 rounded-md bg-gray-50 px-2 py-2 text-sm text-gray-700 hover:bg-gray-100 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-600";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.targetPickerOptionInput = "true";
    input.name = options.inputName || "";
    input.value = target.name;
    input.dataset.targetType = target.target_type;
    input.dataset.displayLabel = target.display_label || target.name;
    input.checked = selected.has(target.name);
    setTargetPickerOptionSelected(label, input.checked);
    input.className =
      "checkbox individual rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-500 dark:bg-gray-800";
    input.addEventListener("change", () => {
      if (picker.dataset.multiple !== "true" && input.checked) {
        picker
          .querySelectorAll("[data-target-picker-option-input]")
          .forEach((other) => {
            if (other !== input) other.checked = false;
          });
        setTargetPickerOpen(picker, false);
      }
      picker
        .querySelectorAll("[data-target-picker-option]")
        .forEach((option) => {
          const optionInput = option.querySelector(
            "[data-target-picker-option-input]",
          );
          setTargetPickerOptionSelected(option, Boolean(optionInput?.checked));
        });
      updateTargetPickerSummary(picker);
      picker.dispatchEvent(
        new CustomEvent("target-picker-change", { bubbles: true }),
      );
    });

    const name = document.createElement("span");
    name.className = "min-w-0 flex-1 truncate";
    name.textContent = target.display_label || target.name;
    name.title = target.display_label || target.name;
    label.append(input, name);
    if (options.suggested?.test(target.name)) {
      const badge = document.createElement("span");
      badge.className =
        "shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-300";
      badge.textContent = "Suggested";
      label.appendChild(badge);
    }
    elements.options?.appendChild(label);
  });
  if (elements.search) elements.search.value = "";
  updateTargetPickerSummary(picker);
  filterTargetPicker(picker, "");
}

function fullMatchTargetNames(patternText, targets, targetType) {
  if (!patternText) return { matches: [] };
  try {
    const pattern = new RegExp(`^(?:${patternText})$`);
    return {
      matches: targets.filter(
        (target) =>
          (!targetType || target.target_type === targetType) &&
          pattern.test(target.name),
      ),
    };
  } catch (error) {
    return { matches: [], error: error.message };
  }
}

function updateRegexTargetPreview(element, patternText, targets, targetType) {
  if (!element) return;
  const result = fullMatchTargetNames(patternText, targets, targetType);
  if (!patternText)
    element.textContent = "Enter a pattern to preview matching targets.";
  else if (result.error)
    element.textContent =
      "Preview unavailable in this browser. The AIDRIN server will validate this pattern.";
  else if (!result.matches.length)
    element.textContent = "No targets match this pattern.";
  else {
    const names = result.matches
      .slice(0, 3)
      .map((target) => target.display_label || target.name);
    const remainder = result.matches.length - names.length;
    element.textContent = `${result.matches.length} matching target${result.matches.length === 1 ? "" : "s"}: ${names.join(", ")}${remainder ? `, and ${remainder} more` : ""}`;
  }
}

function initFileReferenceTargetPicker() {
  initTargetPicker(document.getElementById("file-reference-target-picker"));
  const mode = document.getElementById("file-reference-target-match");
  const pattern = document.getElementById("file-reference-target-pattern");
  mode?.addEventListener("change", updateFileReferenceTargetMode);
  pattern?.addEventListener("input", updateFileReferenceTargetMode);
}

function updateFileReferenceTargetMode() {
  const enabled = Boolean(
    document.getElementById("toggleButton_file_reference_validation")?.checked,
  );
  const regex =
    document.getElementById("file-reference-target-match")?.value === "regex";
  const picker = document.getElementById("file-reference-target-picker");
  const pattern = document.getElementById("file-reference-target-pattern");
  document
    .getElementById("file-reference-target-exact")
    ?.classList.toggle("hidden", regex);
  document
    .getElementById("file-reference-target-regex")
    ?.classList.toggle("hidden", !regex);
  setTargetPickerEnabled(picker, enabled && !regex);
  if (pattern) pattern.disabled = !enabled || !regex;
  updateRegexTargetPreview(
    document.getElementById("file-reference-target-preview"),
    pattern?.value.trim(),
    fileReferenceTargets,
  );
}

function toggleFileReferenceTargetControl(enabled) {
  updateFileReferenceTargetMode();
  if (!enabled)
    setTargetPickerOpen(
      document.getElementById("file-reference-target-picker"),
      false,
    );
}

function loadFileReferenceOptions() {
  const checkbox = document.getElementById(
    "toggleButton_file_reference_validation",
  );
  const message = document.getElementById("file-reference-message");
  if (!checkbox || window.AIDRIN_GLOBUS_MODE) return Promise.resolve();

  return fetch("/custom-outlier-targets", { method: "POST" })
    .then((response) => response.json())
    .then((data) => {
      const config = data.file_reference || {};
      if (!data.success || !config.enabled) {
        if (message) {
          message.textContent =
            config.message ||
            data.message ||
            "File-reference validation is unavailable.";
        }
        return;
      }

      const targets = (data.targets || []).filter(isFileReferenceTarget);
      const suggestedName = /(path|file|filename|filepath|location)/i;
      targets.sort((left, right) => {
        const leftSuggested = suggestedName.test(left.name) ? 0 : 1;
        const rightSuggested = suggestedName.test(right.name) ? 0 : 1;
        return leftSuggested - rightSuggested;
      });

      fileReferenceTargets = targets;
      renderTargetPicker(
        document.getElementById("file-reference-target-picker"),
        targets,
        { inputName: "file_reference_targets", suggested: suggestedName },
      );
      updateFileReferenceTargetMode();

      const rootSelect = document.getElementById("file-reference-root");
      if (rootSelect) {
        rootSelect.replaceChildren();
        if ((config.roots || []).length !== 1) {
          const placeholder = document.createElement("option");
          placeholder.value = "";
          placeholder.textContent = "Select a configured root";
          placeholder.disabled = true;
          placeholder.selected = true;
          rootSelect.appendChild(placeholder);
        }
        (config.roots || []).forEach((root) => {
          const option = document.createElement("option");
          option.value = root.id;
          option.textContent = root.label;
          rootSelect.appendChild(option);
        });
      }

      if (!targets.length) {
        if (message)
          message.textContent =
            "No string-valued targets are available in this dataset.";
        return;
      }
      checkbox.disabled = false;
      toggleFileReferenceTargetControl(checkbox.checked);
      if (message) {
        message.textContent = `Paths are checked on this AIDRIN server. Web scans are capped at ${Number(config.scan_limit).toLocaleString()} values; use CLI or MCP for larger complete scans.`;
      }
    })
    .catch((error) => {
      if (message)
        message.textContent =
          "Unable to load file-reference options: " + error.message;
    });
}

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
  "data-structure": "data_structure",
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
  initCustomOutlierEditor();
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
async function workspaceSubmit(targetUrl) {
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
      "/data-structure": [
        "constant_feature_count",
        "max_pairwise_correlation",
        "skewness",
        "kurtosis",
      ],
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
      completeness: "Column-Level Completeness",
      outliers: "Outliers",
      duplicates: "Duplicity",
      row_level_completeness: "Row-Level Completeness",
      duplicity_by_features: "Duplicates by Selected Features",
      feature_coverage_ratio: "Feature Coverage Ratio",
      temporal_completeness: "Temporal Completeness",
      null_count_trend: "Null Count Trend",
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
      constant_feature_count: "Constant Feature Count",
    };

    if (targetUrl === "/data-quality") {
      remoteName = "data_quality";
      const selected = [];
      const selectedNames = [];
      if (gFormData.get("completeness") === "yes") {
        selected.push("completeness");
        selectedNames.push("Column-Level Completeness");
      }
      if (gFormData.get("outliers") === "yes") {
        selected.push("outliers");
        selectedNames.push("Outliers");
      }
      if (gFormData.get("duplicity") === "yes") {
        selected.push("duplicates");
        selectedNames.push("Duplicity");
      }
      if (gFormData.get("duplicate detection by features") === "yes") {
        selected.push("duplicity_by_features");
        selectedNames.push("Duplicates by Selected Features");
        remoteParams.duplicate_features = Array.from(
          gFormData.getAll("features for duplicate detection"),
        );
      }
      if (gFormData.get("row level completeness") === "yes") {
        selected.push("row_level_completeness");
        selectedNames.push("Row-Level Completeness");
        remoteParams.required_columns = Array.from(
          gFormData.getAll("required columns for row level completeness"),
        );
      }
      if (gFormData.get("feature coverage ratio") === "yes") {
        selected.push("feature_coverage_ratio");
        selectedNames.push("Feature Coverage Ratio");
        const thr = parseFloat(
          gFormData.get("threshold for feature coverage ratio"),
        );
        remoteParams.threshold = isNaN(thr) ? 0.9 : thr;
      }
      if (gFormData.get("temporal completeness") === "yes") {
        selected.push("temporal_completeness");
        selectedNames.push("Temporal Completeness");
        remoteParams.timestamp_column = gFormData.get(
          "timestamp column for temporal completeness",
        );
        remoteParams.frequency =
          gFormData.get("frequency for temporal completeness") || "D";
      }
      if (gFormData.get("null count trend") === "yes") {
        selected.push("null_count_trend");
        selectedNames.push("Null Count Trend");
        remoteParams.batch_column = gFormData.get(
          "batch column for null count trend",
        );
        remoteParams.target_columns = Array.from(
          gFormData.getAll("target columns for null count trend"),
        );
      }
      if (gFormData.get("custom_outliers") === "yes") {
        const customOutlierRules = await resolveCustomOutlierRules();
        if (!customOutlierRules) return;
        selected.push("custom_outliers");
        selectedNames.push("Custom Criteria Outliers");
        remoteParams.custom_outlier_rules = customOutlierRules;
        remoteParams.max_outliers = customOutlierLimitValue(
          gFormData.get("max_outliers"),
          100,
        );
        remoteParams.max_export_rows = customOutlierLimitValue(
          gFormData.get("max_export_rows"),
          10000,
        );
        const scanLimit = gFormData.get("scan_limit");
        if (scanLimit !== null && scanLimit !== "") {
          remoteParams.scan_limit = Number(scanLimit);
        }
        remoteParams.stop_after_outliers =
          gFormData.get("stop_after_outliers") === "yes";
      }
      if (selected.length === 0) {
        if (typeof showToast === "function")
          showToast("Please select at least one metric", "error");
        return;
      }
      remoteParams.selected = selected;
      remoteDisplayName = selectedNames.join(", ");
    } else if (targetUrl === "/data-structure") {
      remoteName = "data_structure";
      const selected = [];
      const selectedNames = [];
      if (gFormData.get("constant feature count") === "yes") {
        selected.push("constant_feature_count");
        selectedNames.push("Constant Feature Count");
      }
      if (gFormData.get("max pairwise correlation") === "yes") {
        selected.push("max_pairwise_correlation");
        selectedNames.push("Max Pairwise Correlation");
      }
      if (gFormData.get("skewness") === "yes") {
        selected.push("skewness");
        selectedNames.push("Skewness");
      }
      if (gFormData.get("kurtosis") === "yes") {
        selected.push("kurtosis");
        selectedNames.push("Kurtosis");
      }
      if (selected.length === 0) {
        if (typeof showToast === "function")
          showToast("Please select at least one metric", "error");
        return;
      }
      remoteParams.selected = selected;
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
  if (targetUrl === "/data-quality") {
    const customOutliersSelected = formData.get("custom_outliers") === "yes";
    const customOutlierRules = customOutliersSelected
      ? await resolveCustomOutlierRules()
      : [];
    if (customOutliersSelected && !customOutlierRules) {
      return;
    }
    processedFormData.set(
      "custom_outlier_rules",
      JSON.stringify(customOutlierRules),
    );
    processedFormData.set(
      "max_outliers",
      String(customOutlierLimitValue(formData.get("max_outliers"), 100)),
    );
    processedFormData.set(
      "max_export_rows",
      String(customOutlierLimitValue(formData.get("max_export_rows"), 10000)),
    );
  }
  if (
    targetUrl === "/data-structure" &&
    formData.get("file_reference_validation") === "yes"
  ) {
    const targetMatch = formData.get("file_reference_target_match") || "exact";
    const selectedTargets = formData
      .getAll("file_reference_targets")
      .map((value) => String(value).trim())
      .filter(Boolean);
    let message = "";
    if (!selectedTargets.length) {
      message =
        targetMatch === "regex"
          ? "Enter a target pattern."
          : "Select at least one path-bearing target.";
    }
    if (message) {
      if (typeof showToast === "function") showToast(message, "error");
      return;
    }
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
          m.innerHTML = `<div class="p-4 text-sm text-yellow-800 rounded-lg bg-yellow-50 dark:bg-yellow-900/20 dark:text-yellow-300" role="alert">${escapeHtml(data.message)}</div>`;
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
// Display-only title overrides for result cards. The underlying result key
// (e.g. "Completeness") stays stable for Globus/LLM-explain plumbing.
const RESULT_TITLE_OVERRIDES = { Completeness: "Column-Level Completeness" };
function prettyResultTitle(key) {
  return RESULT_TITLE_OVERRIDES[key] || key;
}

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
    html += `<h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">${escapeHtml(prettyResultTitle(type))}</h3>`;

    if (error) {
      html += `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">${escapeHtml(error)}</div>`;
    } else {
      if (description) {
        html += `<p class="text-sm text-gray-600 dark:text-gray-400 mb-4 leading-relaxed">${escapeHtml(description)}</p>`;
      }
      if (
        type === "File Reference Validation" &&
        results.Summary &&
        !results.Summary.scan_complete
      ) {
        html += `<div class="p-4 mb-4 text-sm text-amber-800 rounded-lg bg-amber-50 dark:bg-amber-900/20 dark:text-amber-300" role="alert"><strong>Partial scan:</strong> ${escapeHtml(formatValue(results.Summary.unscanned_values))} reference values were not checked because the server scan cap was reached. Use CLI or MCP for a complete larger scan.</div>`;
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
            <p class="text-gray-700 dark:text-gray-300 leading-relaxed">${escapeHtml(interpretation)}</p>
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

function renderFileReferenceInvalidTable(rows) {
  let html = `<div class="mb-4">`;
  html += `<h4 class="text-xs font-semibold mb-2 uppercase tracking-wider text-gray-500 dark:text-gray-400">Invalid references (${rows.length})</h4>`;
  if (!rows.length) {
    return (
      html +
      `<p class="text-sm text-gray-600 dark:text-gray-300">None in the returned details.</p></div>`
    );
  }
  html += `<div class="relative overflow-x-auto rounded-lg shadow-sm"><table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">`;
  html += `<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400"><tr>`;
  ["Target", "Location", "Value", "Reason", "Resolved path"].forEach(
    (heading) => {
      html += `<th scope="col" class="px-3 py-2.5">${escapeHtml(heading)}</th>`;
    },
  );
  html += `</tr></thead><tbody>`;
  rows.forEach((row, index) => {
    const stripe =
      index % 2
        ? "bg-gray-50 dark:bg-gray-700/50"
        : "bg-white dark:bg-gray-800";
    const values = [
      row.target,
      row.location?.display,
      row.value,
      row.reason,
      row.resolved_path,
    ];
    html += `<tr class="${stripe} border-b dark:border-gray-700">`;
    values.forEach((value) => {
      html += `<td class="px-3 py-2 align-top break-all">${escapeHtml(formatValue(value))}</td>`;
    });
    html += `</tr>`;
  });
  return html + `</tbody></table></div></div>`;
}

function renderFileReferenceMetadataTable(rows) {
  let html = `<div class="mb-4">`;
  html += `<h4 class="text-xs font-semibold mb-2 uppercase tracking-wider text-gray-500 dark:text-gray-400">File metadata (${rows.length})</h4>`;
  if (!rows.length) {
    return (
      html +
      `<p class="text-sm text-gray-600 dark:text-gray-300">No valid files in the returned details.</p></div>`
    );
  }
  html += `<div class="relative overflow-x-auto rounded-lg shadow-sm"><table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">`;
  html += `<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400"><tr>`;
  [
    "Resolved path",
    "Size (bytes)",
    "Owner",
    "Created",
    "Modified",
    "Occurrences",
  ].forEach((heading) => {
    html += `<th scope="col" class="px-3 py-2.5">${escapeHtml(heading)}</th>`;
  });
  html += `</tr></thead><tbody>`;
  rows.forEach((row, index) => {
    const stripe =
      index % 2
        ? "bg-gray-50 dark:bg-gray-700/50"
        : "bg-white dark:bg-gray-800";
    const values = [
      row.resolved_path,
      row.size_bytes,
      row.owner_name,
      row.created_at || "Unavailable",
      row.modified_at,
      row.occurrences,
    ];
    html += `<tr class="${stripe} border-b dark:border-gray-700">`;
    values.forEach((value) => {
      html += `<td class="px-3 py-2 align-top break-all">${escapeHtml(formatValue(value))}</td>`;
    });
    html += `</tr>`;
  });
  return html + `</tbody></table></div></div>`;
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
        html += `<h4 class="text-xs font-semibold mb-2 uppercase tracking-wider text-gray-500 dark:text-gray-400">${escapeHtml(key)} <span class="normal-case font-normal">(${count})</span></h4>`;
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
        html += `<td class="px-4 py-2 font-medium text-gray-900 dark:text-white whitespace-nowrap">${escapeHtml(k)}</td>`;
        html += `<td class="px-4 py-2 text-right font-mono text-xs">${escapeHtml(formatValue(v))}</td>`;
        html += `</tr>`;
        rowIdx++;
      }
      html += `</tbody></table></div></div>`;
    }
    // Custom outlier preview gets a compact scan-first table with per-row details.
    else if (key === "Outlier preview" && isObject(value)) {
      html += renderCustomOutlierPreviewTable(value);
    }
    // Custom outlier export rows are downloaded instead of rendered inline.
    else if (key === "Outlier export" && isObject(value)) {
      const rows = flattenOutlierExportRows(value);
      html += `<div class="mb-4 rounded-lg border border-gray-200 dark:border-gray-700 p-4">`;
      html += `<div class="flex flex-wrap items-center justify-between gap-3">`;
      html += `<div>`;
      html += `<h4 class="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">${escapeHtml(key)}</h4>`;
      html += `<p class="mt-1 text-sm text-gray-600 dark:text-gray-300">${rows.length} downloadable row${rows.length === 1 ? "" : "s"}</p>`;
      html += `</div>`;
      html += `<button type="button" onclick="downloadCustomOutlierExportCsv()" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white rounded-lg bg-blue-600 hover:bg-blue-700 focus:ring-4 focus:ring-blue-300 dark:bg-blue-500 dark:hover:bg-blue-600 transition-colors">Download CSV</button>`;
      html += `</div></div>`;
    }
    // Nested dict → collapsible Flowbite accordion-style section
    else if (isObject(value) && Object.keys(value).length > 0) {
      const isDeep = Object.values(value).some((v) => isObject(v));
      if (isDeep || Object.keys(value).length > 5) {
        html += `<details class="mb-3 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden" ${depth === 0 ? "open" : ""}>`;
        html += `<summary class="cursor-pointer flex items-center justify-between px-4 py-2.5 text-sm font-medium text-gray-900 dark:text-white bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors">`;
        html += `${escapeHtml(key)}<svg class="w-3 h-3 shrink-0 ml-2" viewBox="0 0 10 6"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M1 1l4 4 4-4"/></svg>`;
        html += `</summary>`;
        html += `<div class="p-4 border-t border-gray-200 dark:border-gray-700">`;
        html += renderScoresSection(value, depth + 1);
        html += `</div></details>`;
      } else {
        html += `<div class="mb-4">`;
        html += `<h4 class="text-xs font-semibold mb-2 uppercase tracking-wider text-gray-500 dark:text-gray-400">${escapeHtml(key)}</h4>`;
        html += renderScoresSection(value, depth + 1);
        html += `</div>`;
      }
    }
    // Array
    else if (key === "Invalid references" && Array.isArray(value)) {
      html += renderFileReferenceInvalidTable(value);
    } else if (key === "File metadata" && Array.isArray(value)) {
      html += renderFileReferenceMetadataTable(value);
    } else if (Array.isArray(value)) {
      html += `<div class="mb-4">`;
      html += `<h4 class="text-xs font-semibold mb-2 uppercase tracking-wider text-gray-500 dark:text-gray-400">${escapeHtml(key)} <span class="normal-case font-normal">(${value.length})</span></h4>`;
      if (value.length > 0 && typeof value[0] !== "object") {
        html += `<p class="text-sm text-gray-700 dark:text-gray-300">${escapeHtml(value.map(formatValue).join(", "))}</p>`;
      } else {
        value.forEach((item, i) => {
          if (isObject(item)) {
            html += `<details class="mb-1 ml-2 border-l-2 border-gray-200 dark:border-gray-600 pl-3">`;
            html += `<summary class="cursor-pointer text-sm text-gray-700 dark:text-gray-300">[${i}]</summary>`;
            html += `<div class="mt-1">${renderScoresSection(item, depth + 1)}</div>`;
            html += `</details>`;
          } else {
            html += `<div class="text-sm text-gray-700 dark:text-gray-300">${escapeHtml(formatValue(item))}</div>`;
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
      html += `<a href="${escapeHtml(value)}" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white rounded-lg bg-green-600 hover:bg-green-700 focus:ring-4 focus:ring-green-300 dark:bg-green-500 dark:hover:bg-green-600 transition-colors">`;
      html += `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>`;
      html += `Download CSV</a>`;
      html += `</div>`;
    }
    // Scalar → Flowbite list-group style row
    else {
      html += `<div class="flex justify-between items-center px-4 py-2.5 text-sm border-b border-gray-200 dark:border-gray-700 last:border-b-0">`;
      html += `<span class="font-medium text-gray-900 dark:text-white">${escapeHtml(key)}</span>`;
      html += `<span class="font-mono text-xs text-gray-500 dark:text-gray-400">${escapeHtml(formatValue(value))}</span>`;
      html += `</div>`;
    }
  }

  return html;
}

// ==================== Globus Compute ====================

/** Switch between Upload, Globus, and CLI tabs on the landing page. */
function switchUploadTab(tab) {
  const localPanel = document.getElementById("local-upload");
  const globusPanel = document.getElementById("globus-panel");
  const cliPanel = document.getElementById("cli-panel");
  const tabLocal = document.getElementById("tab-local");
  const tabGlobus = document.getElementById("tab-globus");
  const tabCli = document.getElementById("tab-cli");

  if (!localPanel) {
    console.error("switchUploadTab: localPanel not found");
    return;
  }

  const base =
    "upload-tab flex-1 py-2.5 text-sm font-medium text-center border-b-2";
  const activeClass =
    "border-blue-600 text-blue-600 dark:text-blue-500 dark:border-blue-500";
  const inactiveClass =
    "border-transparent text-gray-500 hover:text-gray-600 hover:border-gray-300 dark:text-gray-400";

  // Hide all panels and deactivate all tabs
  localPanel.classList.add("hidden");
  if (globusPanel) globusPanel.classList.add("hidden");
  if (cliPanel) cliPanel.classList.add("hidden");
  if (tabLocal) tabLocal.className = `${base} ${inactiveClass}`;
  if (tabGlobus) tabGlobus.className = `${base} ${inactiveClass}`;
  if (tabCli) tabCli.className = `${base} ${inactiveClass}`;

  // Activate the selected tab and panel
  if (tab === "globus" && globusPanel) {
    globusPanel.classList.remove("hidden");
    if (tabGlobus) tabGlobus.className = `${base} ${activeClass}`;
  } else if (tab === "cli" && cliPanel) {
    cliPanel.classList.remove("hidden");
    if (tabCli) tabCli.className = `${base} ${activeClass}`;
  } else {
    localPanel.classList.remove("hidden");
    if (tabLocal) tabLocal.className = `${base} ${activeClass}`;
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

    if (
      data.summary_statistics &&
      Object.keys(data.summary_statistics).length > 0
    ) {
      const features = Object.keys(data.summary_statistics);
      const allStats = Object.keys(data.summary_statistics[features[0]]);
      html +=
        '<h3 class="text-sm font-semibold text-gray-900 dark:text-white mb-3 uppercase tracking-wide">Numerical Features</h3>';
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

    html += buildCategoricalSummaryTable(data.categorical_summary);

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
  }
  inputs.forEach((el) => {
    el.disabled = true;
    el.classList.add("opacity-50");
  });

  const fileName = filePath.split("/").pop();

  if (loadBtn) _globusBtnLoading(loadBtn, "Checking endpoint...");
  if (typeof showToast === "function")
    showToast("Checking endpoint compatibility...", "info");

  // Step 1: verify the endpoint's aidrin/Python versions match this server
  // BEFORE submitting any work. Blocks connection on an incompatible or
  // too-old endpoint instead of failing later during metric polling.
  fetch("/globus/check-endpoint", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint_id: endpointId }),
  })
    .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
    .then(({ ok, data }) => {
      if (!ok || data.compatible === false) {
        _reEnableGlobusForm();
        const msg =
          data.warnings && data.warnings.length
            ? data.warnings.join(" ")
            : data.error ||
              "Endpoint is not compatible with this AIDRIN server.";
        if (typeof showToast === "function") showToast(msg, "error");
        return;
      }
      // Step 2: endpoint is compatible — proceed to load the dataset.
      if (loadBtn) _globusBtnLoading(loadBtn, "Connecting...");
      _submitGlobusDataset(endpointId, filePath, fileName, fileType);
    })
    .catch((err) => {
      _reEnableGlobusForm();
      if (typeof showToast === "function")
        showToast("Endpoint check failed: " + err.message, "error");
    });
}

// Submit the initial metric once the endpoint has been verified compatible.
function _submitGlobusDataset(endpointId, filePath, fileName, fileType) {
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

// Show a spinner + label inside the Globus load button while it's busy.
function _globusBtnLoading(btn, label) {
  btn.innerHTML =
    '<span class="inline-flex items-center justify-center gap-2">' +
    '<svg class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">' +
    '<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>' +
    '<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>' +
    "</svg>" +
    "<span>" +
    label +
    "</span>" +
    "</span>";
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

// ==================== Custom Criteria Outliers ====================

function initCustomOutlierEditor() {
  const addButton = document.getElementById("custom-outlier-add-rule");
  if (addButton) {
    addButton.addEventListener("click", () => addCustomOutlierRuleRow());
  }
  const saveButton = document.getElementById("custom-outlier-save-rules");
  if (saveButton) {
    saveButton.addEventListener("click", downloadCustomOutlierRules);
  }
  const checkbox = document.getElementById("toggleButton_custom_outliers");
  document
    .querySelectorAll('input[name="custom_outlier_rule_source"]')
    .forEach((input) => {
      input.addEventListener("change", () => {
        clearCustomOutlierResults();
        updateCustomOutlierRuleSource();
      });
    });
  updateCustomOutlierRuleSource();
  if (document.getElementById("custom-outlier-editor") && checkbox?.checked) {
    toggleCustomOutlierEditor(checkbox);
  }
}

function toggleCustomOutlierEditor(checkbox) {
  const editor = document.getElementById("custom-outlier-editor");
  if (!editor) return;
  editor.classList.toggle("hidden", !checkbox.checked);
  if (checkbox.checked && customOutlierRuleSource() === "manual") {
    loadCustomOutlierTargets().then(() => {
      const list = document.getElementById("custom-outlier-rule-list");
      if (list && list.children.length === 0) addCustomOutlierRuleRow();
    });
  }
}

function customOutlierRuleSource() {
  return (
    document.querySelector('input[name="custom_outlier_rule_source"]:checked')
      ?.value || "manual"
  );
}

function updateCustomOutlierRuleSource() {
  const isFileSource = customOutlierRuleSource() === "file";
  document
    .getElementById("custom-outlier-manual-source")
    ?.classList.toggle("hidden", isFileSource);
  document
    .getElementById("custom-outlier-file-source")
    ?.classList.toggle("hidden", !isFileSource);

  const checkbox = document.getElementById("toggleButton_custom_outliers");
  if (checkbox?.checked && !isFileSource) {
    loadCustomOutlierTargets().then(() => {
      const list = document.getElementById("custom-outlier-rule-list");
      if (list && list.children.length === 0) addCustomOutlierRuleRow();
    });
  }
}

function clearCustomOutlierResults() {
  const resultsSection = document.getElementById("results-section");
  if (resultsSection) resultsSection.style.display = "none";
  const metricsDiv = document.getElementById("metrics");
  if (metricsDiv) metricsDiv.innerHTML = "";
  const buttonsContainer = document.getElementById("buttonsContainer");
  if (buttonsContainer) buttonsContainer.style.display = "none";
  lastMetricResult = null;
}

function loadCustomOutlierTargets() {
  const message = document.getElementById("custom-outlier-message");
  if (window.AIDRIN_GLOBUS_MODE) {
    return loadGlobusCustomOutlierTargets(message);
  }
  return fetch("/custom-outlier-targets", { method: "POST" })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        customOutlierTargets = data.targets || [];
        updateCustomOutlierTargetOptions();
        if (message) message.classList.add("hidden");
      } else if (message) {
        message.textContent = data.message || "Unable to load targets.";
        message.classList.remove("hidden");
      }
    })
    .catch((err) => {
      if (message) {
        message.textContent = "Unable to load targets: " + err.message;
        message.classList.remove("hidden");
      }
    });
}

function loadGlobusCustomOutlierTargets(message) {
  const endpointId = window.AIDRIN_GLOBUS_ENDPOINT || "";
  const filePath = window.AIDRIN_GLOBUS_FILE_PATH || "";
  const fileName = window.AIDRIN_GLOBUS_FILE_NAME || "";
  const fileType = window.AIDRIN_GLOBUS_FILE_TYPE || "";
  if (!endpointId || !filePath) {
    if (message) {
      message.textContent =
        "Remote target discovery requires a loaded Globus file.";
      message.classList.remove("hidden");
    }
    return Promise.resolve();
  }
  if (message) {
    message.textContent = "Loading remote targets...";
    message.classList.remove("hidden");
  }
  return fetch("/globus/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      endpoint_id: endpointId,
      file_path: filePath,
      file_name: fileName,
      file_type: fileType,
      metric_name: "custom_outlier_targets",
      params: {},
    }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.error) throw new Error(data.error);
      if (!data.task_id) return data.result || data;
      return pollGlobusCustomOutlierTargets(data.task_id);
    })
    .then((result) => {
      if (result && result.success) {
        customOutlierTargets = result.targets || [];
        updateCustomOutlierTargetOptions();
        if (message) message.classList.add("hidden");
      } else if (message) {
        message.textContent =
          (result && (result.message || result.error)) ||
          "Remote target discovery failed.";
        message.classList.remove("hidden");
      }
    })
    .catch((err) => {
      if (message) {
        message.textContent = "Remote target discovery failed: " + err.message;
        message.classList.remove("hidden");
      }
    });
}

function pollGlobusCustomOutlierTargets(taskId) {
  let attempts = 0;
  return new Promise((resolve, reject) => {
    const poll = () => {
      attempts += 1;
      fetch(`/globus/check-task/${taskId}`)
        .then((r) => r.json())
        .then((data) => {
          if (data.status === "completed") {
            resolve(data.result);
          } else if (data.status === "failed") {
            reject(new Error(data.error || "Task failed"));
          } else if (attempts < 150) {
            setTimeout(poll, 2000);
          } else {
            reject(new Error("Timed out waiting for remote target discovery"));
          }
        })
        .catch(reject);
    };
    poll();
  });
}

function addCustomOutlierRuleRow() {
  const list = document.getElementById("custom-outlier-rule-list");
  if (!list) return;
  customOutlierRuleCounter += 1;
  const row = document.createElement("div");
  row.className =
    "custom-outlier-rule relative rounded-lg border border-gray-200 dark:border-gray-700 p-2";
  row.dataset.ruleId = `custom-rule-${customOutlierRuleCounter}`;
  row.innerHTML = `
    <div class="grid gap-2 pr-7 md:grid-cols-[minmax(9rem,0.6fr)_minmax(16rem,1.4fr)_auto]">
      <label class="text-xs font-medium text-gray-700 dark:text-gray-300">Rule name
        <input type="text" data-field="name" value="Rule ${customOutlierRuleCounter}"
               class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
      </label>
      <div class="text-xs font-medium text-gray-700 dark:text-gray-300">
        <span>Target</span>
        <div class="mt-1 flex items-center gap-2">
          <select data-field="target_match" aria-label="Target match mode"
                  class="w-28 shrink-0 rounded-lg border border-gray-300 bg-gray-50 px-2 py-1 text-xs font-medium text-gray-900 shadow-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white">
            <option value="exact">Exact name</option>
            <option value="regex">Regex</option>
          </select>
          <div data-section="target-exact" class="min-w-0 flex-1">
            <div data-field="target" data-target-picker data-multiple="false" data-placeholder="Select a target..." class="relative">
              <button type="button" data-target-picker-button aria-haspopup="listbox" aria-expanded="false"
                      class="flex w-full items-center justify-between gap-2 rounded-lg border border-gray-300 bg-gray-50 px-2 py-1 text-left text-sm font-normal text-gray-900 shadow-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white">
                <span data-target-picker-summary>Select a target...</span><span aria-hidden="true">&#9662;</span>
              </button>
              <div data-target-picker-menu class="absolute z-30 mt-1 hidden w-full min-w-64 rounded-lg border border-gray-200 bg-white p-2 shadow-lg dark:border-gray-600 dark:bg-gray-700">
                <input type="search" data-target-picker-search aria-label="Search exact targets" placeholder="Search targets..." autocomplete="off"
                       class="mb-2 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-normal text-gray-900 dark:border-gray-600 dark:bg-gray-800 dark:text-white" />
                <div data-target-picker-options role="listbox" class="max-h-56 space-y-1 overflow-y-auto"></div>
                <p data-target-picker-empty class="hidden px-2 py-3 text-sm font-normal text-gray-500 dark:text-gray-400">No matching targets.</p>
              </div>
            </div>
          </div>
          <div data-section="target-regex" class="hidden min-w-0 flex-1">
            <input type="text" data-field="target_regex" placeholder="Target pattern, e.g. ^/S_[0-9]+_[0-9]+/X$" aria-label="Target pattern (regular expression)"
                   title="Matches complete target names in this file."
                   class="w-full rounded-lg border border-gray-300 bg-white px-2 py-1 font-mono text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            <p data-section="target-regex-preview" class="mt-1 text-xs font-normal text-gray-500 dark:text-gray-400"></p>
          </div>
          <label data-section="target-type" class="hidden w-36 shrink-0">
            <span class="sr-only">Match targets of type</span>
            <select data-field="target_type" aria-label="Match targets of type"
                    class="w-full rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white"></select>
          </label>
        </div>
      </div>
      <label class="flex items-center gap-2 pt-5 whitespace-nowrap text-xs font-medium text-gray-700 dark:text-gray-300">
        <input type="checkbox" data-field="allow_missing" class="rounded border-gray-300" />
        Allow missing values
      </label>
    </div>
    <button type="button" data-action="remove" aria-label="Remove rule" title="Remove rule"
            class="absolute right-2 top-2 px-2 py-1 text-xs font-medium text-red-700 rounded-lg border border-red-200 hover:bg-red-50 dark:text-red-300 dark:border-red-800 dark:hover:bg-red-900/20">
      Remove
    </button>
    <div data-section="criteria-tree" class="mt-2 rounded-lg bg-gray-50 p-2 dark:bg-gray-900/40">
      <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
        <label class="text-xs font-medium text-gray-700 dark:text-gray-300">Valid when
          <select data-field="criteria_op"
                  class="ml-2 rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
            <option value="and">All conditions match</option>
            <option value="or">Any condition matches</option>
            <option value="not">No conditions match</option>
          </select>
        </label>
        <button type="button" data-action="add-condition"
                class="px-2.5 py-1 text-xs font-medium text-blue-700 rounded-lg border border-blue-200 hover:bg-blue-50 dark:text-blue-300 dark:border-blue-800 dark:hover:bg-blue-900/20">
          Add condition
        </button>
      </div>
      <p class="mb-1 text-xs text-gray-600 dark:text-gray-300">Values that do not satisfy these conditions are flagged.</p>
      <div data-section="criteria-conditions" class="space-y-2"></div>
    </div>
    `;
  list.appendChild(row);

  row.querySelector('[data-action="remove"]').addEventListener("click", () => {
    row.remove();
    serializeCustomOutlierRules();
  });
  row
    .querySelector('[data-action="add-condition"]')
    .addEventListener("click", () => {
      addCustomOutlierConditionRow(row);
      serializeCustomOutlierRules();
    });
  row
    .querySelector('[data-field="target_match"]')
    .addEventListener("change", () => updateCustomOutlierTargetMatch(row));
  row
    .querySelector('[data-field="target_regex"]')
    .addEventListener("input", () => updateCustomOutlierRegexPreview(row));
  row
    .querySelector('[data-field="target_type"]')
    .addEventListener("change", () => updateCustomOutlierRegexPreview(row));
  row
    .querySelector('[data-field="target"][data-target-picker]')
    .addEventListener("target-picker-change", serializeCustomOutlierRules);
  row.addEventListener("input", serializeCustomOutlierRules);
  row.addEventListener("change", serializeCustomOutlierRules);

  addCustomOutlierConditionRow(row);
  updateCustomOutlierTargetOptions(row);
  updateCustomOutlierTargetMatch(row);
  serializeCustomOutlierRules();
}

function addCustomOutlierConditionRow(ruleRow) {
  const list = ruleRow.querySelector('[data-section="criteria-conditions"]');
  if (!list) return;
  const condition = document.createElement("div");
  condition.className =
    "custom-outlier-condition rounded-md bg-white p-1.5 shadow-sm dark:bg-gray-800";
  condition.innerHTML = `
    <div class="grid gap-2 md:grid-cols-[minmax(9rem,0.7fr)_1fr_auto]">
      <label class="text-xs font-medium text-gray-700 dark:text-gray-300">Type
        <select data-field="condition_type"
                class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
          <option value="range">Range</option>
          <option value="regex">Regex</option>
        </select>
      </label>
      <div data-section="condition-range" class="grid gap-2 sm:grid-cols-4">
        <label class="text-xs font-medium text-gray-700 dark:text-gray-300">Min
          <input type="number" step="any" data-field="condition_min"
                 class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        </label>
        <label class="text-xs font-medium text-gray-700 dark:text-gray-300">Max
          <input type="number" step="any" data-field="condition_max"
                 class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        </label>
        <label class="flex items-center gap-2 pt-4 text-xs font-medium text-gray-700 dark:text-gray-300">
          <input type="checkbox" data-field="condition_min_inclusive" checked class="rounded border-gray-300" />
          Include min
        </label>
        <label class="flex items-center gap-2 pt-4 text-xs font-medium text-gray-700 dark:text-gray-300">
          <input type="checkbox" data-field="condition_max_inclusive" checked class="rounded border-gray-300" />
          Include max
        </label>
      </div>
      <div data-section="condition-regex" class="hidden">
        <label class="text-xs font-medium text-gray-700 dark:text-gray-300">Pattern
          <input type="text" data-field="condition_pattern" value=".*"
                 class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-2 py-1 font-mono text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        </label>
      </div>
      <button type="button" data-action="remove-condition"
              class="self-end px-2.5 py-1 text-xs font-medium text-red-700 rounded-lg border border-red-200 hover:bg-red-50 dark:text-red-300 dark:border-red-800 dark:hover:bg-red-900/20">
        Remove
      </button>
    </div>`;
  list.appendChild(condition);
  condition
    .querySelector('[data-field="condition_type"]')
    .addEventListener("change", () => {
      updateCustomOutlierConditionSections(condition);
    });
  condition
    .querySelector('[data-action="remove-condition"]')
    .addEventListener("click", () => {
      condition.remove();
      serializeCustomOutlierRules();
    });
  updateCustomOutlierConditionSections(condition);
}

function updateCustomOutlierTargetOptions(scope) {
  const root = scope || document;
  root
    .querySelectorAll('[data-field="target"][data-target-picker]')
    .forEach((picker) => {
      renderTargetPicker(picker, customOutlierTargets);
    });
  root.querySelectorAll('[data-field="target_type"]').forEach((select) => {
    const selected = select.value;
    const targetTypes = [
      ...new Set(customOutlierTargets.map((target) => target.target_type)),
    ];
    select.innerHTML = "";
    targetTypes.forEach((targetType) => {
      const option = document.createElement("option");
      option.value = targetType;
      option.textContent =
        targetType === "hdf5_dataset" ? "HDF5 datasets" : "Columns";
      select.appendChild(option);
    });
    if (selected && targetTypes.includes(selected)) select.value = selected;
  });
  root
    .querySelectorAll(".custom-outlier-rule")
    .forEach(updateCustomOutlierRegexPreview);
}

function updateCustomOutlierTargetMatch(row) {
  const isRegex =
    row.querySelector('[data-field="target_match"]')?.value === "regex";
  row
    .querySelector('[data-section="target-exact"]')
    ?.classList.toggle("hidden", isRegex);
  row
    .querySelector('[data-section="target-regex"]')
    ?.classList.toggle("hidden", !isRegex);
  const targetTypes = [
    ...new Set(customOutlierTargets.map((target) => target.target_type)),
  ];
  row
    .querySelector('[data-section="target-type"]')
    ?.classList.toggle("hidden", !isRegex || targetTypes.length <= 1);
  updateCustomOutlierRegexPreview(row);
}

function updateCustomOutlierRegexPreview(row) {
  updateRegexTargetPreview(
    row.querySelector('[data-section="target-regex-preview"]'),
    row.querySelector('[data-field="target_regex"]')?.value.trim(),
    customOutlierTargets,
    customOutlierRegexTargetType(row),
  );
}

function customOutlierRegexTargetType(row) {
  const targetTypes = [
    ...new Set(customOutlierTargets.map((target) => target.target_type)),
  ];
  if (targetTypes.length === 1) return targetTypes[0];
  return row.querySelector('[data-field="target_type"]')?.value || "column";
}

function serializeCustomOutlierRules() {
  const rows = document.querySelectorAll(".custom-outlier-rule");
  const rules = [];
  rows.forEach((row, index) => {
    const targetPicker = row.querySelector(
      '[data-field="target"][data-target-picker]',
    );
    const selectedTarget = selectedTargetPickerInputs(targetPicker)[0];
    const targetMatch =
      row.querySelector('[data-field="target_match"]')?.value || "exact";
    const target =
      targetMatch === "regex"
        ? row.querySelector('[data-field="target_regex"]')?.value.trim()
        : selectedTarget?.value;
    if (!target) return;
    const id = row.dataset.ruleId || `custom-rule-${index + 1}`;
    const rule = {
      id,
      name: row.querySelector('[data-field="name"]')?.value || id,
      target,
      target_type:
        targetMatch === "regex"
          ? customOutlierRegexTargetType(row)
          : selectedTarget?.dataset.targetType || "column",
      allow_missing: Boolean(
        row.querySelector('[data-field="allow_missing"]')?.checked,
      ),
      criteria: serializeCustomOutlierCriteria(row),
    };
    if (targetMatch === "regex") rule.target_match = "regex";
    rules.push(rule);
  });
  const hidden = document.getElementById("custom-outlier-rules-json");
  if (hidden) hidden.value = JSON.stringify(rules);
  return rules;
}

function downloadCustomOutlierRules() {
  const rules = serializeCustomOutlierRules();
  if (!validateCustomOutlierRuleSelection(rules)) return;

  const blob = new Blob([JSON.stringify(rules, null, 2)], {
    type: "application/json",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "custom-outlier-rules.json";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}

function showCustomOutlierFileError(message) {
  const element = document.getElementById("custom-outlier-file-message");
  if (!element) return;
  element.textContent = message;
  element.classList.remove("hidden");
}

function clearCustomOutlierFileError() {
  const element = document.getElementById("custom-outlier-file-message");
  if (element) element.classList.add("hidden");
}

function parseCustomOutlierRulesJson(text) {
  let rules;
  try {
    rules = JSON.parse(text);
  } catch (error) {
    throw new Error("The rules file must contain valid JSON.");
  }
  if (!Array.isArray(rules)) {
    throw new Error("The rules file must contain a JSON array.");
  }
  if (rules.length === 0) {
    throw new Error("The rules file must contain at least one rule.");
  }
  return rules;
}

function validateCustomOutlierRulesFile(rules) {
  const seenIds = new Set();
  const seenKeys = new Map();
  for (const [index, rule] of rules.entries()) {
    if (!rule || typeof rule !== "object" || Array.isArray(rule)) {
      return `Rule ${index + 1} must be an object.`;
    }
    const ruleId = String(rule.id ?? "").trim();
    if (!ruleId) return `Rule ${index + 1} requires a non-empty id.`;
    if (seenIds.has(ruleId))
      return `Duplicate custom outlier rule id: ${ruleId}.`;
    seenIds.add(ruleId);

    const ruleKey =
      ruleId.replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "") ||
      "rule";
    if (seenKeys.has(ruleKey)) {
      return `Custom outlier rule ids resolve to the same output key: ${seenKeys.get(ruleKey)} and ${ruleId}.`;
    }
    seenKeys.set(ruleKey, ruleId);

    const ruleName = rule.name || ruleId;
    if (!String(rule.target ?? "").trim())
      return `${ruleName} requires a target.`;
    const targetMatch = String(rule.target_match ?? "exact")
      .trim()
      .toLowerCase();
    if (!["exact", "regex"].includes(targetMatch)) {
      return `${ruleName} has an unsupported target match mode.`;
    }
    if (
      !["column", "hdf5_dataset"].includes(
        String(rule.target_type ?? "").trim(),
      )
    ) {
      return `${ruleName} has an unsupported target type.`;
    }
    if (
      [
        "criteria_type",
        "min",
        "max",
        "pattern",
        "min_inclusive",
        "max_inclusive",
      ].some((field) => field in rule)
    ) {
      return `${ruleName} must use criteria tree syntax.`;
    }
    const error = validateCustomOutlierCriteria(rule.criteria, ruleName);
    if (error) return error;
  }
  return null;
}

async function resolveCustomOutlierRules() {
  if (customOutlierRuleSource() === "manual") {
    const rules = serializeCustomOutlierRules();
    return validateCustomOutlierRuleSelection(rules) ? rules : null;
  }

  const fileInput = document.getElementById("custom-outlier-rules-file");
  const file = fileInput?.files?.[0];
  if (!file) {
    showCustomOutlierFileError("Choose a JSON rules file before submitting.");
    return null;
  }

  try {
    const rules = parseCustomOutlierRulesJson(await file.text());
    const error = validateCustomOutlierRulesFile(rules);
    if (error) throw new Error(error);
    clearCustomOutlierFileError();
    return rules;
  } catch (error) {
    showCustomOutlierFileError(error.message);
    return null;
  }
}

function updateCustomOutlierConditionSections(condition) {
  const type = condition.querySelector('[data-field="condition_type"]')?.value;
  condition
    .querySelector('[data-section="condition-range"]')
    ?.classList.toggle("hidden", type !== "range");
  condition
    .querySelector('[data-section="condition-regex"]')
    ?.classList.toggle("hidden", type !== "regex");
}

function serializeCustomOutlierCriteria(row) {
  const op = row.querySelector('[data-field="criteria_op"]')?.value || "and";
  const conditions = Array.from(
    row.querySelectorAll(".custom-outlier-condition"),
  )
    .map(serializeCustomOutlierCondition)
    .filter(Boolean);

  if (op === "not") {
    if (conditions.length === 0) return { op: "not", condition: null };
    if (conditions.length === 1) {
      return { op: "not", condition: conditions[0] };
    }
    return { op: "not", condition: { op: "or", conditions } };
  }

  return { op, conditions };
}

function serializeCustomOutlierCondition(condition) {
  const type =
    condition.querySelector('[data-field="condition_type"]')?.value || "range";
  if (type === "regex") {
    return {
      type: "regex",
      pattern:
        condition.querySelector('[data-field="condition_pattern"]')?.value ||
        "",
    };
  }

  const min = condition.querySelector('[data-field="condition_min"]')?.value;
  const max = condition.querySelector('[data-field="condition_max"]')?.value;
  const criteria = {
    type: "range",
    min_inclusive: Boolean(
      condition.querySelector('[data-field="condition_min_inclusive"]')
        ?.checked,
    ),
    max_inclusive: Boolean(
      condition.querySelector('[data-field="condition_max_inclusive"]')
        ?.checked,
    ),
  };
  if (min !== "") criteria.min = min;
  if (max !== "") criteria.max = max;
  return criteria;
}

function validateCustomOutlierRuleSelection(rules) {
  if (!Array.isArray(rules) || rules.length === 0) {
    const hasRows = Boolean(document.querySelector(".custom-outlier-rule"));
    return showCustomOutlierValidationError(
      hasRows
        ? "Select a target for each custom outlier rule before submitting."
        : "Add at least one custom outlier rule before submitting.",
    );
  }
  for (const rule of rules) {
    const ruleName = rule.name || rule.id || "Custom outlier rule";
    const error = validateCustomOutlierCriteria(rule.criteria, ruleName);
    if (error) return showCustomOutlierValidationError(error);
  }
  return true;
}

function validateCustomOutlierCriteria(criteria, ruleName) {
  if (!criteria || typeof criteria !== "object") {
    return `${ruleName} requires criteria.`;
  }
  const op = String(criteria.op || "")
    .trim()
    .toLowerCase();
  if (op === "and" || op === "or") {
    if (
      !Array.isArray(criteria.conditions) ||
      criteria.conditions.length === 0
    ) {
      return `${ruleName} requires at least one condition.`;
    }
    for (const condition of criteria.conditions) {
      const error = validateCustomOutlierCriteria(condition, ruleName);
      if (error) return error;
    }
    return null;
  }
  if (op === "not") {
    if (!criteria.condition) {
      return `${ruleName} requires a condition for NOT.`;
    }
    return validateCustomOutlierCriteria(criteria.condition, ruleName);
  }
  if (op) return `${ruleName} has an unsupported operator: ${op}.`;
  if (criteria.type === "range") {
    const hasMin =
      criteria.min !== undefined &&
      criteria.min !== null &&
      criteria.min !== "";
    const hasMax =
      criteria.max !== undefined &&
      criteria.max !== null &&
      criteria.max !== "";
    if (!hasMin && !hasMax) {
      return `${ruleName} range condition requires min or max.`;
    }
    for (const field of ["min", "max"]) {
      if (
        criteria[field] !== undefined &&
        criteria[field] !== null &&
        criteria[field] !== "" &&
        !Number.isFinite(Number(criteria[field]))
      ) {
        return `${ruleName} range ${field} must be a finite number.`;
      }
    }
    return null;
  }
  if (criteria.type === "regex") return null;
  return `${ruleName} has an unsupported condition type.`;
}

function showCustomOutlierValidationError(text) {
  const message = document.getElementById("custom-outlier-message");
  if (message) {
    message.textContent = text;
    message.classList.remove("hidden");
  }
  if (typeof showToast === "function") {
    showToast(text, "error");
  }
  return false;
}

function customOutlierLimitValue(rawValue, defaultValue) {
  if (rawValue === null || rawValue === undefined || rawValue === "") {
    return defaultValue;
  }
  const value = Number(rawValue);
  return Number.isFinite(value) && value >= 0 ? value : defaultValue;
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

function storeAsyncMetricResult(metricName, result) {
  if (!lastMetricResult || typeof lastMetricResult !== "object") {
    lastMetricResult = {};
  }
  lastMetricResult[metricName] = result;
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
    data_structure: "Data Structure",
    completeness: "Column-Level Completeness",
    outliers: "Outliers",
    duplicates: "Duplicity",
    row_level_completeness: "Row-Level Completeness",
    duplicity_by_features: "Duplicates by Selected Features",
    feature_coverage_ratio: "Feature Coverage Ratio",
    temporal_completeness: "Temporal Completeness",
    null_count_trend: "Null Count Trend",
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
    Completeness: "Column-Level Completeness",
    constant_feature_count: "Constant Feature Count",
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
          storeAsyncMetricResult(metricName, response.result);

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
  html += `<h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">${escapeHtml(type)}</h3>`;

  if (error) {
    html += `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-red-900/20 dark:text-red-400" role="alert">${escapeHtml(error)}</div>`;
  } else {
    if (description) {
      html += `<p class="text-sm text-gray-600 dark:text-gray-400 mb-4 leading-relaxed">${escapeHtml(description)}</p>`;
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
          <p class="text-gray-700 dark:text-gray-300 leading-relaxed">${escapeHtml(interpretation)}</p>
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
  // Errors stay until the user dismisses them (via the X); other toasts
  // auto-close. An explicit duration always wins; duration 0 = persistent.
  if (duration === undefined) {
    duration = type === "error" ? 0 : 4000;
  }

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

  // Auto-dismiss (skipped when duration is 0 — persistent, close via the X)
  if (duration > 0) {
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(-8px)";
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }
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

function flattenOutlierExportRows(exportByRule) {
  if (!exportByRule || typeof exportByRule !== "object") return [];
  const rows = [];
  for (const [ruleKey, ruleRows] of Object.entries(exportByRule)) {
    if (!Array.isArray(ruleRows)) continue;
    for (const row of ruleRows) {
      if (!row || typeof row !== "object") continue;
      rows.push({
        rule_key: ruleKey,
        rule_id: row.rule_id || "",
        rule_name: row.rule_name || "",
        target: row.target || "",
        target_type: row.target_type || "",
        value: row.value,
        reason: row.reason || "",
        location: row.location || {},
      });
    }
  }
  return rows;
}

function flattenOutlierPreviewRows(previewByRule) {
  if (!previewByRule || typeof previewByRule !== "object") return [];
  const rows = [];
  for (const [ruleKey, ruleRows] of Object.entries(previewByRule)) {
    if (!Array.isArray(ruleRows)) continue;
    for (const row of ruleRows) {
      if (!row || typeof row !== "object") continue;
      rows.push({
        rule_key: ruleKey,
        rule_id: row.rule_id || "",
        rule_name: row.rule_name || row.rule_id || ruleKey,
        target: row.target || "",
        target_type: row.target_type || "",
        value: row.value,
        reason: row.reason || "",
        flag: row.flag || formatOutlierFlagFallback(row.reason),
        location: row.location || {},
        raw: row,
      });
    }
  }
  return rows;
}

function renderCustomOutlierPreviewTable(previewByRule) {
  const rows = flattenOutlierPreviewRows(previewByRule);
  let html = `<div class="mb-4">`;
  html += `<div class="mb-2 flex flex-wrap items-center justify-between gap-2">`;
  html += `<h4 class="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Outlier preview <span class="normal-case font-normal">(${rows.length})</span></h4>`;
  html += `</div>`;
  html += `<p class="mb-2 text-xs text-gray-600 dark:text-gray-300">Preview rows failed a valid-value condition.</p>`;
  if (rows.length === 0) {
    html += `<p class="text-sm text-gray-600 dark:text-gray-300">No preview rows.</p>`;
    html += `</div>`;
    return html;
  }

  html += `<div class="relative overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">`;
  html += `<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">`;
  html += `<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400"><tr>`;
  html += `<th scope="col" class="px-3 py-2.5">Rule</th>`;
  html += `<th scope="col" class="px-3 py-2.5">Location</th>`;
  html += `<th scope="col" class="px-3 py-2.5 text-right">Value</th>`;
  html += `<th scope="col" class="px-3 py-2.5">Why flagged</th>`;
  html += `<th scope="col" class="px-3 py-2.5 text-right">Details</th>`;
  html += `</tr></thead><tbody>`;
  rows.forEach((row, index) => {
    const stripe =
      index % 2 === 0
        ? "bg-white dark:bg-gray-800"
        : "bg-gray-50 dark:bg-gray-700/50";
    const locationDisplay =
      row.location.display ||
      row.location.path ||
      formatValue(row.location.index || "");
    html += `<tr class="${stripe} border-b dark:border-gray-700 last:border-b-0 align-top">`;
    html += `<td class="px-3 py-2 font-medium text-gray-900 dark:text-white">${escapeHtml(row.rule_name)}</td>`;
    html += `<td class="px-3 py-2 font-mono text-xs text-gray-700 dark:text-gray-300 whitespace-nowrap">${escapeHtml(formatValue(locationDisplay))}</td>`;
    html += `<td class="px-3 py-2 text-right font-mono text-xs text-gray-700 dark:text-gray-300">${escapeHtml(formatValue(row.value))}</td>`;
    html += `<td class="px-3 py-2 font-mono text-xs text-gray-900 dark:text-white whitespace-nowrap">${escapeHtml(row.flag)}</td>`;
    html += `<td class="px-3 py-2 text-right">`;
    html += `<details class="inline-block text-left">`;
    html += `<summary class="cursor-pointer text-xs font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300">Expand</summary>`;
    html += `<div class="mt-2 min-w-72 max-w-xl rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800">`;
    html += `<div class="mb-2 text-xs text-gray-600 dark:text-gray-300"><span class="font-medium text-gray-900 dark:text-white">Target:</span> ${escapeHtml(row.target)}</div>`;
    html += `<pre class="max-h-64 overflow-auto text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words">${escapeHtml(JSON.stringify(row.raw, null, 2))}</pre>`;
    html += `</div></details></td>`;
    html += `</tr>`;
  });
  html += `</tbody></table></div></div>`;
  return html;
}

function formatOutlierFlagFallback(reason) {
  const labels = {
    below_min: "< min",
    above_max: "> max",
    regex_mismatch: "!=",
    non_numeric: "NaN",
    missing: "missing",
  };
  return labels[reason] || reason || "";
}

function findCustomOutlierExport(result) {
  if (!result || typeof result !== "object") return null;
  const direct = result["Outlier export"];
  if (direct && typeof direct === "object") return direct;
  for (const value of Object.values(result)) {
    if (value && typeof value === "object" && value["Outlier export"]) {
      return value["Outlier export"];
    }
  }
  return null;
}

function downloadCustomOutlierExportCsv() {
  const exportByRule = findCustomOutlierExport(lastMetricResult);
  const rows = flattenOutlierExportRows(exportByRule);
  const headers = [
    "rule_key",
    "rule_id",
    "rule_name",
    "target",
    "target_type",
    "value",
    "reason",
    "location_display",
    "location_path",
    "location_index",
    "source_line",
    "row_index",
  ];
  const csvRows = [headers.join(",")];
  for (const row of rows) {
    const location = row.location || {};
    const values = [
      row.rule_key,
      row.rule_id,
      row.rule_name,
      row.target,
      row.target_type,
      row.value,
      row.reason,
      location.display || "",
      location.path || "",
      Array.isArray(location.index) ? location.index.join(";") : "",
      location.source_line ?? "",
      location.row_index ?? "",
    ];
    csvRows.push(values.map(csvEscape).join(","));
  }
  const blob = new Blob([csvRows.join("\n")], { type: "text/csv" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "custom-outlier-export.csv";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}

function csvEscape(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
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
  if (Array.isArray(v)) return v.length ? v.map(formatValue).join(", ") : "—";
  if (typeof v === "object")
    return Object.keys(v).length ? JSON.stringify(v) : "—";
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

/**
 * Build the categorical-features summary table from the /summary-statistics
 * `categorical_summary` payload. Returns "" when there are no categorical
 * features so callers can append unconditionally.
 * @param {Object} summary - {column: {count, unique, top, freq}}
 */
function buildCategoricalSummaryTable(summary) {
  if (!summary || Object.keys(summary).length === 0) return "";
  const cols = ["count", "unique", "top", "freq", "freq_pct"];
  const labels = {
    count: "Count",
    unique: "Unique",
    top: "Top",
    freq: "Freq",
    freq_pct: "Freq %",
  };
  let html =
    '<h3 class="text-sm font-semibold text-gray-900 dark:text-white mt-6 mb-3 uppercase tracking-wide">Categorical Features</h3>';
  html += '<div class="relative overflow-x-auto rounded-lg shadow-sm">';
  html +=
    '<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">';
  html +=
    '<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400"><tr>';
  html += '<th scope="col" class="px-4 py-3">Feature</th>';
  cols.forEach((c) => {
    html += `<th scope="col" class="px-4 py-3 text-right">${labels[c]}</th>`;
  });
  html += "</tr></thead><tbody>";
  Object.keys(summary).forEach((feat, i) => {
    const stripe =
      i % 2 === 0
        ? "bg-white dark:bg-gray-800"
        : "bg-gray-50 dark:bg-gray-700/50";
    const row = summary[feat] || {};
    html += `<tr class="${stripe} border-b dark:border-gray-700">`;
    html += `<td class="px-4 py-2 font-medium text-gray-900 dark:text-white whitespace-nowrap">${escapeHtml(feat)}</td>`;
    cols.forEach((c) => {
      let val;
      if (c === "top") val = escapeHtml(String(row[c] ?? "—"));
      else if (c === "freq_pct") val = `${row[c] ?? 0}%`;
      else val = row[c] ?? "—";
      html += `<td class="px-4 py-2 font-mono text-xs text-right">${val}</td>`;
    });
    html += "</tr>";
  });
  html += "</tbody></table></div>";
  return html;
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
    '<h3 class="text-sm font-semibold text-gray-900 dark:text-white mb-3 uppercase tracking-wide">Numerical Feature Distributions</h3>';
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
 * Show dataset picker for multi-dataset HDF5 files.
 */
function renderHdf5DatasetPicker(container, data) {
  const datasets = data.datasets || [];
  const groups = data.groups || [];
  const checked = new Set(data.current_checked_keys || []);
  const datasetByPath = new Map(datasets.map((ds) => [ds.path, ds]));
  const groupedPaths = new Set(
    groups.flatMap((group) => group.dataset_paths || []),
  );
  const ungrouped = datasets.filter((ds) => !groupedPaths.has(ds.path));

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  }

  function datasetLength(ds) {
    return Array.isArray(ds?.shape) && ds.shape.length === 1
      ? ds.shape[0]
      : null;
  }

  function renderDatasetRow(ds) {
    const shape = Array.isArray(ds.shape) ? ds.shape.join(" × ") : "";
    const length = datasetLength(ds);
    const escapedPath = escapeHtml(ds.path);
    const isChecked = checked.has(ds.path) ? "checked" : "";
    return `
      <label class="flex items-start gap-3 w-full p-3 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors cursor-pointer hdf5-dataset-option"
        data-path="${escapedPath}" data-length="${length ?? ""}" data-ndim="${ds.ndim ?? ""}">
        <input type="checkbox" class="mt-1 hdf5-dataset-checkbox" value="${escapedPath}" ${isChecked} />
        <div class="min-w-0">
          <div class="font-medium text-gray-900 dark:text-white">${escapedPath}</div>
          <div class="text-xs text-gray-500 dark:text-gray-400 mt-1">${escapeHtml(ds.dtype || "")}${shape ? ` · shape ${shape}` : ""}${ds.size != null ? ` · ${ds.size} values` : ""}</div>
        </div>
      </label>`;
  }

  function groupSummary(group) {
    const members = (group.dataset_paths || [])
      .map((path) => datasetByPath.get(path))
      .filter(Boolean);
    const lengths = new Set(
      members.map((ds) => datasetLength(ds)).filter((len) => len != null),
    );
    const count = members.length;
    if (lengths.size === 1) {
      return `${count} datasets · length ${[...lengths][0]}`;
    }
    if (lengths.size > 1) {
      return `${count} datasets · mixed lengths`;
    }
    return `${count} datasets`;
  }

  let html = `
    <div class="flex items-start gap-2 p-3 mb-4 text-sm rounded-lg bg-amber-50 text-amber-800 dark:bg-amber-900/20 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
      <svg class="w-4 h-4 mt-0.5 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"/></svg>
      <span>${escapeHtml(data.message || "Select compatible datasets to analyze.")}</span>
    </div>
    <p class="text-xs text-gray-500 dark:text-gray-400 mb-3">Select one dataset, multiple compatible 1D arrays, or use a group checkbox to select a whole subtree at once.</p>
    <div class="space-y-3 max-h-96 overflow-y-auto mb-4">`;

  groups.forEach((group) => {
    const groupId = escapeHtml(group.id);
    const memberPaths = (group.dataset_paths || [])
      .map((path) => escapeHtml(path))
      .join(",");
    html += `
      <div class="rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50/80 dark:bg-gray-900/20" data-hdf5-group="${groupId}">
        <label class="flex items-center gap-3 px-3 py-2 border-b border-gray-200 dark:border-gray-600 cursor-pointer">
          <input type="checkbox" class="hdf5-group-checkbox" data-group-id="${groupId}" data-group-paths="${memberPaths}" />
          <div class="min-w-0 flex-1">
            <div class="font-semibold text-sm text-gray-900 dark:text-white">${groupId}</div>
            <div class="text-xs text-gray-500 dark:text-gray-400">${groupSummary(group)}</div>
          </div>
        </label>
        <div class="space-y-2 p-2">`;
    (group.dataset_paths || []).forEach((path) => {
      const ds = datasetByPath.get(path);
      if (ds) html += renderDatasetRow(ds);
    });
    html += `</div></div>`;
  });

  if (ungrouped.length > 0) {
    html += `<div class="space-y-2">`;
    if (groups.length > 0) {
      html += `<div class="px-1 text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">Other datasets</div>`;
    }
    ungrouped.forEach((ds) => {
      html += renderDatasetRow(ds);
    });
    html += `</div>`;
  }

  html += `</div>
    <div class="flex items-center gap-3">
      <button type="button" id="hdf5-load-selected" class="px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed" disabled>
        Load selected
      </button>
      <span id="hdf5-selection-hint" class="text-xs text-gray-500 dark:text-gray-400"></span>
    </div>
    <p id="hdf5-selection-error" class="mt-2 text-sm text-red-600 dark:text-red-400 hidden"></p>`;
  container.innerHTML = html;

  const loadBtn = document.getElementById("hdf5-load-selected");
  const hint = document.getElementById("hdf5-selection-hint");
  const errorEl = document.getElementById("hdf5-selection-error");

  function getSelectedCheckboxes() {
    return Array.from(
      container.querySelectorAll(".hdf5-dataset-checkbox:checked"),
    );
  }

  function getSelectionAnchor() {
    const selected = getSelectedCheckboxes();
    if (selected.length === 0) {
      return { length: null, ndim: null };
    }
    const label = selected[0].closest(".hdf5-dataset-option");
    return {
      length: label?.dataset.length || null,
      ndim: label?.dataset.ndim || null,
    };
  }

  function dominantLengthForPaths(paths) {
    const counts = new Map();
    paths.forEach((path) => {
      const ds = datasetByPath.get(path);
      const len = datasetLength(ds);
      if (len != null) {
        counts.set(len, (counts.get(len) || 0) + 1);
      }
    });
    let bestLength = null;
    let bestCount = 0;
    counts.forEach((count, len) => {
      if (count > bestCount) {
        bestCount = count;
        bestLength = len;
      }
    });
    return bestLength == null ? null : String(bestLength);
  }

  function pathsCompatibleWithAnchor(paths, anchor) {
    return paths.filter((path) => {
      const ds = datasetByPath.get(path);
      if (!ds) return false;
      const len = datasetLength(ds);
      const ndim = ds.ndim != null ? String(ds.ndim) : "";
      if (anchor.length == null) return true;
      return String(len) === anchor.length && ndim === anchor.ndim;
    });
  }

  function syncGroupCheckboxes() {
    container.querySelectorAll(".hdf5-group-checkbox").forEach((groupCb) => {
      const paths = (groupCb.dataset.groupPaths || "")
        .split(",")
        .filter(Boolean);
      const memberCbs = paths
        .map((path) =>
          container.querySelector(
            `.hdf5-dataset-checkbox[value="${CSS.escape(path)}"]`,
          ),
        )
        .filter(Boolean);
      const enabledMembers = memberCbs.filter((cb) => !cb.disabled);
      const checkedMembers = enabledMembers.filter((cb) => cb.checked);
      groupCb.indeterminate =
        checkedMembers.length > 0 &&
        checkedMembers.length < enabledMembers.length;
      groupCb.checked =
        enabledMembers.length > 0 &&
        checkedMembers.length === enabledMembers.length;
      groupCb.disabled = enabledMembers.length === 0;
    });
  }

  function syncHdf5PickerState() {
    const selected = getSelectedCheckboxes();
    const lengths = new Set(
      selected
        .map((cb) => cb.closest(".hdf5-dataset-option")?.dataset.length)
        .filter(Boolean),
    );
    const ndims = new Set(
      selected
        .map((cb) => cb.closest(".hdf5-dataset-option")?.dataset.ndim)
        .filter(Boolean),
    );

    errorEl.classList.add("hidden");
    errorEl.textContent = "";

    container.querySelectorAll(".hdf5-dataset-option").forEach((label) => {
      const cb = label.querySelector(".hdf5-dataset-checkbox");
      if (!cb || cb.checked) {
        label.classList.remove("opacity-40");
        cb.disabled = false;
        return;
      }
      if (selected.length === 0) {
        label.classList.remove("opacity-40");
        cb.disabled = false;
        return;
      }
      const compatibleLength =
        lengths.size === 1 && label.dataset.length === [...lengths][0];
      const compatibleNdim =
        ndims.size === 1 && label.dataset.ndim === [...ndims][0];
      const compatible = compatibleLength && compatibleNdim;
      label.classList.toggle("opacity-40", !compatible);
      cb.disabled = !compatible;
    });

    syncGroupCheckboxes();

    loadBtn.disabled = selected.length === 0;
    if (selected.length === 0) {
      hint.textContent = "";
    } else if (lengths.size === 1) {
      hint.textContent = `${selected.length} selected · length ${[...lengths][0]}`;
    } else {
      hint.textContent = `${selected.length} selected · incompatible lengths`;
      loadBtn.disabled = true;
    }
  }

  container.querySelectorAll(".hdf5-dataset-checkbox").forEach((cb) => {
    cb.addEventListener("change", syncHdf5PickerState);
  });

  container.querySelectorAll(".hdf5-group-checkbox").forEach((groupCb) => {
    groupCb.addEventListener("change", () => {
      const paths = (groupCb.dataset.groupPaths || "")
        .split(",")
        .filter(Boolean);
      if (groupCb.checked) {
        const anchor = getSelectionAnchor();
        const targetLength =
          anchor.length ??
          dominantLengthForPaths(
            paths.filter((path) => {
              const cb = container.querySelector(
                `.hdf5-dataset-checkbox[value="${CSS.escape(path)}"]`,
              );
              return cb && !cb.disabled;
            }),
          );
        const targetNdim =
          anchor.ndim ??
          (() => {
            const first = datasetByPath.get(paths[0]);
            return first?.ndim != null ? String(first.ndim) : null;
          })();
        pathsCompatibleWithAnchor(paths, {
          length: targetLength,
          ndim: targetNdim,
        }).forEach((path) => {
          const cb = container.querySelector(
            `.hdf5-dataset-checkbox[value="${CSS.escape(path)}"]`,
          );
          if (cb && !cb.disabled) cb.checked = true;
        });
      } else {
        paths.forEach((path) => {
          const cb = container.querySelector(
            `.hdf5-dataset-checkbox[value="${CSS.escape(path)}"]`,
          );
          if (cb) cb.checked = false;
        });
      }
      syncHdf5PickerState();
    });
  });

  loadBtn.addEventListener("click", () => {
    const paths = Array.from(
      container.querySelectorAll(".hdf5-dataset-checkbox:checked"),
    ).map((cb) => cb.value);
    if (paths.length === 0) return;
    selectHdf5Datasets(paths);
  });

  syncHdf5PickerState();
}

function selectHdf5Datasets(paths) {
  const container = document.getElementById("workspace-summary");
  if (container) {
    container.innerHTML = `
      <div role="status" class="inline-block">
        <svg class="w-8 h-8 text-gray-200 animate-spin dark:text-gray-600 fill-blue-600" viewBox="0 0 100 101"><path d="M100 50.59c0 27.61-22.39 50-50 50S0 78.2 0 50.59 22.39.59 50 .59s50 22.39 50 50zm-90.92 0c0 22.6 18.32 40.92 40.92 40.92s40.92-18.32 40.92-40.92S72.6 9.67 50 9.67 9.08 28 9.08 50.59z" fill="currentColor"/><path d="M93.97 39.04c2.43-.64 3.93-3.13 3.04-5.5A50 50 0 0048.44.58c-2.5.23-4.21 2.53-3.73 5l.02.1a3.89 3.89 0 004.57 3.13A41.1 41.1 0 0188.18 37.2a3.88 3.88 0 005.79 1.84z" fill="currentFill"/></svg>
      </div>
      <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">Loading selected dataset(s)...</p>`;
  }

  fetch("/filter-file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keys: paths }),
  })
    .then((r) => r.json())
    .then((resp) => {
      if (resp.success) {
        initWorkspace();
      } else if (container) {
        const p = document.createElement("p");
        p.className = "text-sm text-red-600 dark:text-red-400";
        p.textContent = resp.error || "Failed to select dataset(s).";
        container.replaceChildren(p);
      }
    })
    .catch((err) => {
      if (container) {
        const p = document.createElement("p");
        p.className = "text-sm text-red-600 dark:text-red-400";
        p.textContent = "Error: " + err.message;
        container.replaceChildren(p);
      }
    });
}

function clearWorkspaceFeatureDropdowns() {
  if (typeof populateWorkspaceDropdowns === "function") {
    populateWorkspaceDropdowns({
      all_features: [],
      categorical_features: [],
      numerical_features: [],
      class_imbalance_features: [],
    });
  }
}

/**
 * Return to the HDF5 dataset picker without re-uploading the file.
 */
function returnToHdf5DatasetPicker() {
  const container = document.getElementById("workspace-summary");
  const hist = document.getElementById("workspace-histograms");
  if (hist) hist.innerHTML = "";
  if (container) {
    container.innerHTML = `
      <div role="status" class="inline-block">
        <svg class="w-8 h-8 text-gray-200 animate-spin dark:text-gray-600 fill-blue-600" viewBox="0 0 100 101"><path d="M100 50.59c0 27.61-22.39 50-50 50S0 78.2 0 50.59 22.39.59 50 .59s50 22.39 50 50zm-90.92 0c0 22.6 18.32 40.92 40.92 40.92s40.92-18.32 40.92-40.92S72.6 9.67 50 9.67 9.08 28 9.08 50.59z" fill="currentColor"/><path d="M93.97 39.04c2.43-.64 3.93-3.13 3.04-5.5A50 50 0 0048.44.58c-2.5.23-4.21 2.53-3.73 5l.02.1a3.89 3.89 0 004.57 3.13A41.1 41.1 0 0188.18 37.2a3.88 3.88 0 005.79 1.84z" fill="currentFill"/></svg>
      </div>
      <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">Returning to dataset selection...</p>`;
  }
  clearWorkspaceFeatureDropdowns();

  fetch("/clear-dataset-selection", { method: "POST" })
    .then((r) => r.json())
    .then((data) => {
      if (data.needs_dataset_selection && data.datasets?.length && container) {
        renderHdf5DatasetPicker(container, data);
        showPanel("data-overview", false);
      } else if (container) {
        const p = document.createElement("p");
        p.className = "text-sm text-red-600 dark:text-red-400";
        p.textContent =
          data.message ||
          data.error ||
          "Failed to return to dataset selection.";
        container.replaceChildren(p);
      }
    })
    .catch((err) => {
      if (container) {
        const p = document.createElement("p");
        p.className = "text-sm text-red-600 dark:text-red-400";
        p.textContent = "Error: " + err.message;
        container.replaceChildren(p);
      }
    });
}

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
        let html = "";
        if (data.hdf5_multi_dataset) {
          const keys = (data.selected_dataset_keys || []).join(", ");
          const keysDisplay =
            keys.length > 80 ? `${keys.slice(0, 77)}...` : keys;
          const escapedKeys = keys
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/"/g, "&quot;");
          const escapedDisplay = keysDisplay
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;");
          html += `
          <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4 pb-4 border-b border-gray-200 dark:border-gray-700">
            <p class="text-sm text-gray-600 dark:text-gray-400">
              HDF5 datasets:
              <span class="font-mono text-xs text-gray-800 dark:text-gray-200" title="${escapedKeys}">${escapedDisplay || "selected"}</span>
            </p>
            <button type="button" onclick="returnToHdf5DatasetPicker()" class="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18"/></svg>
              Change dataset selection
            </button>
          </div>`;
        }
        html += `
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
        if (
          data.summary_statistics &&
          Object.keys(data.summary_statistics).length > 0
        ) {
          const features = Object.keys(data.summary_statistics);
          const allStats = Object.keys(data.summary_statistics[features[0]]);
          html +=
            '<h3 class="text-sm font-semibold text-gray-900 dark:text-white mb-3 uppercase tracking-wide">Numerical Features</h3>';
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

        html += buildCategoricalSummaryTable(data.categorical_summary);

        container.innerHTML = html;

        // Render histograms in the data overview panel
        if (data.histograms) {
          renderWorkspaceHistograms(data.histograms);
        }
      } else if (data.needs_dataset_selection && data.datasets?.length) {
        renderHdf5DatasetPicker(container, data);
      } else {
        container.innerHTML = `
          <div class="flex items-start gap-2 p-3 text-sm rounded-lg bg-amber-50 text-amber-800 dark:bg-amber-900/20 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
            <svg class="w-4 h-4 mt-0.5 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"/></svg>
            <span>${escapeHtml(data.message)}</span>
          </div>`;
      }
    })
    .catch((err) => {
      const container = document.getElementById("workspace-summary");
      if (container) {
        const p = document.createElement("p");
        p.className = "text-sm";
        p.style.color = "red";
        p.textContent = "Error loading summary: " + err.message;
        container.replaceChildren(p);
      }
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

  initFileReferenceTargetPicker();
  loadFileReferenceOptions();

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

  // Data Quality (completeness-extras) column pickers
  fillCheckboxContainer(
    "rowLevelCompletenessColumnsCheckbox",
    allFeatures,
    "required columns for row level completeness",
  );
  fillCheckboxContainer(
    "duplicateFeaturesCheckbox",
    allFeatures,
    "features for duplicate detection",
  );
  fillDropdown("temporalCompletenessColumnDropdown", allFeatures);
  fillDropdown("nullCountTrendBatchDropdown", allFeatures);
  fillCheckboxContainer(
    "nullCountTrendTargetColumnsCheckbox",
    allFeatures,
    "target columns for null count trend",
  );

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
