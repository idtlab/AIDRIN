"""Unit tests for the ROOT TTree reader."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from aidrin.file_handling.file_parser import READER_MAP, SUPPORTED_FILE_TYPES, read_file
from aidrin.file_handling.readers.root_reader import rootReader

uproot = pytest.importorskip("uproot")
np = pytest.importorskip("numpy")


@pytest.fixture
def logger():
    return logging.getLogger("test_root_reader")


def _branch_type(array):
    """``mktree`` branch spec for a numpy (flat) or awkward (jagged) array."""
    dtype = getattr(array, "dtype", None)
    if isinstance(dtype, np.dtype):
        return dtype
    import awkward as ak

    # "3 * var * float32" -> "var * float32"
    return str(ak.type(array)).split(" * ", 1)[1]


@pytest.fixture(params=["rntuple", "ttree"])
def write_root(request):
    """Write ``{tree: {branch: array}}`` as an RNTuple and as a real TTree.

    ``handle[name] = {...}`` writes an RNTuple, not a TTree, so tests built on
    that form alone never reach uproot's TTree code path -- where jagged
    branches are routed through the optional awkward-pandas stack and a plain
    ``tree.arrays()`` fails the whole read. Every write asserts the container
    it actually produced, so the coverage cannot silently rot back to one
    format.
    """
    kind = request.param

    def write(path, trees):
        with uproot.recreate(str(path)) as handle:
            for name, branches in trees.items():
                if kind == "ttree":
                    handle.mktree(
                        name, {b: _branch_type(a) for b, a in branches.items()}
                    )
                    handle[name].extend(branches)
                else:
                    handle[name] = branches
        expected = "TTree" if kind == "ttree" else "ROOT::RNTuple"
        with uproot.open(str(path)) as handle:
            assert set(handle.classnames().values()) == {expected}

    return write


class TestRootReader:
    def test_registered_in_parser(self):
        assert ".root" in READER_MAP
        assert READER_MAP[".root"] is rootReader
        assert (".root", "ROOT") in SUPPORTED_FILE_TYPES

    def test_parse_lists_trees(self, tmp_path, logger, write_root):
        path = tmp_path / "multi.root"
        write_root(
            path,
            {
                "events": {"x": np.arange(5), "y": np.arange(5) * 2},
                "meta": {"id": np.arange(3)},
            },
        )
        keys = rootReader(str(path), logger).parse()
        assert keys == ["events", "meta"]

    def test_read_single_tree_auto(self, tmp_path, logger, write_root):
        path = tmp_path / "one.root"
        write_root(path, {"tree": {"x": np.array([1.0, 2.0]), "y": np.array([3.0, 4.0])}})
        df = rootReader(str(path), logger).read()
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["x", "y"]
        assert len(df) == 2

    def test_read_multi_tree_needs_selection(self, tmp_path, logger, write_root):
        """An ambiguous file must reach the caller as the layout-aware "pick a
        tree" error, the way HDF5 and Zarr do. Raising ValueError here instead
        left ``read_file``'s blanket handler to flatten it into "Unable to read
        the uploaded file", which names neither the trees nor the fix.
        """
        from aidrin.file_handling.file_parser import ReaderReturnedNone

        path = tmp_path / "multi.root"
        write_root(
            path,
            {
                "events": {"x": np.arange(5)},
                "meta": {"id": np.arange(3)},
            },
        )
        assert rootReader(str(path), logger).read() is None
        with pytest.raises(ReaderReturnedNone) as excinfo:
            read_file((str(path), "multi.root", ".root"))
        message = str(excinfo.value)
        assert "multi_dataset" in message
        assert "--selected-keys" in message

    def test_read_with_selected_keys(self, tmp_path, logger, write_root):
        path = tmp_path / "multi.root"
        write_root(
            path,
            {
                "events": {"x": np.arange(5), "y": np.arange(5)},
                "meta": {"id": np.arange(3)},
            },
        )
        df = rootReader(str(path), logger, selected_keys=["events"]).read()
        assert list(df.columns) == ["x", "y"]
        assert len(df) == 5

    def test_read_file_roundtrip(self, tmp_path, write_root):
        path = tmp_path / "sample.root"
        write_root(path, {"tree": {"a": np.array([10, 20]), "b": np.array([1, 0])}})
        df = read_file((str(path), "sample.root", ".root"))
        assert isinstance(df, pd.DataFrame)
        assert list(df["a"]) == [10, 20]

    def test_read_file_with_embedded_selected_keys(self, tmp_path, write_root):
        path = tmp_path / "multi.root"
        write_root(
            path,
            {
                "events": {"x": np.arange(4)},
                "meta": {"id": np.arange(2)},
            },
        )
        df = read_file((str(path), "multi.root", ".root", ["meta"]))
        assert list(df.columns) == ["id"]
        assert len(df) == 2

    def test_jagged_branches_are_dropped_with_disclosure(self, tmp_path, logger, write_root):
        """Regression test: jagged branches (variable-length per event, e.g.
        vector<float>) load as object columns of arrays and crash any metric
        that hashes cells (unhashable numpy.ndarray) -- four readiness-report
        sections died this way on the shipped ATLAS sample. On a TTree they are
        worse than that: converting them needs the optional awkward-pandas
        package, so asking for the whole tree fails the read outright. The
        reader must leave them out, keep the scalar columns, and disclose the
        drop on df.attrs.
        """
        ak = pytest.importorskip("awkward")
        path = tmp_path / "jagged.root"
        write_root(
            path,
            {
                "events": {
                    "energy": np.array([10.0, 20.0, 30.0]),
                    "lep_pt": ak.Array([[1.0, 2.0], [], [3.0, 4.0, 5.0]]),
                }
            },
        )
        df = rootReader(str(path), logger).read()
        # A TTree also carries uproot's generated counter branch (nlep_pt), so
        # assert on the branches under test rather than the exact column list.
        assert "lep_pt" not in df.columns
        assert "energy" in df.columns
        assert df.attrs["dropped_jagged_columns"] == ["lep_pt"]
        assert len(df) == 3
        # The surviving frame must be metric-safe: nunique() hashes cells.
        assert df["energy"].nunique() == 3

    def test_all_jagged_tree_raises_clear_error(self, tmp_path, logger):
        # RNTuple only: mktree always adds a scalar counter branch alongside a
        # variable-length one, so a TTree is never wholly array-valued.
        ak = pytest.importorskip("awkward")
        path = tmp_path / "alljagged.root"
        with uproot.recreate(str(path)) as handle:
            handle["events"] = {"lep_pt": ak.Array([[1.0], [2.0, 3.0]])}
        with pytest.raises(ValueError, match="only array-valued"):
            rootReader(str(path), logger).read()

    def test_summarize_dataset_discloses_dropped_columns(self, tmp_path, write_root):
        """The public API (CLI/MCP/remote all route through summarize_dataset)
        must disclose reader-level exclusions, not just shrink the shape."""
        ak = pytest.importorskip("awkward")
        from aidrin.headless.api import summarize_dataset

        path = tmp_path / "jagged.root"
        write_root(
            path,
            {
                "events": {
                    "energy": np.array([10.0, 20.0, 30.0]),
                    "lep_pt": ak.Array([[1.0, 2.0], [], [3.0]]),
                }
            },
        )
        result = summarize_dataset(str(path))
        assert "lep_pt" not in result["columns"]
        assert result["dropped_columns"]["columns"] == ["lep_pt"]
        assert result["dropped_columns"]["reason"]


def test_sample_root_if_present():
    from pathlib import Path

    sample = Path("examples/sample_data/root/sample.root")
    if not sample.exists():
        pytest.skip("sample.root not present")
    df = read_file((str(sample), "sample.root", ".root"))
    assert isinstance(df, pd.DataFrame)
    assert set(df.columns) >= {"x", "y"}
