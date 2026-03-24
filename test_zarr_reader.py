"""
Tests for zarrReader.

Covers the three-method contract (read / parse / filter) and the core
fill-value classification mechanism (_collect_fill_values).

Follows the conventions established in test_hdf5_reader.py:
- Root-level test file
- pkg_resources compatibility shim
- pytest tmp_path fixture
- caplog assertions for WARNING/INFO log messages
"""

import logging
import os
import sys
import types

# Compatibility shim — see test_hdf5_reader.py for explanation.
if "pkg_resources" not in sys.modules:
    _pkg_resources = types.ModuleType("pkg_resources")

    class _Dist:
        def __init__(self):
            self.version = "0.0.0"

    _pkg_resources.get_distribution = lambda _name: _Dist()
    sys.modules["pkg_resources"] = _pkg_resources

import numpy as np
import pytest

zarr = pytest.importorskip("zarr", reason="zarr is required for zarrReader tests")

from aidrin.file_handling.readers.zarr_reader import zarrReader


@pytest.fixture
def logger():
    return logging.getLogger("test_zarr_reader")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dir_store(path, arrays: dict, fill_values: dict = None):
    """Create a Zarr directory store with the given named arrays."""
    root = zarr.open_group(str(path), mode="w")
    for name, data in arrays.items():
        fv = (fill_values or {}).get(name)
        kwargs = {} if fv is None else {"fill_value": fv}
        root.create_dataset(name, data=data, **kwargs)
    return str(path)


def _make_zip_store(zip_path, arrays: dict):
    """Create a Zarr zip store with the given named arrays."""
    store = zarr.ZipStore(str(zip_path), mode="w")
    root = zarr.open_group(store, mode="w")
    for name, data in arrays.items():
        root.create_dataset(name, data=data)
    store.close()
    return str(zip_path)


# ---------------------------------------------------------------------------
# read()
# ---------------------------------------------------------------------------

class TestZarrRead:
    def test_directory_store_returns_dataframe(self, tmp_path, logger):
        path = _make_dir_store(
            tmp_path / "s.zarr", {"x": np.array([1.0, 2.0, 3.0])}
        )
        df = zarrReader(path, logger).read()
        assert df is not None
        assert not df.empty

    def test_zip_store_returns_dataframe(self, tmp_path, logger):
        path = _make_zip_store(
            tmp_path / "s.zarr.zip", {"x": np.array([10, 20, 30], dtype=np.int32)}
        )
        df = zarrReader(path, logger).read()
        assert df is not None
        assert not df.empty

    def test_column_names_are_strings(self, tmp_path, logger):
        path = _make_dir_store(
            tmp_path / "s.zarr", {"m": np.array([[1, 2], [3, 4]], dtype=np.int32)}
        )
        df = zarrReader(path, logger).read()
        assert df is not None
        assert all(isinstance(c, str) for c in df.columns)

    def test_non_numeric_array_skipped(self, tmp_path, logger):
        store_path = str(tmp_path / "s.zarr")
        root = zarr.open_group(store_path, mode="w")
        root.create_dataset("labels", data=np.array(["a", "b", "c"]))
        root.create_dataset("values", data=np.array([1.0, 2.0, 3.0]))
        df = zarrReader(store_path, logger).read()
        assert df is not None
        assert not df.empty

    def test_empty_store_returns_none(self, tmp_path, logger):
        zarr.open_group(str(tmp_path / "empty.zarr"), mode="w")
        df = zarrReader(str(tmp_path / "empty.zarr"), logger).read()
        assert df is None

    def test_invalid_path_returns_none(self, tmp_path, logger):
        df = zarrReader(str(tmp_path / "does_not_exist.zarr"), logger).read()
        assert df is None


# ---------------------------------------------------------------------------
# _collect_fill_values() — the core mechanism
# ---------------------------------------------------------------------------

class TestFillValueClassification:
    """The explicit/uncertain split is the central mechanism this PoC demonstrates.

    Non-zero metadata fill_value → explicit (replaced silently).
    Default zero fill_value     → uncertain (WARNING emitted before replacement).
    User-supplied fill_values   → always explicit (replaced silently).
    """

    def test_nonzero_fill_replaced_silently(self, tmp_path, logger, caplog):
        data = np.array([1.0, -9999.0, 3.0], dtype=np.float64)
        path = _make_dir_store(
            tmp_path / "s.zarr", {"d": data}, fill_values={"d": -9999.0}
        )
        with caplog.at_level(logging.WARNING):
            df = zarrReader(path, logger).read()
        assert df is not None
        assert df.iloc[:, 0].isna().sum() == 1
        # No warning: the non-zero sentinel is unambiguously explicit
        assert not any("default fill value" in r.message for r in caplog.records)

    def test_zero_default_fill_emits_warning(self, tmp_path, logger, caplog):
        data = np.array([0, 1, 2, 0, 4], dtype=np.int32)
        path = _make_dir_store(tmp_path / "s.zarr", {"d": data})
        with caplog.at_level(logging.WARNING):
            zarrReader(path, logger).read()
        assert any("default fill value" in r.message for r in caplog.records)

    def test_user_supplied_fill_replaces_silently(self, tmp_path, logger, caplog):
        data = np.array([1.0, 42.0, 3.0], dtype=np.float64)
        path = _make_dir_store(tmp_path / "s.zarr", {"d": data})
        with caplog.at_level(logging.WARNING):
            df = zarrReader(path, logger, fill_values=[42.0]).read()
        assert df is not None
        assert df.iloc[:, 0].isna().sum() == 1
        assert not any("default fill value" in r.message for r in caplog.records)

    def test_completeness_reflects_fill_replacement(self, tmp_path, logger):
        """After replacement, completeness computed from the DataFrame is correct."""
        data = np.array([1.0, -9999.0, 3.0, -9999.0, 5.0], dtype=np.float64)
        path = _make_dir_store(
            tmp_path / "s.zarr", {"d": data}, fill_values={"d": -9999.0}
        )
        df = zarrReader(path, logger).read()
        completeness = 1 - df.iloc[:, 0].isnull().mean()
        assert abs(completeness - 0.6) < 1e-9


# ---------------------------------------------------------------------------
# parse()
# ---------------------------------------------------------------------------

class TestZarrParse:
    def test_returns_group_names(self, tmp_path, logger):
        store_path = str(tmp_path / "s.zarr")
        root = zarr.open_group(store_path, mode="w")
        root.create_group("group_a")
        root["group_a"].create_group("sub")
        root.create_dataset("arr", data=np.array([1.0]))
        groups = zarrReader(store_path, logger).parse()
        assert groups is not None
        assert "group_a" in groups

    def test_excludes_arrays(self, tmp_path, logger):
        store_path = str(tmp_path / "s.zarr")
        root = zarr.open_group(store_path, mode="w")
        root.create_dataset("only_array", data=np.array([1.0, 2.0]))
        groups = zarrReader(store_path, logger).parse()
        # Arrays are not groups — list should be empty (not None)
        assert groups is not None
        assert "only_array" not in groups

    def test_invalid_path_returns_none(self, tmp_path, logger):
        result = zarrReader(str(tmp_path / "nope.zarr"), logger).parse()
        assert result is None


# ---------------------------------------------------------------------------
# filter()
# ---------------------------------------------------------------------------

class TestZarrFilter:
    def test_filter_writes_new_zip(self, tmp_path, logger):
        store_path = str(tmp_path / "s.zarr")
        root = zarr.open_group(store_path, mode="w")
        ga = root.create_group("group_a")
        ga.create_dataset("x", data=np.array([1.0, 2.0]))
        root.create_group("group_b")

        upload_folder = str(tmp_path / "uploads")
        os.makedirs(upload_folder)

        result = zarrReader(store_path, logger).filter(
            ["group_a"],
            upload_folder=upload_folder,
            filename="test.zarr.zip",
        )
        assert result is not None
        assert os.path.exists(result)

    def test_filter_comma_string_accepted(self, tmp_path, logger):
        store_path = str(tmp_path / "s.zarr")
        root = zarr.open_group(store_path, mode="w")
        root.create_group("g1")
        root.create_group("g2")

        upload_folder = str(tmp_path / "uploads")
        os.makedirs(upload_folder)

        result = zarrReader(store_path, logger).filter(
            "g1, g2",
            upload_folder=upload_folder,
            filename="test.zarr.zip",
        )
        assert result is not None
