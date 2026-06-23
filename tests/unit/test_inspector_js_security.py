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
    assert "remoteParams.custom_outlier_rules = serializeCustomOutlierRules()" in source
