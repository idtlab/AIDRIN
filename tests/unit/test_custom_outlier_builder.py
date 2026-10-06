"""Exercise the actual browser serializers against the existing JSON engine."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from aidrin.structured_data_metrics.custom_outliers import calculate_custom_outliers


pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for browser logic tests")
SOURCE = Path(__file__).resolve().parents[2] / "web/static/js/inspector.js"


def browser_rules(action, rules, targets=None):
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index("// ==================== Custom Criteria Outliers")
    end = source.index("// ==================== Layout Helpers", start)
    script = source[start:end] + r'''
let customOutlierTargets;
let rows = [];
let validationError = null;
let downloaded = null;
const hidden = {value: '', classList: {add: () => {}, remove: () => {}}};
function selectedTargetPickerInputs(picker) { return picker?.selected || []; }
function conditionNode(criteria) {
  const fields = {
    condition_type: {value: criteria.type},
    condition_min: {value: criteria.min == null ? '' : String(criteria.min)},
    condition_max: {value: criteria.max == null ? '' : String(criteria.max)},
    condition_min_inclusive: {checked: criteria.min_inclusive !== false},
    condition_max_inclusive: {checked: criteria.max_inclusive !== false},
    condition_pattern: {value: criteria.pattern ?? ''},
    condition_operator: {value: criteria.operator ?? '<='},
    condition_other_target: {value: criteria.other_target ?? ''},
  };
  return {fields, querySelector: selector => fields[selector.match(/data-field="([^"]+)"/)[1]]};
}
function ruleNode(plan) {
  const rule = plan.rule;
  const fields = {
    target: {selected: [{value: rule.target, dataset: {targetType: rule.target_type}}]},
    target_match: {value: rule.target_match || 'exact'},
    target_regex: {value: rule.target},
    target_type: {value: rule.target_type},
    name: {value: rule.name || rule.id},
    allow_missing: {checked: Boolean(rule.allow_missing)},
    criteria_op: {value: plan.op},
  };
  const conditions = plan.conditions.map(conditionNode);
  return {
    dataset: {ruleId: rule.id},
    querySelector: selector => fields[selector.match(/data-field="([^"]+)"/)[1]],
    querySelectorAll: () => conditions,
  };
}
let payload;
const document = {
  querySelectorAll: () => rows,
  querySelector: selector => selector.includes('custom_outlier_rule_source')
    ? {value: payload.action === 'save_file' ? 'file' : 'manual'} : rows[0],
  getElementById: id => id === 'custom-outlier-rules-file'
    ? {files: [{text: async () => JSON.stringify(payload.rules)}]} : hidden,
  createElement: () => ({click: () => {}}),
  body: {appendChild: () => {}, removeChild: () => {}},
};
const URL = {createObjectURL: () => 'blob:test', revokeObjectURL: () => {}};
const Blob = class { constructor(parts) { downloaded = parts.join(''); } };
showCustomOutlierValidationError = error => { validationError = error; return false; };
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', async () => {
  payload = JSON.parse(input);
  customOutlierTargets = payload.targets || ['lower', 'upper'].map(name => ({name, target_type: 'column'}));
  try {
    if (payload.action === 'save_file' || payload.action === 'save_manual') {
      if (payload.action === 'save_manual') rows = customOutlierBuilderPlan(payload.rules).map(ruleNode);
      await downloadCustomOutlierRules();
      process.stdout.write(JSON.stringify({rules: downloaded && JSON.parse(downloaded)}));
    } else if (payload.action === 'validate') {
      const valid = validateCustomOutlierRuleSelection(payload.rules);
      process.stdout.write(JSON.stringify({valid, error: validationError}));
    } else {
      const plan = customOutlierBuilderPlan(payload.rules);
      rows = plan.map(ruleNode);
      const rules = serializeCustomOutlierRules();
      const valid = validateCustomOutlierRuleSelection(rules);
      process.stdout.write(JSON.stringify({rules, valid, error: validationError, saved: hidden.value}));
    }
  } catch (error) {
    process.stdout.write(JSON.stringify({error: error.message}));
  }
});
'''
    # A script file avoids Windows' command-line length limit for the real editor source.
    with tempfile.TemporaryDirectory() as directory:
        script_file = Path(directory) / "builder.cjs"
        script_file.write_text(script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_file)],
            input=json.dumps({"action": action, "rules": rules, "targets": targets}),
            text=True, capture_output=True, check=True,
        )
    return json.loads(completed.stdout)


def rule(criteria, **fields):
    return {"id": "bounds", "target": "lower", "target_type": "column", "criteria": criteria, **fields}


COMPARE = {"type": "compare", "operator": "<=", "other_target": "upper"}
RANGE = {"type": "range", "min": 0, "max": 2, "min_inclusive": False, "max_inclusive": True}
REGEX = {"type": "regex", "pattern": "[12]"}


@pytest.mark.parametrize("criteria", [
    COMPARE, RANGE, REGEX,
    {"op": "and", "conditions": [RANGE, REGEX, COMPARE]},
    {"op": "or", "conditions": [RANGE, COMPARE]},
    {"op": "not", "condition": COMPARE},
    {"op": "not", "condition": {"op": "or", "conditions": [RANGE, REGEX, COMPARE]}},
])
@pytest.mark.parametrize("allow_missing", [False, True])
def test_builder_save_reimport_preserves_evaluation_and_row_evidence(tmp_path, criteria, allow_missing):
    path = tmp_path / "bounds.csv"
    path.write_text("lower,upper\n1,2\n3,2\n2,2\n,4\nbad,5\n", encoding="utf-8")
    original = [rule(criteria, name="Ordered bounds", allow_missing=allow_missing)]
    exported = browser_rules("roundtrip", original)
    assert exported["valid"], exported
    assert json.loads(exported["saved"]) == exported["rules"]
    assert browser_rules("save_manual", original)["rules"] == exported["rules"]
    reimported = browser_rules("roundtrip", json.loads(exported["saved"]))
    assert reimported["valid"], reimported
    file_info = (str(path), "bounds.csv", ".csv")
    expected = calculate_custom_outliers(file_info, original)
    assert calculate_custom_outliers(file_info, reimported["rules"]) == expected
    if criteria == COMPARE and not allow_missing:
        assert expected["Rule summaries"]["bounds"]["outlier"] == 3
        row = expected["Outlier export"]["bounds"][0]
        assert row["location"]["source_line"] == 3
        assert row["reference_values"] == {"upper": 2}


@pytest.mark.parametrize("operator", ["<", "<=", ">", ">=", "==", "!="])
def test_builder_serializes_all_supported_comparison_operators(operator):
    result = browser_rules("roundtrip", [rule({**COMPARE, "operator": operator})])
    assert result["valid"]
    assert result["rules"][0]["criteria"]["conditions"] == [{**COMPARE, "operator": operator}]


def test_builder_preserves_regex_target_matching():
    result = browser_rules("roundtrip", [rule(COMPARE, target="lower.*", target_match="regex")])
    assert result["valid"]
    assert result["rules"][0]["target_match"] == "regex"
    assert result["rules"][0]["target"] == "lower.*"


@pytest.mark.parametrize("original", [
    [rule({"op": "and", "conditions": [{"op": "or", "conditions": [RANGE, REGEX]}, COMPARE]})],
    [rule({"op": "not", "condition": {"op": "and", "conditions": [RANGE, COMPARE]}})],
    [rule(COMPARE, description="Keep this additional field")],
    [rule({**RANGE, "annotation": "Keep this condition field"})],
    [rule(COMPARE, allow_missing="false")],
    [rule(COMPARE, target=" lower.* ", target_match="regex")],
    [rule({**RANGE, "min": True})],
    [rule({**RANGE, "min": [1]})],
])
def test_advanced_valid_files_remain_unchanged_in_file_save_mode(original):
    result = browser_rules("roundtrip", original)
    assert "simple builder cannot edit" in result["error"]
    assert browser_rules("save_file", original)["rules"] == original


@pytest.mark.parametrize(("rules", "error"), [
    ([], "Add at least one"),
    ([rule(COMPARE, target="")], "select a target"),
    ([rule({**COMPARE, "other_target": ""})], "select a comparison column"),
    ([rule({**COMPARE, "other_target": "gone"})], "not available"),
    ([rule(COMPARE, target="gone")], "not available"),
    ([rule({"type": "range"})], "min or max"),
    ([rule({**COMPARE, "operator": "="})], "requires operator"),
    ([rule({"op": "and", "conditions": []})], "at least one condition"),
])
def test_builder_rejects_empty_and_invalid_states_with_actionable_errors(rules, error):
    result = browser_rules("validate", rules)
    assert not result["valid"]
    assert error in result["error"]


def test_hdf5_comparisons_cannot_be_submitted_from_builder():
    result = browser_rules("validate", [rule(COMPARE, target="/lower", target_type="hdf5_dataset")],
                           [{"name": "/lower", "target_type": "hdf5_dataset"}])
    assert not result["valid"]
    assert "tabular columns" in result["error"]


def test_normalized_groups_still_validate_comparison_columns():
    result = browser_rules("validate", [rule({"op": " AND ", "conditions": [{**COMPARE, "other_target": "gone"}]})])
    assert not result["valid"]
    assert "not available" in result["error"]


def test_builder_rejects_ids_with_colliding_output_keys():
    result = browser_rules("validate", [rule(COMPARE, id="custom rule 1"), rule(COMPARE, id="custom-rule-2"),
                                        rule(COMPARE, id="custom_rule_1")])
    assert not result["valid"]
    assert "same output key" in result["error"]


@pytest.mark.parametrize(("focus_inside", "disabled", "expected_focus"), [
    (True, False, True),
    (False, False, False),
    (True, True, False),
])
def test_target_picker_close_restores_keyboard_focus_without_stealing_outside_focus(focus_inside, disabled, expected_focus):
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index("function setTargetPickerOpen(")
    end = source.index("function setTargetPickerEnabled(", start)
    script = source[start:end] + r'''
const input = JSON.parse(process.argv[2]);
let focused = false;
let hidden = false;
let expanded;
const document = {activeElement: {}};
const button = {disabled: input.disabled, focus: () => {focused = true;}, setAttribute: (name, value) => {expanded = value;}};
const menu = {contains: () => input.focus_inside, classList: {toggle: (name, value) => {hidden = value;}}};
function targetPickerElements() {return {button, menu, search: {focus: () => {}}};}
setTargetPickerOpen({}, false);
process.stdout.write(JSON.stringify({focused, hidden, expanded}));
'''
    completed = subprocess.run(
        ["node", "-e", script, "unused", json.dumps({"focus_inside": focus_inside, "disabled": disabled})],
        text=True, capture_output=True, check=True,
    )
    assert json.loads(completed.stdout) == {"focused": expected_focus, "hidden": True, "expanded": "false"}
