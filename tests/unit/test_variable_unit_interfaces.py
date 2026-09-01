"""Headless, CLI, batch, and remote tests for variable-unit validation."""

import io
import json
from unittest.mock import patch

import pandas as pd
import pytest

from aidrin.compute.remote import remote_headless_runner
from aidrin.headless.api import METRIC_REGISTRY, run_batch_metrics, run_metric
from aidrin.headless.config import HeadlessConfig


def _dataset(tmp_path):
    path = tmp_path / "data.csv"
    pd.DataFrame({"speed": [1.0], "station": ["A"]}).to_csv(path, index=False)
    return path


def _mapping():
    return {
        "speed": {"unit": "m/s"},
        "station": {"status": "not_applicable"},
    }


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


def test_headless_api_accepts_inline_json_and_host_local_file(tmp_path):
    dataset = _dataset(tmp_path)
    mapping_path = tmp_path / "units.json"
    mapping_path.write_text(json.dumps(_mapping()), encoding="utf-8")

    inline = run_metric(
        "variable-unit-validation",
        str(dataset),
        unit_declarations_json=json.dumps(_mapping()),
        save_images=False,
    )
    from_file = run_metric(
        "variable-unit-validation",
        str(dataset),
        units_file=str(mapping_path),
        save_images=False,
    )

    assert inline == from_file
    assert inline["all_variables_ready"] is True


def test_headless_api_rejects_multiple_mapping_sources(tmp_path):
    with pytest.raises(ValueError, match="at most one variable-unit mapping source"):
        run_metric(
            "variable-unit-validation",
            str(_dataset(tmp_path)),
            unit_declarations=_mapping(),
            unit_declarations_json=json.dumps(_mapping()),
            save_images=False,
        )


def test_cli_accepts_units_json_and_units_file(tmp_path):
    dataset = _dataset(tmp_path)
    mapping_path = tmp_path / "units.json"
    mapping_path.write_text(json.dumps(_mapping()), encoding="utf-8")

    inline_out, inline_err, inline_code = _run_cli(
        "run", "variable-unit-validation", str(dataset), "--units-json", json.dumps(_mapping())
    )
    file_out, file_err, file_code = _run_cli(
        "variable-unit-validation", str(dataset), "--units-file", str(mapping_path)
    )

    assert inline_code == 0, inline_err
    assert file_code == 0, file_err
    assert json.loads(inline_out)["all_variables_ready"] is True
    assert json.loads(file_out)["all_variables_ready"] is True


def test_cli_mapping_options_are_mutually_exclusive(tmp_path):
    _out, error, code = _run_cli(
        "run",
        "variable-unit-validation",
        str(_dataset(tmp_path)),
        "--units-json",
        "{}",
        "--units-file",
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
        payload["unit-declarations"] = _mapping()
    else:
        mapping_path = tmp_path / "units.json"
        mapping_path.write_text(json.dumps(_mapping()), encoding="utf-8")
        payload["units-file"] = str(mapping_path)

    config = HeadlessConfig.from_dict(payload)
    result = run_batch_metrics(config)["variable_unit_validation"]

    assert result["all_variables_ready"] is True


def test_remote_headless_dispatch_resolves_units_file_on_execution_host(tmp_path):
    dataset = _dataset(tmp_path)
    mapping_path = tmp_path / "remote-units.json"
    mapping_path.write_text(json.dumps(_mapping()), encoding="utf-8")

    result = remote_headless_runner("run_metric", {
        "metric_name": "variable-unit-validation",
        "file_path": str(dataset),
        "units_file": str(mapping_path),
        "save_images": False,
    })

    assert result["all_variables_ready"] is True
