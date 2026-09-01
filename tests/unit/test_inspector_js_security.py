import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSPECTOR_JS = REPO_ROOT / "web" / "static" / "js" / "inspector.js"
DATA_QUALITY_PANEL = REPO_ROOT / "web" / "templates" / "_panels" / "_data_quality.html"
DATA_STRUCTURE_PANEL = REPO_ROOT / "web" / "templates" / "_panels" / "_data_structure.html"
VARIABLE_UNIT_PANEL = REPO_ROOT / "web" / "templates" / "_panels" / "_variable_unit_validation.html"
SIDEBAR = REPO_ROOT / "web" / "templates" / "_components" / "sidebar.html"


def test_result_renderer_escapes_untrusted_display_values():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    required_fragments = [
        "${escapeHtml(type)}",
        "${escapeHtml(error)}",
        "${escapeHtml(description)}",
        "${escapeHtml(key)}",
        "${escapeHtml(k)}",
        "${escapeHtml(formatValue(v))}",
        "${escapeHtml(interpretation)}",
        "${escapeHtml(formatValue(value))}",
    ]
    for fragment in required_fragments:
        assert fragment in source


def test_escape_html_covers_attribute_breakout_chars():
    """Strong escaper must encode >, ', and \" so attribute breakouts fail."""
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    start = source.index("function escapeHtml(str)")
    end = source.index("\n\n// ==================== FAIR Assessment", start)
    escaper = source[start:end]
    assert ".replace(/>/g, \"&gt;\")" in escaper
    assert ".replace(/'/g, \"&#39;\")" in escaper
    assert ".replace(/\"/g, \"&quot;\")" in escaper


def test_readiness_and_overview_renderers_escape_dataset_strings():
    """Dataset-derived strings must not reach innerHTML unescaped."""
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    required = [
        'alt="Distribution of ${escapeHtml(colName)}"',
        "${escapeHtml(p.feature)}",
        'title="${escapeHtml(p.summary || "")}"',
        "${escapeHtml(meta.file_name || \"Dataset\")}",
        "function _escapeHtml(s) {\n  return escapeHtml(s);",
        "Representation ${escapeHtml(col)}",
        "Class imbalance: ${escapeHtml(det.class_imbalance.error)}",
    ]
    for fragment in required:
        assert fragment in source, f"missing escape: {fragment!r}"

    # Unescaped forms that previously enabled stored XSS
    forbidden = [
        'alt="Distribution of ${colName}"',
        "${p.feature}</td>",
        'title="${p.summary || ""}"',
        "${meta.file_name || \"Dataset\"}",
        "Dataset overview unavailable: ${overview.error}",
        "Class imbalance: ${det.class_imbalance.error}",
    ]
    for fragment in forbidden:
        assert fragment not in source, f"unescaped sink still present: {fragment!r}"


def test_categorical_pie_charts_escape_column_name_payload():
    """Column-name XSS payload must not appear raw in pie-chart HTML."""
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert 'alt="Distribution of ${escapeHtml(colName)}"' in source
    assert 'alt="Distribution of ${colName}"' not in source

    # Mirror escapeHtml() and the pie-chart template without requiring Node.
    def escape_html(text):
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    payload = '<img src=x onerror=alert(1)>'
    breakout = '" onerror=alert(1) x="'
    for col_name in (payload, breakout):
        html = (
            f'<img src="data:image/png;base64,AAAA" '
            f'alt="Distribution of {escape_html(col_name)}" />'
        )
        assert payload not in html
        assert 'alt="Distribution of "' not in html
        assert "&lt;" in html or "&quot;" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for XSS string repro")
def test_categorical_pie_charts_escape_column_name_payload_in_node():
    """Execute renderCategoricalPieCharts in Node when available."""
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    start = source.index("function renderCategoricalPieCharts")
    end = source.index("\nfunction renderHdf5DatasetPicker", start)
    esc_start = source.index("function escapeHtml(str)")
    esc_end = source.index("\n\n// ==================== FAIR Assessment", esc_start)
    script = f"""
{source[esc_start:esc_end]}
{source[start:end]}
let captured = "";
const document = {{
  getElementById: () => ({{
    set innerHTML(v) {{ captured = v; }},
    get innerHTML() {{ return captured; }},
  }}),
}};
const payload = '<img src=x onerror=alert(1)>';
const breakout = '" onerror=alert(1) x="';
renderCategoricalPieCharts({{ [payload]: "AAAA" }}, "c");
if (captured.includes(payload)) {{
  process.stdout.write(JSON.stringify({{ ok: false, reason: "raw payload in html" }}));
  process.exit(0);
}}
renderCategoricalPieCharts({{ [breakout]: "AAAA" }}, "c");
if (captured.includes('onerror=alert(1)') && !captured.includes('&quot;')) {{
  process.stdout.write(JSON.stringify({{ ok: false, reason: "attribute breakout" }}));
  process.exit(0);
}}
process.stdout.write(JSON.stringify({{ ok: true, sample: captured.slice(0, 200) }}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["ok"] is True, result


def test_custom_outlier_targets_load_only_when_enabled():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert 'const checkbox = document.getElementById("toggleButton_custom_outliers")' in source
    assert "checkbox?.checked" in source
    assert "toggleCustomOutlierEditor(checkbox)" in source


def test_file_reference_ui_keeps_custom_outlier_loading_independent():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    panel = DATA_STRUCTURE_PANEL.read_text(encoding="utf-8")
    quality_panel = DATA_QUALITY_PANEL.read_text(encoding="utf-8")
    assert "function loadFileReferenceOptions()" in source
    assert "loadFileReferenceOptions();" in source
    assert "window.AIDRIN_GLOBUS_MODE" in source
    assert 'id="toggleButton_file_reference_validation"' in panel
    assert 'id="toggleButton_file_reference_validation"' not in quality_panel
    assert 'inputName: "file_reference_targets"' in source
    assert 'name="file_reference_root_id"' in panel
    assert 'name="file_reference_base_subdirectory"' in panel
    assert 'name="file_reference_max_results"' in panel


def test_file_reference_targets_use_searchable_collapsed_multi_select():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    panel = DATA_STRUCTURE_PANEL.read_text(encoding="utf-8")
    assert 'id="file-reference-target-button"' in panel
    assert 'aria-haspopup="listbox"' in panel
    assert 'id="file-reference-target-menu"' in panel
    assert 'id="file-reference-target-search"' in panel
    assert 'role="listbox" aria-multiselectable="true"' in panel
    assert '<select id="file-reference-targets"' not in panel
    assert "function initFileReferenceTargetPicker()" in source
    assert "function filterTargetPicker(picker, query)" in source
    assert "function updateTargetPickerSummary(picker)" in source
    assert 'inputName: "file_reference_targets"' in source
    assert 'badge.textContent = "Suggested"' in source
    assert '"Enter a target pattern."' in source


def test_file_reference_and_custom_outliers_share_searchable_target_picker():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    panel = DATA_STRUCTURE_PANEL.read_text(encoding="utf-8")
    assert "function renderTargetPicker(picker, targets, options = {})" in source
    assert 'id="file-reference-target-picker" data-target-picker' in panel
    assert 'data-field="target" data-target-picker' in source
    assert "renderTargetPicker(picker, customOutlierTargets)" in source
    assert ".custom-outlier-target" not in source
    assert "function fullMatchTargetNames(patternText, targets, targetType)" in source
    assert "function updateRegexTargetPreview(" in source
    assert 'name="file_reference_target_match"' in panel
    assert 'name="file_reference_targets" disabled' in panel
    assert 'data-section="target-regex-preview"' in source


def test_target_pickers_share_one_document_click_handler():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert "function closeTargetPickersOnDocumentClick(event)" in source
    assert "function ensureTargetPickerDocumentHandler()" in source
    assert "ensureTargetPickerDocumentHandler();" in source
    assert source.count('document.addEventListener("click"') == 1


def test_python_regex_preview_is_advisory_for_submission():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert '"No targets match this pattern."' in source
    assert "The target pattern does not match any path-bearing targets." not in source
    assert "does not match any available targets." not in source
    assert "element.dataset.valid" not in source


def test_target_pickers_use_compact_side_by_side_shaded_controls():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    panel = DATA_STRUCTURE_PANEL.read_text(encoding="utf-8")
    assert 'class="flex items-start gap-2"' in panel
    assert panel.count('class="w-32 shrink-0') == 1
    assert '<option value="regex">Regex</option>' in panel
    assert "bg-gray-50 px-2 py-2 text-sm" in source
    assert 'class="w-32 shrink-0' in source
    assert '<option value="regex">Regex</option>' in source
    assert "function setTargetPickerOptionSelected(option, selected)" in source
    assert 'option.classList.toggle("bg-blue-50", selected)' in source


def test_file_reference_tables_escape_values_and_warn_on_partial_scans():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert "function renderFileReferenceInvalidTable(rows)" in source
    assert "function renderFileReferenceMetadataTable(rows)" in source
    assert "escapeHtml(formatValue(value))" in source
    assert "Partial scan:" in source
    assert "!results.Summary.scan_complete" in source


def test_variable_unit_editor_and_results_escape_dataset_metadata():
    source = INSPECTOR_JS.read_text(encoding="utf-8")

    editor_start = source.index("function renderVariableUnitEditor()")
    editor_end = source.index("function toggleVariableUnitEditor", editor_start)
    editor = source[editor_start:editor_end]
    assert "cell.textContent = text" in editor
    assert "option.textContent = label" in editor

    result_start = source.index("function renderVariableUnitResultTable(rows)")
    result_end = source.index("function filterVariableUnitResults", result_start)
    result_renderer = source[result_start:result_end]
    assert "escapeHtml(formatValue(value))" in result_renderer
    assert "escapeHtml(classification)" in result_renderer


def test_variable_unit_editor_exposes_search_pagination_and_json_round_trip():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    panel = VARIABLE_UNIT_PANEL.read_text(encoding="utf-8")
    data_structure_panel = DATA_STRUCTURE_PANEL.read_text(encoding="utf-8")
    sidebar = SIDEBAR.read_text(encoding="utf-8")

    for element_id in (
        "variable-unit-search",
        "variable-unit-import-file",
        "variable-unit-prev",
        "variable-unit-next",
        "variable-unit-declarations",
    ):
        assert f'id="{element_id}"' in panel
        assert f'id="{element_id}"' not in data_structure_panel
    understandability_start = sidebar.index('id="pillar-understand"')
    data_structure_start = sidebar.index("<!-- Pillar: Data Structure & Organization -->")
    assert (
        understandability_start
        < sidebar.index("showPanel('variable-unit-validation')")
        < data_structure_start
    )
    assert "const VARIABLE_UNIT_PAGE_SIZE = 10" in source
    assert "function exportVariableUnitDeclarations()" in source
    assert "function importVariableUnitDeclarations(file)" in source
    assert "function filterVariableUnitResults(select)" in source


def test_variable_unit_globus_control_is_capability_gated_and_serialized():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    inspector = (REPO_ROOT / "web" / "templates" / "inspector.html").read_text(
        encoding="utf-8"
    )

    assert 'capabilities.includes("variable_unit_validation_v1")' in source
    assert "Upgrade and restart its AIDRIN worker" in source
    assert "remoteParams.unit_declarations = variableUnitDeclarations" in source
    assert "setVariableUnitTargets(result.unit_targets || [])" in source
    assert "window.AIDRIN_GLOBUS_CAPABILITIES = {{ globus_capabilities | tojson }}" in inspector


def test_custom_outlier_rules_are_serialized_for_local_and_globus_submission():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert "function serializeCustomOutlierRules()" in source
    assert 'processedFormData.set(\n      "custom_outlier_rules"' in source
    assert "remoteParams.custom_outlier_rules = customOutlierRules" in source
    assert "remoteParams.max_export_rows" in source
    assert "remoteParams.scan_limit" in source
    assert "remoteParams.stop_after_outliers" in source
    assert "criteria: serializeCustomOutlierCriteria(row)" in source
    assert "function serializeCustomOutlierCondition(condition)" in source
    assert 'return { op: "not", condition: { op: "or", conditions } }' in source
    assert "criteria_type:" not in source
    assert "function validateCustomOutlierRuleSelection(rules)" in source
    assert "async function workspaceSubmit(targetUrl)" in source
    assert "await resolveCustomOutlierRules()" in source
    assert "if (!customOutlierRules) return;" in source
    assert "function validateCustomOutlierCriteria(criteria, ruleName)" in source
    assert 'targetMatch === "regex"' in source
    assert 'rule.target_match = "regex"' in source
    assert 'data-section="target-exact"' in source
    assert 'data-section="target-regex"' in source
    assert 'aria-label="Target pattern (regular expression)"' in source
    assert 'md:grid-cols-[minmax(9rem,0.6fr)_minmax(16rem,1.4fr)_auto]' in source
    assert 'class="absolute right-2 top-2' in source
    assert 'aria-label="Remove rule"' in source
    assert "function customOutlierRegexTargetType(row)" in source
    assert "targetTypes.length <= 1" in source
    assert "range condition requires min or max" in source
    assert "requires a condition for NOT" in source
    assert "customOutlierLimitValue(formData.get(\"max_outliers\"), 100)" in source
    assert "customOutlierLimitValue(\n          gFormData.get(\"max_outliers\")," in source


def test_custom_outlier_json_file_source_is_browser_only_and_async():
    panel = DATA_QUALITY_PANEL.read_text(encoding="utf-8")
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert 'name="custom_outlier_rule_source" value="manual" checked' in panel
    assert 'name="custom_outlier_rule_source" value="file"' in panel
    assert 'id="custom-outlier-rules-file" accept="application/json,.json"' in panel
    assert "not uploaded or saved" in panel
    assert "function parseCustomOutlierRulesJson(text)" in source
    assert "async function resolveCustomOutlierRules()" in source
    assert "await file.text()" in source
    assert "submitGlobusMetric" in source


def test_switching_custom_outlier_rule_sources_clears_stale_results():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert "function clearCustomOutlierResults()" in source
    assert "clearCustomOutlierResults();\n        updateCustomOutlierRuleSource();" in source
    assert 'document.getElementById("results-section")' in source
    assert "lastMetricResult = null;" in source


def test_custom_outlier_manual_rules_can_be_saved_as_json():
    panel = DATA_QUALITY_PANEL.read_text(encoding="utf-8")
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert 'id="custom-outlier-save-rules"' in panel
    assert "function downloadCustomOutlierRules()" in source
    assert "JSON.stringify(rules, null, 2)" in source
    assert 'link.download = "custom-outlier-rules.json"' in source


def _parse_rules_file_in_browser(text):
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    start = source.index("function parseCustomOutlierRulesJson(text)")
    end = source.index("\n\nasync function resolveCustomOutlierRules()", start)
    parser_and_validator = source[start:end]
    criteria_start = source.index("function validateCustomOutlierCriteria(criteria, ruleName)")
    criteria_end = source.index("\n\nfunction showCustomOutlierValidationError", criteria_start)
    criteria_validator = source[criteria_start:criteria_end]
    script = f"""{parser_and_validator}
{criteria_validator}
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {{ input += chunk; }});
process.stdin.on("end", () => {{
  try {{
    const rules = parseCustomOutlierRulesJson(input);
    const error = validateCustomOutlierRulesFile(rules);
    process.stdout.write(JSON.stringify(error ? {{ ok: false, error }} : {{ ok: true }}));
  }} catch (error) {{
    process.stdout.write(JSON.stringify({{ ok: false, error: error.message }}));
  }}
}});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        input=text,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for the frontend formatter")
def test_custom_outlier_json_file_parser_corpus():
    cases = [
        ('[{"id":"valid-age","target":"age","target_type":"column","criteria":{"type":"range","min":18}}]', True, None),
        ("{", False, "valid JSON"),
        ("{}", False, "JSON array"),
        ("[]", False, "at least one rule"),
        ('[{"id":"unknown-op","target":"age","target_type":"column","criteria":{"op":"xor","conditions":[]}}]', False, "unsupported operator"),
        ('[{"id":"unknown-type","target":"age","target_type":"column","criteria":{"type":"contains"}}]', False, "unsupported condition type"),
        ('[{"id":"missing-target","target_type":"column","criteria":{"type":"regex","pattern":".*"}}]', False, "requires a target"),
        ('[{"id":"bad-bound","target":"age","target_type":"column","criteria":{"type":"range","min":"NaN"}}]', False, "finite number"),
        ('[{"id":"regex-target","target":"^age$","target_match":"regex","target_type":"column","criteria":{"type":"range","min":18}}]', True, None),
        (
            '[{"id":"bad-target-match","target":"age","target_match":"glob","target_type":"column","criteria":{"type":"range","min":18}}]',
            False,
            "unsupported target match mode",
        ),
        (
            (
                '[{"id":"!!!","target":"age","target_type":"column","criteria":{"type":"range","min":18}},'
                '{"id":"rule","target":"age","target_type":"column","criteria":{"type":"range","min":18}}]'
            ),
            False,
            "resolve to the same output key",
        ),
    ]
    for text, expected_ok, expected_error in cases:
        result = _parse_rules_file_in_browser(text)
        assert result["ok"] is expected_ok
        if expected_error:
            assert expected_error in result["error"]


def test_custom_outlier_preview_cap_placeholder_documents_default():
    source = DATA_QUALITY_PANEL.read_text(encoding="utf-8")
    assert 'name="max_outliers" placeholder="default: 100"' in source


def test_custom_outlier_export_downloads_csv_without_inline_row_rendering():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert 'key === "Outlier export"' in source
    assert "downloadCustomOutlierExportCsv()" in source
    assert 'link.download = "custom-outlier-export.csv"' in source


def test_async_metric_completion_initializes_download_result_store():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert "function storeAsyncMetricResult(metricName, result)" in source
    assert 'lastMetricResult = {}' in source
    assert "lastMetricResult[metricName] = result" in source
    assert "storeAsyncMetricResult(metricName, response.result)" in source


def test_custom_outlier_preview_uses_compact_overview_table():
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert 'key === "Outlier preview"' in source
    assert "renderCustomOutlierPreviewTable(value)" in source
    assert "flattenOutlierPreviewRows(previewByRule)" in source
    assert "Preview rows failed a valid-value condition." in source
    assert "Why flagged" in source
    assert "formatOutlierFlagFallback(reason)" in source
    assert 'below_min: "< min"' in source
    assert 'above_max: "> max"' in source


def test_custom_outlier_ui_explains_valid_value_semantics():
    panel = DATA_QUALITY_PANEL.read_text(encoding="utf-8")
    script = INSPECTOR_JS.read_text(encoding="utf-8")
    expected = "Values that do not satisfy these conditions are flagged."
    assert "Rules define expected valid values." in panel
    assert expected in panel
    assert expected in script


def test_workspace_init_releases_clear_file_lock_after_overview_load():
    """loadDataOverview must return its fetch promise so initWorkspace can
    drop the processing lock. Calling .finally on undefined throws, which left
    the top-bar clear button with pointer-events-none forever."""
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert "return fetch(\"/summary-statistics\")" in source
    assert "Promise.resolve(loadDataOverview()).finally(initTaskDone)" in source


def test_readiness_report_loaded_flag_resets_when_leaving_panel_mid_flight():
    """_readinessReportLoaded must not stick true if the user navigates away
    before cache restore finishes, or the panel stays empty until a reload."""
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    assert "if (activePanel !== \"readiness-report\") {\n        _readinessReportLoaded = false;" in source
    assert "if (!restored && activePanel === \"readiness-report\")" not in source


def test_init_workspace_resets_readiness_state_for_dataset_switch():
    """HDF5 dataset switches call initWorkspace without a reload; stale readiness
    globals would keep showing the previous dataset's report and charts."""
    source = INSPECTOR_JS.read_text(encoding="utf-8")
    start = source.index("function initWorkspace()")
    nxt = source.find("\nfunction ", start + 1)
    body = source[start:nxt if nxt != -1 else None]
    assert "_readinessReportLoaded = false;" in body
    assert "Object.keys(_readinessVizCache)" in body
    assert "delete _readinessVizCache[key]" in body
    assert "Object.keys(_readinessSectionStatus)" in body
    assert "delete _readinessSectionStatus[key]" in body
    assert '_readinessFairCompliance = { status: "idle", data: null }' in body
