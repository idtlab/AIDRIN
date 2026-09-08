"""Unit tests for structured reader scaffold and Zarr reader."""

import logging

import numpy as np
import pytest

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
    assert set(df.columns) == {"temp", "station/x"}
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
    assert set(df.columns) == {"S1/X", "S1/Y"}
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


def _write_multidim_store(path):
    """3D array shaped like (time, lat, lon) — not tabular without aggregation."""
    root = zarr.open_group(str(path), mode="w")
    data = np.zeros((5, 4, 3), dtype=np.float64)
    for t in range(5):
        data[t, :, :] = float(t)
    arr = root.create_array("tmax_grid", shape=data.shape, dtype="f8")
    arr[:] = data


def test_zarr_multidim_refused(tmp_path, logger):
    """ndim >= 3 must not be averaged or flattened for metrics."""
    store = tmp_path / "grid.zarr"
    _write_multidim_store(store)
    df = zarrReader(str(store), logger, selected_keys=["tmax_grid"]).read()
    assert df is None


def test_zarr_read_file_selected_keys(tmp_path):
    store = tmp_path / "pick.zarr"
    _write_grouped_hierarchical_store(store)
    df = read_file((str(store), "pick.zarr", ".zarr", ["S1/X", "S1/Y"]))
    assert df is not None
    assert list(df.columns) == ["S1/X", "S1/Y"]
    assert len(df) == 10


# ---------------------------------------------------------------------------
# Regression tests for review findings
# ---------------------------------------------------------------------------


def test_zarr_missing_dependency_surfaces_install_hint(tmp_path, logger, monkeypatch):
    """A missing 'zarr' package must not be reported as an empty store."""
    import aidrin.file_handling.readers.zarr_reader as zr

    def _no_zarr():
        raise ImportError("Zarr support requires the 'zarr' package on Python >=3.11.")

    monkeypatch.setattr(zr, "_require_zarr", _no_zarr)

    store = tmp_path / "any.zarr"
    store.mkdir()
    with pytest.raises(ImportError, match="requires the 'zarr' package"):
        zr.zarrReader(str(store), logger).inventory()
    with pytest.raises(ImportError, match="requires the 'zarr' package"):
        zr.zarrReader(str(store), logger).read()


def test_zarr_multidim_refused_without_loading_data(tmp_path, logger):
    """The ndim guard must read metadata only — a real grid would not fit in RAM."""
    store = tmp_path / "grid.zarr"
    _write_multidim_store(store)

    reader = zarrReader(str(store), logger, selected_keys=["tmax_grid"])
    root = reader._open_store()
    arr = root["tmax_grid"]

    class _NoRead:
        """Proxy exposing metadata but exploding on any element access."""

        ndim = arr.ndim
        shape = arr.shape

        def __getitem__(self, item):
            raise AssertionError("array data was materialized before the ndim check")

    assert reader._prepare_array_data(_NoRead()) is None


def test_zarr_column_order_is_deterministic(tmp_path, logger):
    """Store iteration order varies between runs; column order must not."""
    store = tmp_path / "order.zarr"
    root = zarr.open_group(str(store), mode="w")
    for name in ("score", "age", "income", "bmi"):
        root.create_array(name, shape=(6,), dtype="f8")[:] = np.arange(6, dtype="f8")

    columns = list(zarrReader(str(store), logger).read().columns)
    assert columns == sorted(columns)
    for _ in range(3):
        assert list(zarrReader(str(store), logger).read().columns) == columns
    assert [ds["path"] for ds in zarrReader(str(store), logger).inventory()["datasets"]] == columns


def test_zarr_mixed_dimension_root_needs_selection(tmp_path, logger):
    """A layout read() cannot auto-merge must not be labelled auto-readable."""
    store = tmp_path / "mixed.zarr"
    root = zarr.open_group(str(store), mode="w")
    root.create_array("x", shape=(100,), dtype="f8")[:] = np.arange(100, dtype="f8")
    root.create_array("img", shape=(10, 10), dtype="f8")[:] = np.zeros((10, 10))

    inv = zarrReader(str(store), logger).inventory()
    assert inv["type"] == INVENTORY_MULTI
    assert zarrReader(str(store), logger).read() is None

    df = zarrReader(str(store), logger, selected_keys=["x"]).read()
    assert list(df.columns) == ["x"]


def test_zarr_scalar_array_reads_as_single_row(tmp_path, logger):
    """0D arrays are documented as supported; arr[:] raises IndexError on them."""
    store = tmp_path / "scalar.zarr"
    root = zarr.open_group(str(store), mode="w")
    root.create_array("s", shape=(), dtype="f8")[...] = 3.5

    df = zarrReader(str(store), logger).read()
    assert df is not None
    assert len(df) == 1
    assert df.iloc[0, 0] == 3.5


def test_zarr_ignores_unrelated_flask_session_keys(tmp_path, logger):
    """There is no Zarr key picker, so session keys can only come from another file."""
    import flask

    store = tmp_path / "flat.zarr"
    root = zarr.open_group(str(store), mode="w")
    for name in ("a", "b"):
        root.create_array(name, shape=(5,), dtype="f8")[:] = np.arange(5, dtype="f8")

    app = flask.Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context("/"):
        flask.session["selected_keys"] = ["group/from_a_previous_hdf5_file"]
        reader = zarrReader(str(store), logger)
        assert reader._get_selected_dataset_keys() == []
        # Falls through to the compatible-layout auto-read, not a failed lookup.
        assert list(reader.read().columns) == ["a", "b"]


def test_read_file_returns_none_for_non_zarr_empty_read(tmp_path):
    """Only Zarr raises; other formats keep returning None, not a message string."""
    h5py = pytest.importorskip("h5py")
    path = tmp_path / "ragged.h5"
    with h5py.File(str(path), "w") as handle:
        handle.create_dataset("a", data=np.arange(10))
        handle.create_dataset("b", data=np.arange(7))

    assert read_file((str(path), "ragged.h5", ".h5")) is None


def test_read_file_raises_for_zarr_needing_selection(tmp_path):
    from aidrin.file_handling.file_parser import ReaderReturnedNone

    store = tmp_path / "ragged.zarr"
    root = zarr.open_group(str(store), mode="w")
    root.create_array("a", shape=(10,), dtype="i4")[:] = np.arange(10)
    root.create_array("b", shape=(7,), dtype="i4")[:] = np.arange(7)

    with pytest.raises(ReaderReturnedNone):
        read_file((str(store), "ragged.zarr", ".zarr"))
