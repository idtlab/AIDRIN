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
    assert result["Outlier preview"]["max-five"][0]["flag"] == "> 5 by 1"


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
    assert [item["flag"] for item in preview] == ["NaN", "> 10 by 2"]


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
        "< 10 by 5",
        "> 20 by 5",
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
    assert preview[0]["flag"] == "no match"


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
    assert preview[0]["flag"] == "NOT"


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


def test_hdf5_default_zero_policy_counts_missing_and_warns(hdf5_file_info, caplog):
    with caplog.at_level(logging.WARNING):
        result = calculate_custom_outliers(hdf5_file_info, [
            _range_rule("default-zero-range", "/default_zero", target_type="hdf5_dataset", min_value=-1, max_value=2)
        ])
    assert result["Rule summaries"]["default-zero-range"]["missing"] == 2
    assert any("default fill value" in record.message for record in caplog.records)


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
