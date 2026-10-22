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
