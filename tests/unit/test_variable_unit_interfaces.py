"""Headless, CLI, batch, and remote tests for variable-unit validation."""

import io
import json
from unittest.mock import patch

import pandas as pd
import pytest

from aidrin.compute.remote import remote_headless_runner
from aidrin.headless.api import METRIC_REGISTRY, run_batch_metrics, run_metric
from aidrin.headless.config import HeadlessConfig
from aidrin.structured_data_metrics.variable_unit_validation import (
    calculate_variable_unit_validation,
)


def _dataset(tmp_path):
    path = tmp_path / "data.csv"
    pd.DataFrame({"speed": [1.0], "station": ["A"]}).to_csv(path, index=False)
    return path


def _sidecar(dataset):
    file_info = (str(dataset), dataset.name, ".csv")
    sidecar = calculate_variable_unit_validation(file_info)
    resolutions = {
        "speed": {"kind": "unit", "unit": "m/s", "source": "user"},
        "station": {"kind": "not_applicable", "source": "user"},
    }
    for variable in sidecar["variables"]:
        variable["resolution"] = resolutions[variable["name"]]
    return sidecar


def _run_cli(*argv):
    from aidrin.headless.cli import main

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 0
    with patch("sys.argv", ["aidrin", *argv]), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        try:
            main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    return stdout.getvalue(), stderr.getvalue(), code


def test_metric_is_registered_as_data_structure():
    assert METRIC_REGISTRY["variable_unit_validation"]["category"] == "data-structure"


def test_headless_api_without_sidecar_returns_read_only_audit(tmp_path):
    result = run_metric(
        "variable-unit-validation",
        str(_dataset(tmp_path)),
        save_images=False,
    )

    assert result["format"] == "aidrin.variable-unit-metadata"
    assert result["summary"]["counts"]["missing"] == 2


def test_headless_api_accepts_inline_sidecar_json_and_host_local_file(tmp_path):
    dataset = _dataset(tmp_path)
    sidecar = _sidecar(dataset)
    sidecar_path = tmp_path / "data.units.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    inline = run_metric(
        "variable-unit-validation",
        str(dataset),
        unit_metadata_json=json.dumps(sidecar),
        save_images=False,
    )
    from_file = run_metric(
        "variable-unit-validation",
        str(dataset),
        unit_metadata_file=str(sidecar_path),
        save_images=False,
    )

    assert inline == from_file
    assert inline["summary"]["all_variables_ready"] is True


def test_headless_api_rejects_multiple_sidecar_sources(tmp_path):
    dataset = _dataset(tmp_path)
    sidecar = _sidecar(dataset)
    with pytest.raises(ValueError, match="at most one variable-unit metadata source"):
        run_metric(
            "variable-unit-validation",
            str(dataset),
            unit_metadata=sidecar,
            unit_metadata_json=json.dumps(sidecar),
            save_images=False,
        )


def test_cli_accepts_unit_metadata_json_and_file(tmp_path):
    dataset = _dataset(tmp_path)
    sidecar = _sidecar(dataset)
    sidecar_path = tmp_path / "data.units.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    inline_out, inline_err, inline_code = _run_cli(
        "run", "variable-unit-validation", str(dataset),
        "--unit-metadata-json", json.dumps(sidecar),
    )
    file_out, file_err, file_code = _run_cli(
        "variable-unit-validation", str(dataset),
        "--unit-metadata-file", str(sidecar_path),
    )

    assert inline_code == 0, inline_err
    assert file_code == 0, file_err
    assert json.loads(inline_out)["summary"]["all_variables_ready"] is True
    assert json.loads(file_out)["summary"]["all_variables_ready"] is True


def test_cli_sidecar_options_are_mutually_exclusive(tmp_path):
    _out, error, code = _run_cli(
        "run",
        "variable-unit-validation",
        str(_dataset(tmp_path)),
        "--unit-metadata-json",
        "{}",
        "--unit-metadata-file",
        "/tmp/units.json",
    )

    assert code == 2
    assert "not allowed with argument" in error


@pytest.mark.parametrize("source", ["inline", "file"])
def test_batch_normalizes_and_forwards_mapping_sources(tmp_path, source):
    dataset = _dataset(tmp_path)
    payload = {
        "file-path": str(dataset),
        "metrics": ["variable-unit-validation"],
        "save-images": False,
    }
    if source == "inline":
        payload["unit-metadata"] = _sidecar(dataset)
    else:
        sidecar_path = tmp_path / "data.units.json"
        sidecar_path.write_text(json.dumps(_sidecar(dataset)), encoding="utf-8")
        payload["unit-metadata-file"] = str(sidecar_path)

    config = HeadlessConfig.from_dict(payload)
    result = run_batch_metrics(config)["variable_unit_validation"]

    assert result["summary"]["all_variables_ready"] is True


def test_remote_headless_dispatch_resolves_sidecar_file_on_execution_host(tmp_path):
    dataset = _dataset(tmp_path)
    sidecar_path = tmp_path / "remote.units.json"
    sidecar_path.write_text(json.dumps(_sidecar(dataset)), encoding="utf-8")

    result = remote_headless_runner("run_metric", {
        "metric_name": "variable-unit-validation",
        "file_path": str(dataset),
        "unit_metadata_file": str(sidecar_path),
        "save_images": False,
    })

    assert result["summary"]["all_variables_ready"] is True
