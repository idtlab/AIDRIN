from pathlib import Path


INSPECTOR_JS = Path(__file__).resolve().parents[2] / "web" / "static" / "js" / "inspector.js"


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


def test_result_renderer_requires_relative_remedy_download_url():
    source = INSPECTOR_JS.read_text()
    assert 'value.startsWith("/download-remedy/")' in source
    assert 'value.includes("/download-remedy/")' not in source


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
    assert "function validateCustomOutlierRuleSelection(rules)" in source
    assert "!validateCustomOutlierRuleSelection(customOutlierRules)" in source


def test_custom_outlier_export_downloads_csv_without_inline_row_rendering():
    source = INSPECTOR_JS.read_text()
    assert 'key === "Outlier export"' in source
    assert "downloadCustomOutlierExportCsv()" in source
    assert 'link.download = "custom-outlier-export.csv"' in source


def test_custom_outlier_preview_uses_compact_overview_table():
    source = INSPECTOR_JS.read_text()
    assert 'key === "Outlier preview"' in source
    assert "renderCustomOutlierPreviewTable(value)" in source
    assert "flattenOutlierPreviewRows(previewByRule)" in source
    assert "formatOutlierFlagFallback(reason)" in source
    assert 'below_min: "< min"' in source
    assert 'above_max: "> max"' in source
