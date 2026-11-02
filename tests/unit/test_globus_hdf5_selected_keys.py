"""Globus web path carries HDF5 selected_keys (issue #236)."""

from aidrin.compute.remote import (
    build_remote_file_info,
    normalize_selected_keys,
    remote_file_inventory,
    remote_headless_runner,
)


def test_normalize_selected_keys_accepts_list_and_csv():
    assert normalize_selected_keys(["a", "b"]) == ["a", "b"]
    assert normalize_selected_keys("a, b") == ["a", "b"]
    assert normalize_selected_keys(None) == []


def test_build_remote_file_info_appends_keys():
    assert build_remote_file_info("/data/x.h5", "x.h5", ".h5") == (
        "/data/x.h5",
        "x.h5",
        ".h5",
    )
    assert build_remote_file_info("/data/x.h5", "x.h5", ".h5", ["grp/d1"]) == (
        "/data/x.h5",
        "x.h5",
        ".h5",
        ["grp/d1"],
    )


def test_remote_file_inventory_rejects_non_hdf5():
    result = remote_file_inventory("/data/x.csv", ".csv")
    assert result["success"] is False
    assert "HDF5" in result["error"]


def test_remote_headless_inventory_command(tmp_path):
    path = tmp_path / "empty.h5"
    path.write_bytes(b"not hdf5")
    result = remote_headless_runner(
        "inventory",
        {"file_path": str(path), "file_type": ".h5"},
    )
    assert result.get("success") is False or "Error" in result


def _multi_dataset_h5(tmp_path):
    """Three same-length 1D datasets, one mismatched, so layout is multi_dataset."""
    import h5py
    import numpy as np

    path = tmp_path / "multi.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("age", data=np.arange(100))
        f.create_dataset("income", data=np.linspace(0, 1e5, 100))
        f.create_group("demo").create_dataset("sex", data=np.array([b"M", b"F"] * 50))
        f.create_dataset("other_len", data=np.arange(7))
    return str(path)


def test_normalize_selected_keys_drops_none_entries():
    """A null in the list must not become a dataset literally named "None"."""
    assert normalize_selected_keys([None]) == []
    assert normalize_selected_keys(["age", None, "income"]) == ["age", "income"]
    assert normalize_selected_keys([""]) == []


def test_unreadable_hdf5_keeps_read_file_message(tmp_path):
    """inventory() must not leak h5py internals in place of read_file's message."""
    from aidrin.compute.remote import remote_metric_runner

    result = remote_metric_runner(
        "summary_statistics", str(tmp_path / "gone.h5"), "gone.h5", ".h5"
    )
    assert result["error"] == f"File not found: {tmp_path / 'gone.h5'}"


def test_invalid_selection_reports_the_reader_verdict(tmp_path):
    """An invalid selection must say why, not "needs an explicit selection"."""
    from aidrin.compute.remote import remote_metric_runner

    path = _multi_dataset_h5(tmp_path)
    cases = {
        ("does_not_exist",): "Unknown dataset: does_not_exist",
        ("age", "other_len"): "same length",
        ("demo",): "not a dataset",
    }
    for keys, expected in cases.items():
        result = remote_metric_runner(
            "completeness", path, "multi.h5", ".h5", selected_keys=list(keys)
        )
        assert expected in result["error"], (keys, result)


def test_valid_selection_still_runs(tmp_path):
    from aidrin.compute.remote import remote_metric_runner

    result = remote_metric_runner(
        "completeness",
        _multi_dataset_h5(tmp_path),
        "multi.h5",
        ".h5",
        selected_keys=["age", "income"],
    )
    assert "error" not in result, result


def test_file_inventory_is_not_gated_on_a_selection(tmp_path):
    """file_inventory is how the picker learns the list, so it must not be gated."""
    from aidrin.compute.remote import remote_metric_runner

    result = remote_metric_runner(
        "file_inventory", _multi_dataset_h5(tmp_path), "multi.h5", ".h5"
    )
    assert result["success"] is True
    assert result["type"] == "multi_dataset"
