"""Unit tests for the parse-once frame cache in ``aidrin.file_handling.file_parser``.

The cache materialises an uploaded file into an on-disk Arrow/Feather artifact the
first time ``read_file`` is called, so repeated metric tasks reload the frame
cheaply instead of re-parsing the source.  Only dtype-stable formats (csv, parquet,
excel) are cached; json/npz/hdf5 build object/list columns that Feather would alter,
so they are never cached.  These tests run without Flask, Celery, or Redis.
"""

import glob
import logging
import os
import stat
import tempfile
import unittest

import pandas as pd

from aidrin.file_handling import file_parser
from aidrin.file_handling.readers.base_reader import BaseFileReader
from aidrin.file_handling.readers.csv_reader import csvReader

_log = logging.getLogger("test")


def _write_csv(text):
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    tmp.write(text)
    tmp.close()
    return tmp.name


def _clean(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass


class _CountingCsvReader(csvReader):
    """Cacheable (.csv) reader that records how often the source is parsed."""

    calls = 0

    def read(self):
        type(self).calls += 1
        return super().read()


class _CountingJsonReader(BaseFileReader):
    """Non-cacheable (.json) reader returning a fixed frame, counting parses."""

    calls = 0

    def read(self):
        type(self).calls += 1
        return pd.DataFrame({"a": [1, 2], "b": [3, 4]})


class FrameCacheTestCase(unittest.TestCase):
    def setUp(self):
        _CountingCsvReader.calls = 0
        _CountingJsonReader.calls = 0
        self._orig_map = dict(file_parser.READER_MAP)
        file_parser.READER_MAP[".csv"] = _CountingCsvReader
        file_parser.READER_MAP[".json"] = _CountingJsonReader
        self._sources = []

    def tearDown(self):
        file_parser.READER_MAP.clear()
        file_parser.READER_MAP.update(self._orig_map)
        for src in self._sources:
            _clean(src, *glob.glob(src + "*" + file_parser._FRAME_CACHE_SUFFIX))

    def _track(self, path):
        self._sources.append(path)
        return path

    def _sidecars(self, path):
        return glob.glob(path + "*" + file_parser._FRAME_CACHE_SUFFIX)

    # -- transparency ------------------------------------------------------

    def test_returns_same_data_as_direct_reader(self):
        path = self._track(_write_csv("a,b\n1,2\n3,4\n"))
        expected = csvReader(path, _log).read()
        got = file_parser.read_file((path, "f.csv", ".csv"))
        pd.testing.assert_frame_equal(got, expected)

    def test_cached_hit_equals_direct_reader(self):
        # second call comes from Feather; must still equal the raw reader output
        path = self._track(_write_csv("a,b\n1,2\n3,4\n"))
        expected = csvReader(path, _log).read()
        file_parser.read_file((path, "f.csv", ".csv"))  # build
        got = file_parser.read_file((path, "f.csv", ".csv"))  # hit
        pd.testing.assert_frame_equal(got, expected)

    # -- parse once (cacheable format) -------------------------------------

    def test_cacheable_source_parsed_only_once(self):
        path = self._track(_write_csv("a,b\n1,2\n3,4\n"))
        info = (path, "f.csv", ".csv")
        file_parser.read_file(info)
        file_parser.read_file(info)
        file_parser.read_file(info)
        self.assertEqual(_CountingCsvReader.calls, 1)
        self.assertEqual(len(self._sidecars(path)), 1)

    # -- non-cacheable format is never cached ------------------------------

    def test_noncacheable_format_not_cached(self):
        path = self._track(_write_csv("ignored"))  # content irrelevant; reader is fake
        info = (path, "f.json", ".json")
        file_parser.read_file(info)
        file_parser.read_file(info)
        # re-parsed every call, and no sidecar written
        self.assertEqual(_CountingJsonReader.calls, 2)
        self.assertEqual(self._sidecars(path), [])

    # -- invalidation ------------------------------------------------------

    def test_cache_rebuilt_when_source_changes(self):
        path = self._track(_write_csv("a,b\n1,2\n"))
        info = (path, "f.csv", ".csv")
        first = file_parser.read_file(info)
        self.assertEqual(first["a"].tolist(), [1])

        with open(path, "w") as fh:
            fh.write("a,b\n9,9\n")

        second = file_parser.read_file(info)
        self.assertEqual(second["a"].tolist(), [9])
        self.assertEqual(_CountingCsvReader.calls, 2)

    # -- column projection -------------------------------------------------

    def test_column_projection_returns_subset(self):
        path = self._track(_write_csv("a,b,c\n1,2,3\n4,5,6\n"))
        got = file_parser.read_file((path, "f.csv", ".csv"), columns=["a", "c"])
        self.assertEqual(list(got.columns), ["a", "c"])
        self.assertEqual(got["a"].tolist(), [1, 4])
        self.assertEqual(got["c"].tolist(), [3, 6])

    def test_projection_still_parses_source_only_once(self):
        path = self._track(_write_csv("a,b,c\n1,2,3\n4,5,6\n"))
        info = (path, "f.csv", ".csv")
        file_parser.read_file(info)
        file_parser.read_file(info, columns=["b"])
        self.assertEqual(_CountingCsvReader.calls, 1)

    # -- graceful degradation: unwritable cache dir ------------------------

    def test_unwritable_dir_falls_back_to_parsed_frame(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "data.csv")
        with open(path, "w") as fh:
            fh.write("a,b\n1,2\n3,4\n")
        file_parser.READER_MAP[".csv"] = csvReader  # real reader; just need a frame
        os.chmod(d, stat.S_IRUSR | stat.S_IXUSR)  # read+exec, no write
        try:
            got = file_parser.read_file((path, "data.csv", ".csv"))
            self.assertIsInstance(got, pd.DataFrame)
            self.assertEqual(got["a"].tolist(), [1, 3])
        finally:
            os.chmod(d, stat.S_IRWXU)
            _clean(path, *glob.glob(path + "*" + file_parser._FRAME_CACHE_SUFFIX))
            os.rmdir(d)

    # -- regression: existing error/edge behavior --------------------------

    def test_unsupported_file_type_returns_none(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xyz", delete=False, mode="w")
        tmp.write("junk")
        tmp.close()
        self._track(tmp.name)
        self.assertIsNone(file_parser.read_file((tmp.name, "x.xyz", ".xyz")))

    def test_missing_file_returns_error_string(self):
        result = file_parser.read_file(("/nonexistent/path/file.csv", "f.csv", ".csv"))
        self.assertIsInstance(result, str)
        self.assertIn("not found", result.lower())


if __name__ == "__main__":
    unittest.main()
