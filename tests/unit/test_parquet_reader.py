"""Unit tests for parquetReader.

These tests run without Flask, Celery, or Redis. Parquet I/O requires a
pandas engine (pyarrow), which AIDRIN declares as a dependency.
"""

import logging
import os
import tempfile

import pandas as pd

from aidrin.file_handling.readers.parquet_reader import parquetReader
from aidrin.file_handling.file_parser import (
    READER_MAP,
    SUPPORTED_FILE_TYPES,
    read_file,
)

_log = logging.getLogger("test")


def _write_parquet(df: pd.DataFrame) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    tmp.close()
    df.to_parquet(tmp.name)
    return tmp.name


def _clean(path):
    try:
        os.unlink(path)
    except OSError:
        pass


class TestParquetReaderRead:

    def test_reads_columns_and_rows(self):
        path = _write_parquet(pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}))
        try:
            df = parquetReader(path, _log).read()
        finally:
            _clean(path)

        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 3
        assert df["a"].tolist() == [1, 2, 3]

    def test_preserves_dtypes_and_strings(self):
        original = pd.DataFrame({"name": ["Alice", "Bob"], "score": [95.5, 88.0]})
        path = _write_parquet(original)
        try:
            df = parquetReader(path, _log).read()
        finally:
            _clean(path)

        assert df["name"].tolist() == ["Alice", "Bob"]
        assert df["score"].iloc[0] == 95.5

    def test_empty_dataframe(self):
        path = _write_parquet(pd.DataFrame({"a": []}))
        try:
            df = parquetReader(path, _log).read()
        finally:
            _clean(path)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_missing_file_raises(self):
        try:
            parquetReader("/nonexistent/path/file.parquet", _log).read()
            raised = False
        except Exception:
            raised = True
        assert raised


class TestParquetRegistration:

    def test_parquet_registered_in_reader_map(self):
        assert ".parquet" in READER_MAP
        assert READER_MAP[".parquet"] is parquetReader

    def test_parquet_listed_as_supported_type(self):
        extensions = [ext for ext, _label in SUPPORTED_FILE_TYPES]
        assert ".parquet" in extensions

    def test_read_file_dispatches_parquet(self):
        path = _write_parquet(pd.DataFrame({"x": [1, 2], "y": [3, 4]}))
        try:
            df = read_file((path, "data.parquet", ".parquet"))
        finally:
            _clean(path)

        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["x", "y"]
        assert len(df) == 2
