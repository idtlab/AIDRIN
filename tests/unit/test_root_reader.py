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


def _write_root(path, trees):
    """Write ``trees`` dict of {name: {branch: array}} to a ROOT file."""
    with uproot.recreate(str(path)) as handle:
        for name, branches in trees.items():
            handle[name] = branches


class TestRootReader:
    def test_registered_in_parser(self):
        assert ".root" in READER_MAP
        assert READER_MAP[".root"] is rootReader
        assert (".root", "ROOT") in SUPPORTED_FILE_TYPES

    def test_parse_lists_trees(self, tmp_path, logger):
        path = tmp_path / "multi.root"
        _write_root(
            path,
            {
                "events": {"x": np.arange(5), "y": np.arange(5) * 2},
                "meta": {"id": np.arange(3)},
            },
        )
        keys = rootReader(str(path), logger).parse()
        assert keys == ["events", "meta"]

    def test_read_single_tree_auto(self, tmp_path, logger):
        path = tmp_path / "one.root"
        _write_root(path, {"tree": {"x": np.array([1.0, 2.0]), "y": np.array([3.0, 4.0])}})
        df = rootReader(str(path), logger).read()
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["x", "y"]
        assert len(df) == 2

    def test_read_multi_tree_requires_selection(self, tmp_path, logger):
        path = tmp_path / "multi.root"
        _write_root(
            path,
            {
                "events": {"x": np.arange(5)},
                "meta": {"id": np.arange(3)},
            },
        )
        with pytest.raises(ValueError, match="multiple TTrees"):
            rootReader(str(path), logger).read()

    def test_read_with_selected_keys(self, tmp_path, logger):
        path = tmp_path / "multi.root"
        _write_root(
            path,
            {
                "events": {"x": np.arange(5), "y": np.arange(5)},
                "meta": {"id": np.arange(3)},
            },
        )
        df = rootReader(str(path), logger, selected_keys=["events"]).read()
        assert list(df.columns) == ["x", "y"]
        assert len(df) == 5

    def test_read_file_roundtrip(self, tmp_path):
        path = tmp_path / "sample.root"
        _write_root(path, {"tree": {"a": np.array([10, 20]), "b": np.array([1, 0])}})
        df = read_file((str(path), "sample.root", ".root"))
        assert isinstance(df, pd.DataFrame)
        assert list(df["a"]) == [10, 20]

    def test_read_file_with_embedded_selected_keys(self, tmp_path):
        path = tmp_path / "multi.root"
        _write_root(
            path,
            {
                "events": {"x": np.arange(4)},
                "meta": {"id": np.arange(2)},
            },
        )
        df = read_file((str(path), "multi.root", ".root", ["meta"]))
        assert list(df.columns) == ["id"]
        assert len(df) == 2

    def test_jagged_branches_are_dropped_with_disclosure(self, tmp_path, logger):
        """Regression test: jagged branches (variable-length per event, e.g.
        vector<float>) load as object columns of arrays and crash any metric
        that hashes cells (unhashable numpy.ndarray) — four readiness-report
        sections died this way on the shipped ATLAS sample. The reader must
        drop them, keep the scalar columns, and disclose the drop on df.attrs.
        """
        ak = pytest.importorskip("awkward")
        path = tmp_path / "jagged.root"
        with uproot.recreate(str(path)) as handle:
            handle["events"] = {
                "energy": np.array([10.0, 20.0, 30.0]),
                "lep_pt": ak.Array([[1.0, 2.0], [], [3.0, 4.0, 5.0]]),
            }
        df = rootReader(str(path), logger).read()
        assert list(df.columns) == ["energy"]
        assert df.attrs["dropped_jagged_columns"] == ["lep_pt"]
        # The surviving frame must be metric-safe: nunique() hashes cells.
        assert df["energy"].nunique() == 3

    def test_all_jagged_tree_raises_clear_error(self, tmp_path, logger):
        ak = pytest.importorskip("awkward")
        path = tmp_path / "alljagged.root"
        with uproot.recreate(str(path)) as handle:
            handle["events"] = {"lep_pt": ak.Array([[1.0], [2.0, 3.0]])}
        with pytest.raises(ValueError, match="only array-valued"):
            rootReader(str(path), logger).read()

    def test_summarize_dataset_discloses_dropped_columns(self, tmp_path):
        """The public API (CLI/MCP/remote all route through summarize_dataset)
        must disclose reader-level exclusions, not just shrink the shape."""
        ak = pytest.importorskip("awkward")
        from aidrin.headless.api import summarize_dataset

        path = tmp_path / "jagged.root"
        with uproot.recreate(str(path)) as handle:
            handle["events"] = {
                "energy": np.array([10.0, 20.0, 30.0]),
                "lep_pt": ak.Array([[1.0, 2.0], [], [3.0]]),
            }
        result = summarize_dataset(str(path))
        assert result["shape"]["columns"] == 1
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
