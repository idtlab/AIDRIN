"""Tests for variable-unit discovery, parsing, precedence, and aggregation."""

import json
from copy import deepcopy
from pathlib import Path

import h5py
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aidrin.structured_data_metrics.variable_unit_validation import (
    _name_unit,
    _parse_unit,
    calculate_variable_unit_validation,
    discover_variable_units,
)


def _csv(tmp_path, columns):
    path = tmp_path / "data.csv"
    pd.DataFrame({column: [1, 2] for column in columns}).to_csv(path, index=False)
    return (str(path), path.name, ".csv")


def _with_resolutions(file_info, resolutions):
    sidecar = deepcopy(calculate_variable_unit_validation(file_info))
    by_name = {variable["name"]: variable for variable in sidecar["variables"]}
    for name, resolution in resolutions.items():
        by_name[name]["resolution"] = resolution
    return sidecar


@pytest.mark.parametrize(
    ("unit", "status"),
    [
        ("m/s^2", "valid"),
        ("m/s²", "valid"),
        ("standard_gravity", "valid"),
        ("[g]", "valid"),
        ("g_0", "valid"),
        ("gram", "valid"),
        ("1", "dimensionless"),
        ("not_a_real_unit_zz", "invalid"),
        ("m//s", "invalid"),
        ("g", "ambiguous"),
    ],
)
def test_unit_parser_classifies_supported_and_problem_units(unit, status):
    assert _parse_unit(unit)["status"] == status


def test_bare_g_message_gives_both_remedies():
    message = _parse_unit("g")["message"]
    assert "gram" in message
    assert "standard_gravity" in message


@pytest.mark.parametrize(
    ("name", "unit"),
    [
        ("velocity (m/s)", "m/s"),
        ("velocity [m/s]", "m/s"),
        ("acceleration [g]", "[g]"),
        ("velocity (m/s) estimate", None),
        ("velocity [m/s] estimate", None),
        ("velocity", None),
    ],
)
def test_name_annotations_are_trailing_only(name, unit):
    assert _name_unit(name) == unit


def test_sidecar_accounts_for_every_resolution_form_and_reports_separate_scores(tmp_path):
    file_info = _csv(tmp_path, ["speed", "score", "station", "missing"])
    sidecar = _with_resolutions(file_info, {
        "speed": {"kind": "unit", "unit": "m/s", "source": "user"},
        "score": {"kind": "dimensionless", "unit": "1", "source": "user"},
        "station": {"kind": "not_applicable", "source": "user"},
    })
    result = calculate_variable_unit_validation(file_info, sidecar)

    assert result["format"] == "aidrin.variable-unit-metadata"
    assert result["version"] == 1
    assert result["unit_vocabulary"] == "pint"
    assert result["summary"]["classification_coverage"] == 0.75
    assert result["summary"]["applicable_unit_coverage"] == pytest.approx(2 / 3)
    assert result["summary"]["metadata_validity"] == 1.0
    assert result["summary"]["all_variables_ready"] is False
    assert result["summary"]["counts"] == {
        "total": 4,
        "valid": 1,
        "missing": 1,
        "invalid": 0,
        "ambiguous": 0,
        "conflicting": 0,
        "dimensionless": 1,
        "not_applicable": 1,
    }


def test_name_units_can_make_all_variables_ready(tmp_path):
    file_info = _csv(tmp_path, ["velocity (meter/second)", "acceleration [g]"])
    result = calculate_variable_unit_validation(file_info)

    assert result["summary"]["all_variables_ready"] is True
    assert [record["name"] for record in result["variables"]] == [
        "velocity (meter/second)",
        "acceleration [g]",
    ]
    assert result["summary"]["counts"]["valid"] == 2


def test_public_python_api_runs_same_validator(tmp_path):
    import aidrin

    file_info = _csv(tmp_path, ["speed"])
    sidecar = _with_resolutions(
        file_info,
        {"speed": {"kind": "unit", "unit": "m/s", "source": "user"}},
    )
    result = aidrin.calculate_variable_unit_validation(file_info, sidecar)

    assert result["summary"]["all_variables_ready"] is True
    assert result["variables"][0]["finding"]["normalized_unit"] == "m / s"


@pytest.mark.parametrize("mutation", [
    lambda sidecar: sidecar.update({"format": "wrong"}),
    lambda sidecar: sidecar.update({"version": 2}),
    lambda sidecar: sidecar.update({"unit_vocabulary": "unknown"}),
    lambda sidecar: sidecar["variables"][0].update({"resolution": {"kind": "unit", "unit": "", "source": "user"}}),
    lambda sidecar: sidecar["variables"][0].update({"resolution": {"kind": "dimensionless", "unit": "m", "source": "user"}}),
    lambda sidecar: sidecar["variables"][0].update({"resolution": {"kind": "not_applicable", "unit": "m", "source": "user"}}),
    lambda sidecar: sidecar["variables"][0].update({"resolution": {"kind": "unit", "unit": "m", "source": "agent"}}),
])
def test_malformed_sidecar_is_rejected(tmp_path, mutation):
    file_info = _csv(tmp_path, ["speed"])
    sidecar = calculate_variable_unit_validation(file_info)
    mutation(sidecar)
    with pytest.raises(ValueError):
        calculate_variable_unit_validation(file_info, sidecar)


def test_sidecar_must_match_dataset_schema_exactly(tmp_path):
    first = _csv(tmp_path, ["Speed"])
    sidecar = calculate_variable_unit_validation(first)
    second_path = tmp_path / "other.csv"
    pd.DataFrame({"speed": [1]}).to_csv(second_path, index=False)

    with pytest.raises(ValueError, match="schema fingerprint does not match"):
        calculate_variable_unit_validation((str(second_path), second_path.name, ".csv"), sidecar)


def test_user_resolution_overrides_conflict_and_retains_observations(tmp_path):
    path = tmp_path / "units.h5"
    with h5py.File(path, "w") as h5:
        dataset = h5.create_dataset("velocity (km/h)", data=[1.0])
        dataset.attrs["units"] = "m/s"

    file_info = (str(path), path.name, ".h5")
    sidecar = _with_resolutions(file_info, {
        "/velocity (km/h)": {
            "kind": "unit",
            "unit": "meter/second",
            "source": "user",
        },
    })
    result = calculate_variable_unit_validation(file_info, sidecar)

    record = result["variables"][0]
    assert record["finding"]["status"] == "valid"
    assert record["resolution"]["source"] == "user"
    assert len(record["observed"]) == 2
    assert record["finding"]["warnings"] == [
        "User resolution overrides detected unit metadata."
    ]
    assert result["summary"]["all_variables_ready"] is True


def test_unresolved_native_name_conflict_fails(tmp_path):
    path = tmp_path / "units.h5"
    with h5py.File(path, "w") as h5:
        dataset = h5.create_dataset("velocity (km/h)", data=[1.0])
        dataset.attrs["units"] = "m/s"

    result = calculate_variable_unit_validation((str(path), path.name, ".h5"))

    assert result["variables"][0]["finding"]["status"] == "conflicting"
    assert result["summary"]["counts"]["conflicting"] == 1
    assert result["summary"]["all_variables_ready"] is False


def test_equivalent_native_and_name_declarations_do_not_conflict(tmp_path):
    path = tmp_path / "units.h5"
    with h5py.File(path, "w") as h5:
        dataset = h5.create_dataset("velocity (meter/second)", data=[1.0])
        dataset.attrs["units"] = "m/s"

    result = calculate_variable_unit_validation((str(path), path.name, ".h5"))

    assert result["variables"][0]["finding"]["status"] == "valid"
    assert result["variables"][0]["resolution"]["source"] == "detected"
    assert result["summary"]["all_variables_ready"] is True


def test_sidecar_round_trip_is_deterministic_and_does_not_change_dataset(tmp_path):
    file_info = _csv(tmp_path, ["speed", "station"])
    before = Path(file_info[0]).read_bytes()
    sidecar = _with_resolutions(file_info, {
        "speed": {"kind": "unit", "unit": "m/s", "source": "user"},
        "station": {"kind": "not_applicable", "source": "user"},
    })

    first = calculate_variable_unit_validation(file_info, sidecar)
    second = calculate_variable_unit_validation(file_info, first)

    assert second == first
    assert Path(file_info[0]).read_bytes() == before


def test_native_hdf5_discovery_reads_units_without_values(tmp_path):
    path = tmp_path / "native.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("group/temperature", shape=(100,), dtype="f8").attrs["unit"] = "kelvin"

    targets = discover_variable_units((str(path), path.name, ".h5"))

    assert targets == [{
        "name": "/group/temperature",
        "dtype": "float64",
        "target_type": "hdf5_dataset",
        "unit_candidates": [{"source": "native:unit", "unit": "kelvin"}],
    }]


def test_hdf5_selected_keys_limit_logical_schema(tmp_path):
    path = tmp_path / "native.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("a", data=[1])
        h5.create_dataset("b", data=[2])

    targets = discover_variable_units((str(path), path.name, ".h5", ["/b"]))

    assert [target["name"] for target in targets] == ["/b"]


def test_pandas_hdfstore_discovers_logical_columns_not_internal_datasets(tmp_path):
    path = tmp_path / "frame.h5"
    pd.DataFrame({"speed (m/s)": [1.0], "station": ["A"]}).to_hdf(path, key="data", format="table")

    targets = discover_variable_units((str(path), path.name, ".h5"))

    assert [target["name"] for target in targets] == ["speed (m/s)", "station"]
    assert targets[0]["unit_candidates"] == [{"source": "name", "unit": "m/s"}]


def test_parquet_field_metadata_prefers_units_and_accepts_unit_alias(tmp_path):
    path = tmp_path / "units.parquet"
    schema = pa.schema([
        pa.field("speed", pa.float64(), metadata={b"units": b"m/s"}),
        pa.field("temperature", pa.float64(), metadata={b"unit": b"kelvin"}),
    ])
    pq.write_table(pa.Table.from_arrays([pa.array([1.0]), pa.array([273.0])], schema=schema), path)

    targets = discover_variable_units((str(path), path.name, ".parquet"))

    assert targets[0]["unit_candidates"] == [{"source": "native:units", "unit": "m/s"}]
    assert targets[1]["unit_candidates"] == [{"source": "native:unit", "unit": "kelvin"}]


def test_empty_logical_schema_has_null_scores(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps([]), encoding="utf-8")

    result = calculate_variable_unit_validation((str(path), path.name, ".json"))

    assert result["summary"]["classification_coverage"] is None
    assert result["summary"]["applicable_unit_coverage"] is None
    assert result["summary"]["metadata_validity"] is None
    assert result["summary"]["all_variables_ready"] is False
    assert result["summary"]["counts"]["total"] == 0
