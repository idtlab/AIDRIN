"""Multi-file pilot controls; all records are synthetic."""

import hashlib
import json
from pathlib import Path

import pytest

from aidrin.headless.api import run_metric


ROOT = Path(__file__).parents[2]
LOADER = f"{ROOT}/examples/grouped_time_series/multi_file_loader.py:load"


def run(path, **kwargs):
    return run_metric(
        "grouped_time_series", str(path), loader=LOADER, save_images=False,
        group_columns=["record_id", "station", "component"], timestamp_column="time",
        expected_cadence=.01, tolerance=1e-6, **kwargs,
    )


def test_multi_file_example_preserves_sources_and_detects_short_component(monkeypatch):
    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "0")
    directory = ROOT / "examples/grouped_time_series"
    paths = [directory / "components/h1.csv", directory / "components/h2.csv"]
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    result = run(directory / "multi_file_manifest.json", expected_count=5, expected_duration=.04)
    groups = {group["group"]["component"]: group for group in result["groups"]}
    assert groups["H1"]["finding_counts"] == {}
    assert groups["H2"]["finding_counts"] == {"count_mismatch": 1, "duration_mismatch": 1}
    assert groups["H2"]["first_time"] == .01
    assert groups["H2"]["row_count"] == 3
    assert all(group["time_reference"] == "relative_or_unspecified" for group in groups.values())
    assert before == [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]


def test_regular_shifted_records_do_not_establish_synchronization(tmp_path, monkeypatch):
    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "0")
    records = []
    for name, times in [("a", [0, .01, .02]), ("b", [.01, .02, .03])]:
        (tmp_path / f"{name}.csv").write_text("t\n" + "\n".join(map(str, times)) + "\n")
        records.append(dict(record_id=name, station="S", component="H1", path=f"{name}.csv", timestamp_column="t"))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(records))
    result = run(manifest, expected_count=3, expected_duration=.02)
    assert result["summary"]["group_count"] == 2  # Same station/component, separate records.
    assert result["summary"]["finding_counts"] == {}
    assert {group["first_time"] for group in result["groups"]} == {0, .01}
    records[1]["record_id"] = "a"
    manifest.write_text(json.dumps(records))
    with pytest.raises(ValueError, match="Duplicate record_id"):
        run(manifest)


def test_component_failure_is_not_silently_omitted(tmp_path, monkeypatch):
    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "0")
    (tmp_path / "empty.csv").write_text("t\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([dict(record_id="empty", station="S", component="H1",
                                         path="empty.csv", timestamp_column="t")]))
    with pytest.raises(ValueError, match="empty component file"):
        run(manifest)


def test_mixed_record_dtypes_preserve_integer_ticks(tmp_path, monkeypatch):
    monkeypatch.setenv("AIDRIN_FRAME_CACHE", "0")
    (tmp_path / "ticks.csv").write_text("t\n9007199254740992\n9007199254740993\n")
    (tmp_path / "elapsed.csv").write_text("t\n0.0\n0.01\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([
        dict(record_id=name, station="S", component="H1", path=f"{name}.csv", timestamp_column="t")
        for name in ["ticks", "elapsed"]
    ]))
    result = run(manifest)
    ticks = next(group for group in result["groups"] if group["group"]["record_id"] == "ticks")
    assert ticks["unique_time_count"] == 2
    assert ticks["last_time"] == "9007199254740993"
    assert ticks["observed_duration"] == 1
