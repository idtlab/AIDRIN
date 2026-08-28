"""Unit tests for multi-format support in aidrin.headless.api custom-metric functions.

run_custom_metric_logic() / run_custom_metric_remedy() used to call pd.read_csv()
directly, so any non-CSV dataset would silently be parsed as if it were CSV. These
tests exercise every reader-backed format through the same read_file()/READER_MAP
abstraction the built-in metrics already use, and confirm remedy() output is always
written as CSV regardless of the input format.
"""

import json
import os
import sys
import textwrap
import types

# pkg_resources was removed from the stdlib in Python 3.12+; dython imports it
# at module level, which would otherwise break importing aidrin.headless.api.
if "pkg_resources" not in sys.modules:
    _pkg_resources = types.ModuleType("pkg_resources")

    class _Dist:
        def __init__(self):
            self.version = "0.0.0"

    _pkg_resources.get_distribution = lambda _name: _Dist()
    sys.modules["pkg_resources"] = _pkg_resources

import h5py
import numpy as np
import pandas as pd
import pytest

from aidrin.headless.api import run_custom_metric_logic, run_custom_metric_remedy, run_metric

_SAMPLE = pd.DataFrame({"age": [25, 30, 35, 40], "income": [50000, 60000, 70000, 80000]})

_CUSTOM_SCRIPT = textwrap.dedent(
    """
    from aidrin.custom_metrics.base_dr import BaseDRAgent

    class CustomDR(BaseDRAgent):
        def metric(self, **kwargs):
            return {"row_count": len(self.dataset), "columns": sorted(self.dataset.columns.tolist())}

        def remedy(self, **kwargs):
            return self.dataset.copy()
    """
)


@pytest.fixture
def script_path(tmp_path):
    path = tmp_path / "my_audit.py"
    path.write_text(_CUSTOM_SCRIPT)
    return str(path)


def _write_csv(tmp_path):
    path = tmp_path / "data.csv"
    _SAMPLE.to_csv(path, index=False)
    return str(path)


def _write_parquet(tmp_path):
    path = tmp_path / "data.parquet"
    _SAMPLE.to_parquet(path)
    return str(path)


def _write_json(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps(_SAMPLE.to_dict(orient="records")))
    return str(path)


def _write_excel(tmp_path):
    path = tmp_path / "data.xlsx"
    _SAMPLE.to_excel(path, index=False)
    return str(path)


def _write_npz(tmp_path):
    path = tmp_path / "data.npz"
    np.savez(path, age=_SAMPLE["age"].to_numpy(), income=_SAMPLE["income"].to_numpy())
    return str(path)


def _write_hdf5(tmp_path):
    # A single structured dataset (rather than sibling 1D arrays) so the
    # reader's row-building logic yields one row per record with "age" and
    # "income" as named columns, matching every other format's fixture.
    path = tmp_path / "data.h5"
    dtype = np.dtype([("age", "i8"), ("income", "i8")])
    records = np.array(list(zip(_SAMPLE["age"], _SAMPLE["income"])), dtype=dtype)
    with h5py.File(path, "w") as f:
        f.create_dataset("records", data=records)
    return str(path)


_FORMATS = {
    "csv": _write_csv,
    "parquet": _write_parquet,
    "json": _write_json,
    "xlsx": _write_excel,
    "npz": _write_npz,
    "h5": _write_hdf5,
}


@pytest.mark.parametrize("fmt", sorted(_FORMATS))
def test_run_custom_metric_logic_supports_format(fmt, tmp_path, script_path):
    file_path = _FORMATS[fmt](tmp_path)
    result = run_custom_metric_logic(script_path, file_path, file_type=fmt)
    assert result["row_count"] == len(_SAMPLE)
    assert result["columns"] == ["age", "income"]


@pytest.mark.parametrize("fmt", sorted(_FORMATS))
def test_run_custom_metric_remedy_always_saves_csv(fmt, tmp_path, script_path):
    file_path = _FORMATS[fmt](tmp_path)
    output_dir = tmp_path / "remedy_out"
    saved_path = run_custom_metric_remedy(
        script_path, file_path, output_dir=str(output_dir), file_type=fmt
    )
    assert saved_path.endswith(".csv")
    assert os.path.exists(saved_path)
    remedied = pd.read_csv(saved_path)
    assert len(remedied) == len(_SAMPLE)


def test_run_custom_metric_logic_infers_type_from_extension(tmp_path, script_path):
    """When file_type is omitted, the extension alone should resolve the reader."""
    file_path = _write_parquet(tmp_path)
    result = run_custom_metric_logic(script_path, file_path)
    assert result["row_count"] == len(_SAMPLE)


# ---------------------------------------------------------------------------
# run_metric()'s custom-metric fallback must not mangle the script path
# ---------------------------------------------------------------------------


def test_run_metric_resolves_hyphenated_custom_script_path(tmp_path):
    """run_metric()'s custom-metric fallback used to pass the lowercased,
    hyphen-to-underscore-mangled `metric_key` (meant only for METRIC_REGISTRY
    lookups) into run_custom_metric_logic() instead of the original
    metric_name. Any script path containing a hyphen or mixed case (e.g. a
    project directory or username) would then fail to resolve on disk and
    surface as a misleading "Unknown metric" error."""
    script_dir = tmp_path / "My-Project"
    script_dir.mkdir()
    script_path = script_dir / "My-Audit.py"
    script_path.write_text(_CUSTOM_SCRIPT)
    file_path = _write_csv(tmp_path)

    result = run_metric(str(script_path), file_path, save_images=False)
    assert result["row_count"] == len(_SAMPLE)


# ---------------------------------------------------------------------------
# remedy() must receive the metric_results computed by metric()
# ---------------------------------------------------------------------------

_METRIC_RESULTS_SCRIPT = textwrap.dedent(
    """
    from aidrin.custom_metrics.base_dr import BaseDRAgent

    class CustomDR(BaseDRAgent):
        def metric(self, **kwargs):
            return {"row_count": len(self.dataset)}

        def remedy(self, **kwargs):
            df = self.dataset.copy()
            metric_results = kwargs.get("metric_results", {})
            df["metric_row_count"] = metric_results.get("row_count")
            return df
    """
)


def test_run_custom_metric_remedy_passes_metric_results_to_remedy(tmp_path):
    """The web UI runs metric() before remedy() and passes the results in
    (web/routes/custom.py), matching the contract documented in the
    generated template ("Access metric results via
    kwargs.get('metric_results', {})"). run_custom_metric_remedy() used to
    skip metric() entirely, so remedy() invoked via the CLI/MCP always saw
    an empty metric_results dict — silently inconsistent with the web UI."""
    script_path = tmp_path / "metric_results_audit.py"
    script_path.write_text(_METRIC_RESULTS_SCRIPT)
    file_path = _write_csv(tmp_path)
    output_dir = tmp_path / "remedy_out"

    saved_path = run_custom_metric_remedy(str(script_path), file_path, output_dir=str(output_dir))

    remedied = pd.read_csv(saved_path)
    assert (remedied["metric_row_count"] == len(_SAMPLE)).all()
