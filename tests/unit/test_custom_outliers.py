import json
import logging
import os
import sys
import tempfile
import types

import h5py
import numpy as np
import pandas as pd
import pytest

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

import aidrin
import aidrin.file_handling.value_iterators as value_iterators
from aidrin.file_handling.value_iterators import iter_targets, iter_value_blocks
from aidrin.structured_data_metrics.custom_outliers import calculate_custom_outliers


def _write_csv(df):
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return (tmp.name, os.path.basename(tmp.name), ".csv")


def _write_dataframe(df, suffix, file_type):
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    if file_type == ".parquet":
        df.to_parquet(tmp.name)
    else:
        df.to_excel(tmp.name, index=False)
    return (tmp.name, os.path.basename(tmp.name), file_type)


def _write_json_rows(rows):
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump(rows, tmp)
    tmp.close()
    return (tmp.name, os.path.basename(tmp.name), ".json")


def _write_npz(values):
    tmp = tempfile.NamedTemporaryFile(suffix=".npz", delete=False)
    tmp.close()
    np.savez(tmp.name, values=np.array(values, dtype=object))
    return (tmp.name, os.path.basename(tmp.name), ".npz")


def _write_column_fixture(file_type):
    data = {"alpha": [0, 1], "beta": [0, 3]}
    if file_type == ".csv":
        return _write_csv(pd.DataFrame(data))
    if file_type == ".xls, .xlsb, .xlsx, .xlsm":
        return _write_dataframe(pd.DataFrame(data), ".xlsx", file_type)
    if file_type == ".parquet":
        return _write_dataframe(pd.DataFrame(data), ".parquet", file_type)
    if file_type == ".json":
        return _write_json_rows([dict(zip(data, values)) for values in zip(*data.values())])
    tmp = tempfile.NamedTemporaryFile(suffix=".npz", delete=False)
    tmp.close()
    np.savez(tmp.name, **{name: np.array(values) for name, values in data.items()})
    return (tmp.name, os.path.basename(tmp.name), ".npz")


def _clean(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _range_rule(rule_id, target, target_type="column", min_value=None, max_value=None, **kwargs):
    criteria = {"type": "range"}
    if min_value is not None:
        criteria["min"] = min_value
    if max_value is not None:
        criteria["max"] = max_value
    return {
        "id": rule_id,
        "target": target,
        "target_type": target_type,
        "criteria": criteria,
        **kwargs,
    }


def _regex_rule(rule_id, target, pattern, target_type="column", **kwargs):
    return {
        "id": rule_id,
        "target": target,
        "target_type": target_type,
        "criteria": {"type": "regex", "pattern": pattern},
        **kwargs,
    }


def _compare_rule(operator="<=", **kwargs):
    return {
        "id": "ordered-bounds",
        "target": "lower",
        "target_type": "column",
        "criteria": {"type": "compare", "operator": operator, "other_target": "upper"},
        **kwargs,
    }


@pytest.mark.parametrize("file_type", [".csv", ".parquet", ".json", ".npz", ".xls, .xlsb, .xlsx, .xlsm"])
def test_comparison_across_tabular_formats(file_type):
    fi = _write_column_fixture(file_type)
    rule = _compare_rule(target="beta", criteria={"type": "compare", "operator": "<=", "other_target": "alpha"})
    with open(fi[0], "rb") as source:
        original = source.read()
    try:
        result = aidrin.calculate_custom_outliers(fi, [rule])
        with open(fi[0], "rb") as source:
            assert source.read() == original
    finally:
        _clean(fi[0])
    summary = result["Rule summaries"]["ordered-bounds"]
    assert summary["total"] == 2
    assert summary["valid"] == summary["outlier"] == 1
    assert summary["reference_targets"] == ["alpha"]
    row = result["Outlier preview"]["ordered-bounds"][0]
    assert row["value"] == 3
    assert row["reference_values"] == {"alpha": 1}
    assert row["reason"] == "comparison_mismatch"
    assert row["location"]["row_index"] == 1
    assert row["flag"] == "beta is 3, exceeds alpha 1"
    assert result["Outlier export"]["ordered-bounds"] == [row]
    if file_type == ".csv":
        assert row["location"]["source_line"] == 3


@pytest.mark.parametrize(("operator", "valid"), [("<", 1), ("<=", 2), (">", 1), (">=", 2), ("==", 1), ("!=", 2)])
def test_comparison_operators_and_numeric_strings(operator, valid):
    fi = _write_json_rows([{"lower": value, "upper": "2"} for value in ["1", "2", "3"]])
    try:
        result = calculate_custom_outliers(fi, [_compare_rule(operator)])
    finally:
        _clean(fi[0])
    assert result["Rule summaries"]["ordered-bounds"]["valid"] == valid


def test_comparison_keeps_large_integer_precision():
    fi = _write_json_rows([{"lower": 9007199254740993, "upper": 9007199254740992}])
    try:
        result = calculate_custom_outliers(fi, [_compare_rule("==")])
    finally:
        _clean(fi[0])
    assert result["Rule summaries"]["ordered-bounds"]["outlier"] == 1


@pytest.mark.parametrize("allow_missing", [False, True])
def test_comparison_missing_either_operand(allow_missing):
    fi = _write_json_rows([
        {"lower": None, "upper": 2}, {"lower": 1, "upper": None},
        {"lower": None, "upper": None}, {"lower": 1, "upper": 2},
    ])
    try:
        result = calculate_custom_outliers(fi, [_compare_rule(allow_missing=allow_missing)])
    finally:
        _clean(fi[0])
    summary = result["Rule summaries"]["ordered-bounds"]
    assert summary["missing"] == 3
    assert summary["valid"] == (4 if allow_missing else 1)
    assert summary["outlier"] == (0 if allow_missing else 3)
    assert all(row["reason"] == "missing" for row in result["Outlier preview"]["ordered-bounds"])


@pytest.mark.parametrize("op", ["and", "or", "not"])
def test_comparison_nested_boolean_criteria_do_not_hide_invalid_operands(op):
    comparison = _compare_rule()["criteria"]
    criteria = {"op": op, "conditions": [comparison, {"type": "range", "min": 0}]}
    if op == "not":
        criteria = {"op": op, "condition": comparison}
    fi = _write_json_rows([
        {"lower": 1, "upper": 2}, {"lower": 3, "upper": 2},
        {"lower": "bad", "upper": 2}, {"lower": 1, "upper": "bad"},
        {"lower": float("inf"), "upper": 2}, {"lower": 1, "upper": float("-inf")},
    ])
    try:
        result = calculate_custom_outliers(fi, [_compare_rule(criteria=criteria)])
    finally:
        _clean(fi[0])
    summary = result["Rule summaries"]["ordered-bounds"]
    assert summary["valid"] == (2 if op == "or" else 1)
    rows = result["Outlier preview"]["ordered-bounds"]
    assert sum(row["reason"] == "invalid_comparison" for row in rows) == 4


def test_comparison_missing_reference_is_rule_scoped():
    fi = _write_csv(pd.DataFrame({"lower": [1, 3]}))
    try:
        result = calculate_custom_outliers(fi, [_compare_rule(), _range_rule("legacy", "lower", min_value=0)])
    finally:
        _clean(fi[0])
    assert result["Rule summaries"]["ordered-bounds"]["total"] == 0
    assert "Comparison column not found: upper" in result["Errors"][0]["error"]
    assert result["Rule summaries"]["legacy"]["valid"] == 2


@pytest.mark.parametrize("criteria", [
    {"type": "compare", "operator": "=", "other_target": "upper"},
    {"type": "compare", "operator": [], "other_target": "upper"},
    {"type": "compare", "operator": "<=", "other_target": ""},
    {"type": "compare", "operator": "<=", "other_target": 1},
])
def test_comparison_rejects_invalid_rules(criteria):
    with pytest.raises(ValueError, match="compare requires"):
        calculate_custom_outliers(None, [_compare_rule(criteria=criteria)])


def test_comparison_rejects_native_hdf5_even_when_nested():
    rule = _compare_rule(target_type="hdf5_dataset", criteria={"op": "not", "condition": _compare_rule()["criteria"]})
    with pytest.raises(ValueError, match="tabular columns only"):
        calculate_custom_outliers(None, [rule])


def test_comparison_regex_targets_caps_and_multiple_references():
    fi = _write_json_rows([{"lower_a": 3, "lower_b": 4, "upper": 2, "ceiling": 5}] * 5)
    rule = _compare_rule(target="lower_.*", target_match="regex", criteria={"op": "and", "conditions": [
        _compare_rule()["criteria"], {"type": "compare", "operator": "<", "other_target": "ceiling"},
    ]})
    try:
        result = calculate_custom_outliers(fi, [rule], max_outliers=1, max_export_rows=2, scan_limit=3)
        stopped = calculate_custom_outliers(fi, [rule], max_outliers=1, stop_after_outliers=True)
    finally:
        _clean(fi[0])
    assert len(result["Rule summaries"]) == 2
    for key, summary in result["Rule summaries"].items():
        assert summary["total"] == summary["outlier"] == 3
        assert summary["reference_targets"] == ["ceiling", "upper"]
        assert summary["scan_stopped_early"] and summary["truncated"] and summary["export_truncated"]
        assert len(result["Outlier preview"][key]) == 1
        assert len(result["Outlier export"][key]) == 2
        assert result["Outlier export"][key][0]["reference_values"] == {"ceiling": 5, "upper": 2}
        assert stopped["Rule summaries"][key]["total"] == 1


def test_comparison_aligns_by_position_and_rejects_ambiguous_columns(monkeypatch):
    df = pd.DataFrame({1: [1, 3], 2: [2, 2]}, index=[9, 9])
    monkeypatch.setattr(value_iterators, "read_file", lambda _fi: df.copy())
    rule = _compare_rule(target="1", criteria={"type": "compare", "operator": "<=", "other_target": "2"})
    result = calculate_custom_outliers(("dummy", "dummy", ".csv"), [rule])
    assert result["Outlier preview"]["ordered-bounds"][0]["location"]["row_index"] == 1
    df.columns = ["1", "1"]
    # Skip discovery to exercise ambiguity in the actual column block reader.
    monkeypatch.setattr("aidrin.structured_data_metrics.custom_outliers.iter_targets", lambda _fi: [
        {"name": "1", "target_type": "column"},
    ])
    rule["criteria"]["other_target"] = "1"
    result = calculate_custom_outliers(("dummy", "dummy", ".csv"), [rule])
    assert "ambiguous" in result["Errors"][0]["error"]


@pytest.fixture
def hdf5_file_info(tmp_path):
    path = tmp_path / "custom_outliers.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("root_scalar", data=np.array(7.0))
        group = h5.create_group("S_01_01")
        x = group.create_dataset("X", data=np.array([0.0, 1.5, -9999.0, 25.0]), fillvalue=-9999.0)
        x.attrs["_FillValue"] = -9999.0
        group.create_dataset("Y", data=np.array([1.0, 2.0, 3.0]))
        group.create_dataset("Z", data=np.array([4.0, 5.0, 6.0]))
        group.create_dataset("STLA,STLO,STDP", data=np.array([10.0, 20.0, 30.0]))
        h5.create_dataset("group/data", data=np.array([[1.0, 2.0], [3.0, 99.0]]))
        h5.create_dataset("default_zero", data=np.array([0.0, 1.0, 0.0]))
    return (str(path), path.name, ".h5")


def test_iter_targets_lists_csv_columns():
    fi = _write_csv(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))
    try:
        targets = iter_targets(fi)
    finally:
        _clean(fi[0])
    assert {target["name"] for target in targets} == {"a", "b"}
    assert all(target["target_type"] == "column" for target in targets)


def test_iter_value_blocks_csv_locations_include_source_line():
    fi = _write_csv(pd.DataFrame({"a": [10, 20]}))
    try:
        target = {"name": "a", "target_type": "column"}
        block = next(iter_value_blocks(fi, target))
    finally:
        _clean(fi[0])
    assert block["locate"]((0,)) == {"row_index": 0, "display": "row 0", "source_line": 2}


@pytest.mark.parametrize(
    ("suffix", "file_type"),
    [(".xlsx", ".xls, .xlsb, .xlsx, .xlsm"), (".parquet", ".parquet")],
)
def test_custom_outliers_normalize_non_string_tabular_columns(suffix, file_type, monkeypatch):
    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "0")
    fi = _write_dataframe(pd.DataFrame({1: [0, 1, 3]}), suffix, file_type)
    try:
        targets = iter_targets(fi)
        assert [target["name"] for target in targets] == ["1"]
        result = calculate_custom_outliers(fi, [_range_rule("numeric-header", "1", min_value=0, max_value=2)])
    finally:
        _clean(fi[0])

    summary = result["Rule summaries"]["numeric-header"]
    assert "errors" not in summary
    assert summary["outlier"] == 1


@pytest.mark.parametrize(
    ("writer", "values"),
    [(_write_json_rows, [{"values": [1, 2]}, {"values": [3]}]), (_write_npz, [[1, 2], [3]])],
)
def test_custom_outliers_handle_container_values_without_rule_errors(writer, values):
    fi = writer(values)
    try:
        regex_result = calculate_custom_outliers(fi, [_regex_rule("containers-regex", "values", r".*")])
        range_result = calculate_custom_outliers(fi, [_range_rule("containers-range", "values", min_value=0, max_value=5)])
    finally:
        _clean(fi[0])

    regex_summary = regex_result["Rule summaries"]["containers-regex"]
    range_summary = range_result["Rule summaries"]["containers-range"]
    assert "errors" not in regex_summary
    assert regex_summary["valid"] == 2
    assert "errors" not in range_summary
    assert range_summary["outlier"] == 2
    assert [row["reason"] for row in range_result["Outlier preview"]["containers-range"]] == ["non_numeric", "non_numeric"]


def test_iter_targets_lists_native_hdf5_paths(hdf5_file_info):
    targets = iter_targets(hdf5_file_info)
    names = {target["name"] for target in targets}
    assert "/S_01_01/X" in names
    assert "/S_01_01/STLA,STLO,STDP" in names
    assert "/group/data" in names
    assert "/root_scalar" in names


def test_iter_value_blocks_hdf5_uses_native_locations(hdf5_file_info):
    block = next(iter_value_blocks(hdf5_file_info, {"name": "/group/data", "target_type": "hdf5_dataset"}))
    assert block["locate"]((1, 1)) == {
        "path": "/group/data",
        "index": [1, 1],
        "display": "/group/data[1,1]",
    }


def test_iter_targets_accepts_hdf5_selected_keys_file_info(hdf5_file_info):
    extended_file_info = (*hdf5_file_info, ["/S_01_01/X"])
    targets = iter_targets(extended_file_info)
    assert any(target["name"] == "/S_01_01/X" for target in targets)


def test_iter_value_blocks_hdf5_streams_regular_slices(tmp_path, monkeypatch):
    monkeypatch.setattr(value_iterators, "HDF5_BLOCK_ELEMENT_LIMIT", 4)
    path = tmp_path / "streamed.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("matrix", data=np.arange(10).reshape(5, 2), fillvalue=-1)

    file_info = (str(path), path.name, ".h5")
    blocks = list(iter_value_blocks(file_info, {"name": "/matrix", "target_type": "hdf5_dataset"}))

    assert [block["offset"] for block in blocks] == [[0, 0], [2, 0], [4, 0]]
    assert [block["values"].shape for block in blocks] == [(2, 2), (2, 2), (1, 2)]
    assert blocks[-1]["locate"]((0, 1)) == {
        "path": "/matrix",
        "index": [4, 1],
        "display": "/matrix[4,1]",
    }

    result = calculate_custom_outliers(file_info, [
        _range_rule("max-five", "/matrix", target_type="hdf5_dataset", max_value=5)
    ])
    summary = result["Rule summaries"]["max-five"]
    assert summary["total"] == 10
    assert summary["outlier"] == 4
    assert result["Outlier preview"]["max-five"][0]["location"]["display"] == "/matrix[3,0]"
    assert result["Outlier preview"]["max-five"][0]["flag"] == "/matrix is 6, exceeds maximum 5"


def test_csv_regex_and_range_rules_report_expected_counts():
    df = pd.DataFrame({
        "Rupture Realization #": ["1", "2patch", "3", "4patch"],
        "Hypocenter Position (km) 2": [-20, -10, 0, 25],
    })
    fi = _write_csv(df)
    rules = [
        _regex_rule("rupture-realization-integer", "Rupture Realization #", "^[0-9]+$"),
        _range_rule("hypocenter-range", "Hypocenter Position (km) 2", min_value=-10, max_value=20),
    ]
    try:
        result = calculate_custom_outliers(fi, rules)
    finally:
        _clean(fi[0])

    regex_summary = result["Rule summaries"]["rupture-realization-integer"]
    range_summary = result["Rule summaries"]["hypocenter-range"]
    assert regex_summary["valid"] == 2
    assert regex_summary["outlier"] == 2
    assert range_summary["valid"] == 2
    assert range_summary["outlier"] == 2
    assert result["Outlier preview"]["hypocenter-range"][0]["location"]["source_line"] == 2


def test_range_allows_one_sided_bounds_and_reports_non_numeric():
    fi = _write_csv(pd.DataFrame({"value": ["5", "bad", "12"]}))
    rules = [_range_rule("max-only", "value", max_value=10)]
    try:
        result = calculate_custom_outliers(fi, rules)
    finally:
        _clean(fi[0])

    preview = result["Outlier preview"]["max-only"]
    assert [item["reason"] for item in preview] == ["non_numeric", "above_max"]
    assert [item["flag"] for item in preview] == ["value is bad, must be a number", "value is 12, exceeds maximum 10"]


def test_compound_and_uses_all_conditions_as_valid_expression():
    fi = _write_csv(pd.DataFrame({"value": [5, 12, 25]}))
    rules = [{
        "id": "range-and-even-text",
        "target": "value",
        "target_type": "column",
        "criteria": {
            "op": "and",
            "conditions": [
                {"type": "range", "min": 10, "max": 20},
                {"type": "regex", "pattern": r"^\d+$"},
            ],
        },
    }]
    try:
        result = calculate_custom_outliers(fi, rules)
    finally:
        _clean(fi[0])

    summary = result["Rule summaries"]["range-and-even-text"]
    assert summary["valid"] == 1
    assert summary["outlier"] == 2
    assert [row["flag"] for row in result["Outlier preview"]["range-and-even-text"]] == [
        "value is 5, below minimum 10",
        "value is 25, exceeds maximum 20",
    ]


def test_compound_or_accepts_any_condition():
    fi = _write_csv(pd.DataFrame({"value": [1, 5, 99]}))
    rules = [{
        "id": "edge-values",
        "target": "value",
        "target_type": "column",
        "criteria": {
            "op": "or",
            "conditions": [
                {"type": "range", "max": 1},
                {"type": "range", "min": 90},
            ],
        },
    }]
    try:
        result = calculate_custom_outliers(fi, rules)
    finally:
        _clean(fi[0])

    preview = result["Outlier preview"]["edge-values"]
    assert result["Rule summaries"]["edge-values"]["outlier"] == 1
    assert preview[0]["value"] == 5
    assert preview[0]["reason"] == "or_mismatch"
    assert preview[0]["flag"] == "value is 5, matches none of the alternatives"


def test_compound_not_inverts_condition():
    fi = _write_csv(pd.DataFrame({"value": [1, 5, 9]}))
    rules = [{
        "id": "not-mid",
        "target": "value",
        "target_type": "column",
        "criteria": {
            "op": "not",
            "condition": {"type": "range", "min": 3, "max": 7},
        },
    }]
    try:
        result = calculate_custom_outliers(fi, rules)
    finally:
        _clean(fi[0])

    preview = result["Outlier preview"]["not-mid"]
    assert result["Rule summaries"]["not-mid"]["outlier"] == 1
    assert preview[0]["value"] == 5
    assert preview[0]["reason"] == "not_mismatch"
    assert preview[0]["flag"] == "value is 5, matches an excluded condition"


def test_flat_rule_syntax_is_rejected():
    fi = _write_csv(pd.DataFrame({"value": [1]}))
    try:
        with pytest.raises(ValueError, match="criteria tree syntax"):
            calculate_custom_outliers(fi, [{
                "id": "flat",
                "target": "value",
                "target_type": "column",
                "criteria_type": "range",
                "min": 0,
            }])
    finally:
        _clean(fi[0])


@pytest.mark.parametrize("bound", ["nan", "inf", "-inf", float("nan"), float("inf")])
def test_non_finite_range_bounds_are_rejected(bound):
    fi = _write_csv(pd.DataFrame({"value": [1]}))
    try:
        with pytest.raises(ValueError, match="non-finite min"):
            calculate_custom_outliers(fi, [
                _range_rule("non-finite", "value", min_value=bound)
            ])
    finally:
        _clean(fi[0])


def test_missing_values_are_counted_separately_and_can_be_allowed():
    fi = _write_csv(pd.DataFrame({"value": [1, None, 3]}))
    try:
        result = calculate_custom_outliers(fi, [
            _range_rule("missing-invalid", "value", min_value=0)
        ])
        allowed = calculate_custom_outliers(fi, [
            _range_rule("missing-allowed", "value", min_value=0, allow_missing=True)
        ])
    finally:
        _clean(fi[0])

    assert result["Rule summaries"]["missing-invalid"]["missing"] == 1
    assert result["Rule summaries"]["missing-invalid"]["outlier"] == 1
    assert allowed["Rule summaries"]["missing-allowed"]["missing"] == 1
    assert allowed["Rule summaries"]["missing-allowed"]["outlier"] == 0


def test_regex_stringification_is_predictable_for_numbers():
    fi = _write_csv(pd.DataFrame({"value": [1, 2.5, 3]}))
    try:
        result = calculate_custom_outliers(fi, [
            _regex_rule("integer-text", "value", "^[0-9]+$")
        ])
    finally:
        _clean(fi[0])
    assert result["Rule summaries"]["integer-text"]["outlier"] == 3
    assert result["Outlier preview"]["integer-text"][0]["value"] == 1.0


def test_duplicate_rule_ids_raise_validation_error():
    fi = _write_csv(pd.DataFrame({"a": [1]}))
    rules = [
        _range_rule("dup", "a", min_value=0),
        _range_rule("dup", "a", max_value=1),
    ]
    try:
        with pytest.raises(ValueError, match="Duplicate"):
            calculate_custom_outliers(fi, rules)
    finally:
        _clean(fi[0])


def test_sanitized_rule_key_collisions_raise_validation_error():
    fi = _write_csv(pd.DataFrame({"a": [1]}))
    rules = [
        _range_rule("a b", "a", min_value=0),
        _range_rule("a_b", "a", max_value=1),
    ]
    try:
        with pytest.raises(ValueError, match="same output key"):
            calculate_custom_outliers(fi, rules)
    finally:
        _clean(fi[0])


def test_duplicate_targets_with_different_ids_are_supported():
    fi = _write_csv(pd.DataFrame({"a": [1, 10]}))
    rules = [
        _range_rule("low", "a", min_value=0),
        _range_rule("high", "a", max_value=5),
    ]
    try:
        result = calculate_custom_outliers(fi, rules)
    finally:
        _clean(fi[0])
    assert result["Rule summaries"]["low"]["outlier"] == 0
    assert result["Rule summaries"]["high"]["outlier"] == 1


def test_invalid_regex_raises_validation_error():
    fi = _write_csv(pd.DataFrame({"a": ["x"]}))
    try:
        with pytest.raises(ValueError, match="invalid pattern"):
            calculate_custom_outliers(fi, [
                _regex_rule("bad-regex", "a", "[")
            ])
    finally:
        _clean(fi[0])


@pytest.mark.parametrize(
    ("criteria", "message"),
    [
        ({"op": "xor", "conditions": []}, "unsupported operator"),
        ({"type": "contains"}, "unsupported condition type"),
    ],
)
def test_unsupported_criteria_are_rejected(criteria, message):
    fi = _write_csv(pd.DataFrame({"value": [1]}))
    try:
        with pytest.raises(ValueError, match=message):
            calculate_custom_outliers(fi, [{
                "id": "unsupported",
                "target": "value",
                "target_type": "column",
                "criteria": criteria,
            }])
    finally:
        _clean(fi[0])


def test_missing_target_is_reported_as_rule_error():
    fi = _write_csv(pd.DataFrame({"a": [1]}))
    try:
        result = calculate_custom_outliers(fi, [
            _range_rule("missing-target", "b", min_value=0)
        ])
    finally:
        _clean(fi[0])
    assert result["Errors"][0]["rule_id"] == "missing-target"
    assert "Target not found" in result["Errors"][0]["error"]


def test_preview_is_capped_per_rule():
    fi = _write_csv(pd.DataFrame({"a": [100, 101, 102]}))
    try:
        result = calculate_custom_outliers(fi, [
            _range_rule("cap", "a", max_value=1)
        ], max_outliers=2)
    finally:
        _clean(fi[0])
    assert result["Rule summaries"]["cap"]["outlier"] == 3
    assert result["Rule summaries"]["cap"]["truncated"] is True
    assert len(result["Outlier preview"]["cap"]) == 2


def test_empty_preview_cap_uses_default():
    fi = _write_csv(pd.DataFrame({"a": list(range(105))}))
    try:
        result = calculate_custom_outliers(fi, [
            _range_rule("empty-cap-default", "a", max_value=1)
        ], max_outliers="")
    finally:
        _clean(fi[0])

    summary = result["Rule summaries"]["empty-cap-default"]
    assert summary["outlier"] == 103
    assert summary["preview_limit"] == 100
    assert summary["truncated"] is True
    assert len(result["Outlier preview"]["empty-cap-default"]) == 100


def test_zero_preview_cap_is_unlimited():
    fi = _write_csv(pd.DataFrame({"a": [100, 101, 102]}))
    try:
        result = calculate_custom_outliers(fi, [
            _range_rule("unlimited-preview", "a", max_value=1)
        ], max_outliers=0)
    finally:
        _clean(fi[0])

    summary = result["Rule summaries"]["unlimited-preview"]
    assert summary["outlier"] == 3
    assert summary["preview_limit"] == 0
    assert summary["truncated"] is False
    assert len(result["Outlier preview"]["unlimited-preview"]) == 3


def test_custom_outlier_export_uses_separate_cap():
    fi = _write_csv(pd.DataFrame({"a": [100, 101, 102, 103]}))
    try:
        result = calculate_custom_outliers(fi, [
            _range_rule("export-cap", "a", max_value=1)
        ], max_outliers=1, max_export_rows=3)
    finally:
        _clean(fi[0])

    summary = result["Rule summaries"]["export-cap"]
    assert summary["outlier"] == 4
    assert summary["truncated"] is True
    assert summary["export_truncated"] is True
    assert len(result["Outlier preview"]["export-cap"]) == 1
    assert len(result["Outlier export"]["export-cap"]) == 3
    assert result["Outlier export"]["export-cap"][0]["rule_id"] == "export-cap"


def test_zero_export_cap_is_unlimited():
    fi = _write_csv(pd.DataFrame({"a": [100, 101, 102, 103]}))
    try:
        result = calculate_custom_outliers(fi, [
            _range_rule("unlimited-export", "a", max_value=1)
        ], max_outliers=1, max_export_rows=0)
    finally:
        _clean(fi[0])

    summary = result["Rule summaries"]["unlimited-export"]
    assert summary["outlier"] == 4
    assert summary["export_limit"] == 0
    assert summary["export_truncated"] is False
    assert len(result["Outlier export"]["unlimited-export"]) == 4


def test_scan_limit_stops_before_full_count():
    fi = _write_csv(pd.DataFrame({"a": [100, 101, 102, 103]}))
    try:
        result = calculate_custom_outliers(fi, [
            _range_rule("limited", "a", max_value=1)
        ], scan_limit=2)
    finally:
        _clean(fi[0])

    summary = result["Rule summaries"]["limited"]
    assert summary["total"] == 2
    assert summary["outlier"] == 2
    assert summary["scan_limit"] == 2
    assert summary["scan_stopped_early"] is True


def test_stop_after_outliers_uses_preview_cap():
    fi = _write_csv(pd.DataFrame({"a": [100, 101, 102, 103]}))
    try:
        result = calculate_custom_outliers(fi, [
            _range_rule("early", "a", max_value=1)
        ], max_outliers=2, stop_after_outliers=True)
    finally:
        _clean(fi[0])

    summary = result["Rule summaries"]["early"]
    assert summary["total"] == 2
    assert summary["outlier"] == 2
    assert summary["stop_after_outliers"] is True
    assert summary["scan_stopped_early"] is True


def test_hdf5_range_rule_counts_fill_values_as_missing(hdf5_file_info):
    result = calculate_custom_outliers(hdf5_file_info, [
        _range_rule("waveform-x-range", "/S_01_01/X", target_type="hdf5_dataset", min_value=-1, max_value=2)
    ])
    summary = result["Rule summaries"]["waveform-x-range"]
    assert summary["missing"] == 1
    assert summary["outlier"] == 2
    reasons = [item["reason"] for item in result["Outlier preview"]["waveform-x-range"]]
    assert reasons == ["missing", "above_max"]


def test_regex_target_match_expands_to_each_hdf5_dataset(hdf5_file_info):
    result = calculate_custom_outliers(hdf5_file_info, [
        _range_rule(
            "waveform-range",
            r"^/S_01_01/[XY]$",
            target_type="hdf5_dataset",
            min_value=0,
            max_value=2,
            target_match="regex",
        )
    ])

    summaries = result["Rule summaries"]
    assert len(summaries) == 2
    by_target = {summary["target"]: summary for summary in summaries.values()}
    assert set(by_target) == {"/S_01_01/X", "/S_01_01/Y"}
    assert by_target["/S_01_01/X"]["missing"] == 1
    assert by_target["/S_01_01/X"]["outlier"] == 2
    assert by_target["/S_01_01/Y"]["outlier"] == 1
    assert all(summary["target_match"] == "regex" for summary in summaries.values())
    assert all(summary["target_pattern"] == r"^/S_01_01/[XY]$" for summary in summaries.values())


def test_regex_target_match_reports_zero_matches(hdf5_file_info):
    result = calculate_custom_outliers(hdf5_file_info, [
        _range_rule(
            "missing-waveform",
            r"^/S_99_99/X$",
            target_type="hdf5_dataset",
            min_value=0,
            target_match="regex",
        )
    ])

    error = result["Errors"][0]["error"]
    assert error == "No targets matched regex: ^/S_99_99/X$. Check the pattern and target type against the Target list."


@pytest.mark.parametrize("file_type", [".csv", ".xls, .xlsb, .xlsx, .xlsm", ".parquet", ".json", ".npz"])
def test_regex_target_match_expands_across_tabular_file_types(file_type, monkeypatch):
    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "0")
    fi = _write_column_fixture(file_type)
    try:
        result = calculate_custom_outliers(fi, [
            _range_rule("tabular-range", r"^(alpha|beta)$", min_value=0, max_value=1, target_match="regex")
        ])
    finally:
        _clean(fi[0])

    summaries = result["Rule summaries"]
    by_target = {summary["target"]: summary for summary in summaries.values()}
    assert set(by_target) == {"alpha", "beta"}
    assert by_target["alpha"]["outlier"] == 0
    assert by_target["beta"]["outlier"] == 1


@pytest.mark.parametrize(
    ("target_match", "target", "message"),
    [("glob", "value", "unsupported target_match"), ("regex", "[", "invalid target regex")],
)
def test_invalid_target_match_is_rejected(target_match, target, message):
    fi = _write_csv(pd.DataFrame({"value": [1]}))
    try:
        with pytest.raises(ValueError, match=message):
            calculate_custom_outliers(fi, [
                _range_rule(
                    "invalid-target-match",
                    target,
                    min_value=0,
                    target_match=target_match,
                )
            ])
    finally:
        _clean(fi[0])


def test_hdf5_multidimensional_locations(hdf5_file_info):
    result = calculate_custom_outliers(hdf5_file_info, [
        _range_rule("multi-range", "/group/data", target_type="hdf5_dataset", max_value=10)
    ])
    preview = result["Outlier preview"]["multi-range"]
    assert preview[0]["location"]["display"] == "/group/data[1,1]"


def test_hdf5_multidimensional_aggregates(hdf5_file_info):
    result = calculate_custom_outliers(hdf5_file_info, [
        _range_rule("multi-range", "/group/data", target_type="hdf5_dataset", max_value=10)
    ])

    aggregates = result["HDF5 aggregates"]["multi-range"]
    assert aggregates["by_leading_index"][0]["key"] == "1"
    assert aggregates["by_leading_index"][0]["outlier"] == 1
    assert aggregates["by_leading_index"][0]["first_outlier"]["display"] == "/group/data[1,1]"


def test_hdf5_aggregate_counts_missing_outlier_once(tmp_path):
    path = tmp_path / "missing_aggregate.h5"
    with h5py.File(path, "w") as h5:
        data = np.array([[1.0, -9999.0], [2.0, 3.0]])
        dataset = h5.create_dataset("matrix", data=data, fillvalue=-9999.0)
        dataset.attrs["_FillValue"] = -9999.0

    result = calculate_custom_outliers((str(path), path.name, ".h5"), [
        _range_rule("missing-aggregate", "/matrix", target_type="hdf5_dataset", min_value=0)
    ])

    row = result["HDF5 aggregates"]["missing-aggregate"]["by_leading_index"][0]
    assert row["key"] == "0"
    assert row["total"] == 2
    assert row["missing"] == 1
    assert row["outlier"] == 1


def test_hdf5_default_zero_values_are_not_missing(hdf5_file_info):
    result = calculate_custom_outliers(hdf5_file_info, [
        _range_rule("default-zero-range", "/default_zero", target_type="hdf5_dataset", min_value=1, max_value=2)
    ])
    summary = result["Rule summaries"]["default-zero-range"]
    assert summary["missing"] == 0
    assert summary["outlier"] == 2
    assert [item["reason"] for item in result["Outlier preview"]["default-zero-range"]] == ["below_min", "below_min"]


def test_hdf5_fill_log_counts_only_sentinel_matches(tmp_path, caplog):
    path = tmp_path / "fill_count.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("values", data=np.array([np.nan, -9999.0]), fillvalue=-9999.0)

    with caplog.at_level(logging.INFO):
        block = next(iter_value_blocks((str(path), path.name, ".h5"), {
            "name": "/values",
            "target_type": "hdf5_dataset",
        }))

    assert block["missing_mask"].tolist() == [True, True]
    messages = [record.message for record in caplog.records]
    assert any("marked 1/2 value(s)" in message for message in messages)


def test_public_api_exports_calculate_custom_outliers():
    assert callable(aidrin.calculate_custom_outliers)


@pytest.mark.parametrize(("operator", "lower", "expected"), [
    ("<", 2, "lower is 2, must be less than upper 2"),
    ("<", 3, "lower is 3, must be less than upper 2"),
    ("<=", 3, "lower is 3, exceeds upper 2"),
    (">", 2, "lower is 2, must be greater than upper 2"),
    (">", 1, "lower is 1, must be greater than upper 2"),
    (">=", 1, "lower is 1, below upper 2"),
    ("==", 1, "lower is 1, must equal upper 2"),
    ("==", 3, "lower is 3, must equal upper 2"),
    ("!=", 2, "lower is 2, must differ from upper 2"),
    ("<=", 9007199254740993, "lower is 9007199254740993, exceeds upper 2"),
])
def test_comparison_explanations_name_actual_operands(operator, lower, expected):
    fi = _write_json_rows([{"lower": str(lower), "upper": "2"}])
    try:
        result = calculate_custom_outliers(fi, [_compare_rule(operator)])
    finally:
        _clean(fi[0])
    preview = result["Outlier preview"]["ordered-bounds"]
    assert preview[0]["reason"] == "comparison_mismatch"
    assert preview[0]["flag"] == expected
    assert result["Outlier export"]["ordered-bounds"] == preview


@pytest.mark.parametrize(("criteria", "value", "expected"), [
    ({"type": "range", "max": 2}, 3, "lower is 3, exceeds maximum 2"),
    ({"type": "range", "min": 2}, 1, "lower is 1, below minimum 2"),
    ({"type": "range", "min": 2, "min_inclusive": False}, 2, "lower is 2, must exceed minimum 2"),
    ({"type": "range", "max": 2, "max_inclusive": False}, 2, "lower is 2, must be below maximum 2"),
    ({"type": "regex", "pattern": "^[0-9]+$"}, "bad", "lower is 'bad', does not match /^[0-9]+$/"),
])
def test_range_and_regex_explanations_keep_boundary_semantics(criteria, value, expected):
    fi = _write_json_rows([{"lower": value}])
    try:
        result = calculate_custom_outliers(fi, [{"id": "rule", "target": "lower", "target_type": "column", "criteria": criteria}])
    finally:
        _clean(fi[0])
    assert result["Outlier preview"]["rule"][0]["flag"] == expected


@pytest.mark.parametrize(("lower", "upper", "expected"), [
    (None, 2, "lower is missing; this rule requires values"),
    (1, None, "upper is missing; this rule requires values"),
    (None, None, "lower, upper are missing; this rule requires values"),
    ("bad", 2, "lower is bad, must be a finite number"),
    (1, "bad", "upper is bad, must be a finite number"),
])
def test_unusable_comparison_explanations_do_not_blame_a_numeric_relationship(lower, upper, expected):
    fi = _write_json_rows([{"lower": lower, "upper": upper}])
    try:
        result = calculate_custom_outliers(fi, [_compare_rule()])
    finally:
        _clean(fi[0])
    assert result["Outlier preview"]["ordered-bounds"][0]["flag"] == expected


def test_negated_comparison_explanation_does_not_claim_comparison_failed():
    fi = _write_json_rows([{"lower": 1, "upper": 2}])
    rule = _compare_rule(criteria={"op": "not", "condition": _compare_rule()["criteria"]})
    try:
        result = calculate_custom_outliers(fi, [rule])
    finally:
        _clean(fi[0])
    row = result["Outlier preview"]["ordered-bounds"][0]
    assert row["reason"] == "not_mismatch"
    assert row["flag"] == "lower is 1, matches an excluded condition"


def test_or_comparison_explanation_represents_all_failed_alternatives():
    fi = _write_json_rows([{"lower": 3, "upper": 2}])
    rule = _compare_rule(criteria={"op": "or", "conditions": [
        _compare_rule()["criteria"], {"type": "regex", "pattern": "^9$"},
    ]})
    try:
        result = calculate_custom_outliers(fi, [rule])
    finally:
        _clean(fi[0])
    row = result["Outlier preview"]["ordered-bounds"][0]
    assert row["reason"] == "or_mismatch"
    assert row["flag"] == "lower is 3, matches none of the alternatives"
