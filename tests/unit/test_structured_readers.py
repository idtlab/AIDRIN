"""Unit tests for structured reader scaffold and Zarr reader."""

import logging
import sys
import types

import numpy as np
import pytest

# Compatibility shim: pkg_resources for clean Python 3.12+ environments.
if "pkg_resources" not in sys.modules:
    _pkg_resources = types.ModuleType("pkg_resources")

    class _Dist:
        def __init__(self):
            self.version = "0.0.0"

    _pkg_resources.get_distribution = lambda _name: _Dist()
    sys.modules["pkg_resources"] = _pkg_resources

from aidrin.file_handling.file_parser import (
    GLOBUS_FILE_TYPES,
    READER_MAP,
    SUPPORTED_FILE_TYPES,
    read_file,
)
from aidrin.file_handling.readers.root_reader import rootReader
from aidrin.file_handling.readers.structured import (
    INVENTORY_EMPTY,
    INVENTORY_LEGACY,
    INVENTORY_MULTI,
    INVENTORY_SINGLE,
    INVENTORY_UNSUPPORTED,
    USER_FACING_INVENTORY_TYPES,
    make_inventory,
)
from aidrin.file_handling.readers.zarr_reader import zarrReader

zarr = pytest.importorskip("zarr")


@pytest.fixture
def logger():
    return logging.getLogger("test_structured_readers")


@pytest.mark.parametrize("reader_cls", [rootReader])
def test_root_stub_inventory_contract(tmp_path, logger, reader_cls):
    path = tmp_path / "placeholder"
    path.write_text("not used", encoding="utf-8")
    inv = reader_cls(str(path), logger).inventory()

    assert set(inv.keys()) == {"type", "datasets", "groups"}
    assert inv["type"] == INVENTORY_UNSUPPORTED
    assert inv["datasets"] == []
    assert inv["groups"] == []
    assert inv["type"] not in USER_FACING_INVENTORY_TYPES


def test_make_inventory_helper():
    inv = make_inventory(INVENTORY_UNSUPPORTED)
    assert inv == {"type": INVENTORY_UNSUPPORTED, "datasets": [], "groups": []}


def test_zarr_registered_for_cli_not_local_upload():
    assert ".zarr" in READER_MAP
    local_exts = [ext for ext, _ in SUPPORTED_FILE_TYPES]
    globus_exts = [ext for ext, _ in GLOBUS_FILE_TYPES]
    assert ".zarr" not in local_exts
    assert ".zarr" in globus_exts


def _write_single_array_store(path):
    arr = zarr.open(str(path), mode="w", shape=(5,), dtype="f8")
    arr[:] = np.arange(5, dtype=np.float64)
    arr.attrs["unit"] = "m"


def _write_group_store(path):
    root = zarr.open_group(str(path), mode="w")
    root.attrs["license"] = "MIT"
    a = root.create_array("temp", shape=(4,), dtype="f8")
    a[:] = np.arange(4, dtype=np.float64)
    a.attrs["unit"] = "C"
    g = root.create_group("station")
    b = g.create_array("x", shape=(4,), dtype="i4")
    b[:] = np.arange(4, dtype=np.int32)


def _write_incompatible_root_store(path):
    root = zarr.open_group(str(path), mode="w")
    a = root.create_array("short", shape=(3,), dtype="f8")
    a[:] = [1.0, 2.0, 3.0]
    b = root.create_array("long", shape=(5,), dtype="f8")
    b[:] = np.arange(5, dtype=np.float64)


def _write_grouped_hierarchical_store(path):
    root = zarr.open_group(str(path), mode="w")
    for station in ("S1", "S2"):
        g = root.create_group(station)
        for axis, length in (("X", 10), ("Y", 10), ("meta", 1)):
            arr = g.create_array(axis, shape=(length,), dtype="f8")
            arr[:] = np.arange(length, dtype=np.float64)


def test_zarr_single_array_inventory_and_read(tmp_path, logger):
    store = tmp_path / "single.zarr"
    _write_single_array_store(store)
    reader = zarrReader(str(store), logger)
    inv = reader.inventory()
    assert inv["type"] == INVENTORY_SINGLE
    assert len(inv["datasets"]) == 1

    df = reader.read()
    assert df is not None
    assert list(df.columns) == ["value"]
    assert len(df) == 5
    assert list(df["value"]) == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_zarr_compatible_group_auto_read(tmp_path, logger):
    store = tmp_path / "group.zarr"
    _write_group_store(store)
    reader = zarrReader(str(store), logger)
    inv = reader.inventory()
    assert inv["type"] == INVENTORY_LEGACY
    assert inv["type"] not in USER_FACING_INVENTORY_TYPES

    df = reader.read()
    assert df is not None
    assert set(df.columns) == {"temp", "x"}
    assert len(df) == 4


def test_zarr_incompatible_root_needs_selection(tmp_path, logger):
    store = tmp_path / "bad.zarr"
    _write_incompatible_root_store(store)
    reader = zarrReader(str(store), logger)
    inv = reader.inventory()
    assert inv["type"] == INVENTORY_MULTI
    assert reader.read() is None

    df = zarrReader(str(store), logger, selected_keys=["short"]).read()
    assert df is not None
    assert list(df.columns) == ["short"]
    assert len(df) == 3


def test_zarr_grouped_hierarchical_selection(tmp_path, logger):
    store = tmp_path / "stations.zarr"
    _write_grouped_hierarchical_store(store)
    reader = zarrReader(str(store), logger)
    inv = reader.inventory()
    assert inv["type"] == INVENTORY_MULTI
    assert len(inv["groups"]) >= 2

    df = zarrReader(
        str(store), logger, selected_keys=["S1/X", "S1/Y"]
    ).read()
    assert df is not None
    assert set(df.columns) == {"X", "Y"}
    assert len(df) == 10


def test_zarr_get_metadata(tmp_path, logger):
    store = tmp_path / "meta.zarr"
    _write_group_store(store)
    meta = zarrReader(str(store), logger).get_metadata()
    assert meta["(root)"]["license"] == "MIT"
    assert meta["temp"]["unit"] == "C"


def test_zarr_read_file_integration(tmp_path):
    store = tmp_path / "cli.zarr"
    _write_single_array_store(store)
    df = read_file((str(store), "cli.zarr", ".zarr"))
    assert df is not None
    assert len(df) == 5


def test_zarr_empty_store(tmp_path, logger):
    store = tmp_path / "empty.zarr"
    zarr.open_group(str(store), mode="w")
    inv = zarrReader(str(store), logger).inventory()
    assert inv["type"] == INVENTORY_EMPTY
    assert zarrReader(str(store), logger).read() is None
