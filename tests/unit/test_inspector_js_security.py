import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSPECTOR_JS = REPO_ROOT / "web" / "static" / "js" / "inspector.js"
DATA_QUALITY_PANEL = REPO_ROOT / "web" / "templates" / "_panels" / "_data_quality.html"


def test_result_renderer_escapes_untrusted_display_values():
    source = INSPECTOR_JS.read_text()
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


def test_custom_outlier_targets_load_only_when_enabled():
    source = INSPECTOR_JS.read_text()
    assert 'const checkbox = document.getElementById("toggleButton_custom_outliers")' in source
    assert "checkbox?.checked" in source
    assert "toggleCustomOutlierEditor(checkbox)" in source


def test_custom_outlier_rules_are_serialized_for_local_and_globus_submission():
    source = INSPECTOR_JS.read_text()
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
    assert 'md:grid-cols-[minmax(9rem,0.6fr)_minmax(16rem,1.4fr)_auto_auto]' in source
    assert "function customOutlierRegexTargetType(row)" in source
    assert "targetTypes.length <= 1" in source
    assert "range condition requires min or max" in source
    assert "requires a condition for NOT" in source
    assert "customOutlierLimitValue(formData.get(\"max_outliers\"), 100)" in source
    assert "customOutlierLimitValue(\n          gFormData.get(\"max_outliers\")," in source


def test_custom_outlier_json_file_source_is_browser_only_and_async():
    panel = DATA_QUALITY_PANEL.read_text()
    source = INSPECTOR_JS.read_text()
    assert 'name="custom_outlier_rule_source" value="manual" checked' in panel
    assert 'name="custom_outlier_rule_source" value="file"' in panel
    assert 'id="custom-outlier-rules-file" accept="application/json,.json"' in panel
    assert "not uploaded or saved" in panel
    assert "function parseCustomOutlierRulesJson(text)" in source
    assert "async function resolveCustomOutlierRules()" in source
    assert "await file.text()" in source
    assert "submitGlobusMetric" in source


def test_switching_custom_outlier_rule_sources_clears_stale_results():
    source = INSPECTOR_JS.read_text()
    assert "function clearCustomOutlierResults()" in source
    assert "clearCustomOutlierResults();\n        updateCustomOutlierRuleSource();" in source
    assert 'document.getElementById("results-section")' in source
    assert "lastMetricResult = null;" in source


def test_custom_outlier_manual_rules_can_be_saved_as_json():
    panel = DATA_QUALITY_PANEL.read_text()
    source = INSPECTOR_JS.read_text()
    assert 'id="custom-outlier-save-rules"' in panel
    assert "function downloadCustomOutlierRules()" in source
    assert "JSON.stringify(rules, null, 2)" in source
    assert 'link.download = "custom-outlier-rules.json"' in source


def _parse_rules_file_in_browser(text):
    source = INSPECTOR_JS.read_text()
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
    ]
    for text, expected_ok, expected_error in cases:
        result = _parse_rules_file_in_browser(text)
        assert result["ok"] is expected_ok
        if expected_error:
            assert expected_error in result["error"]


def test_custom_outlier_preview_cap_placeholder_documents_default():
    source = DATA_QUALITY_PANEL.read_text()
    assert 'name="max_outliers" placeholder="default: 100"' in source


def test_custom_outlier_export_downloads_csv_without_inline_row_rendering():
    source = INSPECTOR_JS.read_text()
    assert 'key === "Outlier export"' in source
    assert "downloadCustomOutlierExportCsv()" in source
    assert 'link.download = "custom-outlier-export.csv"' in source


def test_async_metric_completion_initializes_download_result_store():
    source = INSPECTOR_JS.read_text()
    assert "function storeAsyncMetricResult(metricName, result)" in source
    assert 'lastMetricResult = {}' in source
    assert "lastMetricResult[metricName] = result" in source
    assert "storeAsyncMetricResult(metricName, response.result)" in source


def test_custom_outlier_preview_uses_compact_overview_table():
    source = INSPECTOR_JS.read_text()
    assert 'key === "Outlier preview"' in source
    assert "renderCustomOutlierPreviewTable(value)" in source
    assert "flattenOutlierPreviewRows(previewByRule)" in source
    assert "Preview rows failed a valid-value condition." in source
    assert "Why flagged" in source
    assert "formatOutlierFlagFallback(reason)" in source
    assert 'below_min: "< min"' in source
    assert 'above_max: "> max"' in source


def test_custom_outlier_ui_explains_valid_value_semantics():
    panel = DATA_QUALITY_PANEL.read_text()
    script = INSPECTOR_JS.read_text()
    expected = "Values that do not satisfy these conditions are flagged."
    assert "Rules define expected valid values." in panel
    assert expected in panel
    assert expected in script
