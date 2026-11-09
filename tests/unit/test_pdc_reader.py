"""Unit tests for the PDC (.pdc descriptor) reader.

Fakes stand in for PDCpy and the PDC server, so these run without either.
"""

import json
import logging
import os
import socket
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from aidrin.file_handling import file_parser
from aidrin.file_handling.file_parser import READER_MAP, ReaderReturnedNone, read_file
from aidrin.file_handling.readers import pdc_reader
from aidrin.file_handling.readers.pdc_reader import PDCError, load_descriptor, pdcReader

_log = logging.getLogger("test")


class FakeClient:
    """Stands in for PDCClient: objects maps name -> array, or (array, None) for a type PDCpy cannot read."""

    def __init__(self, objects, containers=("cont",)):
        self.objects = objects
        self.containers = set(containers)
        self.reads = []

    def check_container(self, name):
        if name not in self.containers:
            raise PDCError(f"PDC container '{name}' not found.")

    def _lookup(self, name):
        if name not in self.objects:
            raise PDCError(f"PDC object '{name}' not found.")
        value = self.objects[name]
        return (value, value.dtype) if isinstance(value, np.ndarray) else value

    def describe(self, name):
        arr, dtype = self._lookup(name)
        return tuple(arr.shape), dtype

    def read(self, name):
        arr, dtype = self._lookup(name)
        if dtype is None:
            raise PDCError(f"PDC object '{name}' has a data type PDCpy cannot read: unimplemented type")
        self.reads.append(name)
        return arr


def _write_descriptor(spec, directory=None) -> str:
    fd, path = tempfile.mkstemp(suffix=".pdc", dir=directory)
    with os.fdopen(fd, "w") as fh:
        if isinstance(spec, str):
            fh.write(spec)
        else:
            json.dump(spec, fh)
    return path


def _objects():
    n = 6
    return {
        "age": np.arange(20, 20 + n, dtype=np.int32),
        "income": np.linspace(1000.0, 2000.0, n),
        "score": (np.arange(n) / 2.0).astype(np.float32),
        "grid": np.arange(n * 3, dtype=float).reshape(n, 3),
        "cube": np.zeros((2, 2, 2)),
        "short": np.arange(3, dtype=np.int32),
        "flags": (np.zeros(n), None),
    }


class TestLoadDescriptor(unittest.TestCase):
    def _path(self, spec):
        path = _write_descriptor(spec)
        self.addCleanup(os.remove, path)
        return path

    def test_minimal(self):
        spec = load_descriptor(self._path({"objects": ["a", "b"]}))
        self.assertEqual(spec, {"objects": ["a", "b"], "container": None, "pdc_tmpdir": None})

    def test_relative_tmpdir_resolves_against_descriptor(self):
        path = self._path({"objects": ["a"], "pdc_tmpdir": "pdc_tmp"})
        spec = load_descriptor(path)
        self.assertEqual(spec["pdc_tmpdir"], os.path.join(os.path.dirname(path), "pdc_tmp"))

    def test_absolute_tmpdir_kept(self):
        spec = load_descriptor(self._path({"objects": ["a"], "pdc_tmpdir": "/scratch/pdc_tmp"}))
        self.assertEqual(spec["pdc_tmpdir"], "/scratch/pdc_tmp")

    def test_rejects_bad_descriptors(self):
        bad = [
            "not json",
            [],
            {},
            {"objects": []},
            {"objects": "age"},
            {"objects": ["age", ""]},
            {"objects": ["age", "age"]},
            {"objects": ["age"], "container": ""},
            {"objects": ["age"], "pdc_tmpdir": 3},
        ]
        for spec in bad:
            with self.subTest(spec=spec):
                with self.assertRaises(PDCError):
                    load_descriptor(self._path(spec))


class TestPdcReader(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(_objects())

    def _reader(self, objects, selected_keys=None, **extra):
        path = _write_descriptor({"objects": objects, **extra})
        self.addCleanup(os.remove, path)
        return pdcReader(path, _log, selected_keys=selected_keys, client=self.client)

    def test_equal_length_1d_objects_become_columns(self):
        df = self._reader(["age", "income", "score"]).read()
        self.assertEqual(list(df.columns), ["age", "income", "score"])
        self.assertEqual(len(df), 6)
        self.assertEqual(df["age"].dtype, np.int32)
        self.assertEqual(df["score"].dtype, np.float32)
        np.testing.assert_allclose(df["income"], np.linspace(1000.0, 2000.0, 6))

    def test_single_2d_object_splits_into_columns(self):
        df = self._reader(["grid"]).read()
        self.assertEqual(list(df.columns), ["grid_0", "grid_1", "grid_2"])
        self.assertEqual(df.shape, (6, 3))
        self.assertEqual(df.iloc[1].tolist(), [3.0, 4.0, 5.0])

    def test_selected_keys_subset(self):
        df = self._reader(["age", "income", "grid"], selected_keys="income, age").read()
        self.assertEqual(list(df.columns), ["income", "age"])
        self.assertNotIn("grid", self.client.reads)

    def test_selected_keys_must_be_in_descriptor(self):
        with self.assertRaisesRegex(PDCError, "not listed in the PDC descriptor: secret"):
            self._reader(["age"], selected_keys=["secret"]).read()

    def test_incompatible_objects_are_refused_before_reading(self):
        for objects in (["age", "short"], ["age", "grid"], ["cube"]):
            with self.subTest(objects=objects):
                self.client.reads.clear()
                with self.assertRaisesRegex(ReaderReturnedNone, "cannot form one table"):
                    self._reader(objects).read()
                self.assertEqual(self.client.reads, [])

    def test_missing_object_raises(self):
        with self.assertRaisesRegex(PDCError, "'nope' not found"):
            self._reader(["age", "nope"]).read()

    def test_unsupported_type_raises(self):
        with self.assertRaisesRegex(PDCError, "data type PDCpy cannot read"):
            self._reader(["flags"]).read()

    def test_inventory_layouts(self):
        cases = {
            ("age",): "single_dataset",
            ("age", "income", "score"): "legacy",
            ("age", "short"): "multi_dataset",
            ("age", "grid"): "multi_dataset",
        }
        for objects, layout in cases.items():
            with self.subTest(objects=objects):
                inv = self._reader(list(objects)).inventory()
                self.assertEqual(inv["type"], layout)
                self.assertEqual([d["path"] for d in inv["datasets"]], list(objects))

    def test_inventory_reports_shape_and_dtype(self):
        inv = self._reader(["grid", "flags"]).inventory()
        grid, flags = inv["datasets"]
        self.assertEqual((grid["shape"], grid["ndim"], grid["dtype"], grid["size"]), ((6, 3), 2, "float64", 18))
        self.assertEqual(flags["dtype"], "unsupported")
        self.assertEqual(self.client.reads, [])

    def test_parse_lists_descriptor_objects(self):
        self.assertEqual(self._reader(["age", "grid"]).parse(), ["age", "grid"])


class TestReadFileIntegration(unittest.TestCase):
    """The reader as wired into file_parser.read_file()."""

    def setUp(self):
        self.client = FakeClient(_objects())
        patcher = mock.patch.object(pdc_reader.PDCClient, "get", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = _write_descriptor({"objects": ["age", "income"], "container": "cont"})
        self.addCleanup(os.remove, self.path)

    def test_registered(self):
        self.assertIs(READER_MAP[".pdc"], pdcReader)
        self.assertIn(".pdc", file_parser._SELECTION_FILE_TYPES)
        self.assertNotIn(".pdc", [t for t, _ in file_parser.SUPPORTED_FILE_TYPES])

    def test_read_file_returns_frame(self):
        df = read_file((self.path, "data.pdc", ".pdc"))
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(list(df.columns), ["age", "income"])

    def test_read_file_passes_selected_keys(self):
        df = read_file((self.path, "data.pdc", ".pdc", ["income"]))
        self.assertEqual(list(df.columns), ["income"])

    def test_read_file_columns_argument(self):
        df = read_file((self.path, "data.pdc", ".pdc"), columns=["age"])
        self.assertEqual(list(df.columns), ["age"])

    def test_pdc_errors_reach_the_caller(self):
        self.client.containers = set()
        with self.assertRaisesRegex(PDCError, "container 'cont' not found"):
            read_file((self.path, "data.pdc", ".pdc"))

    def test_not_cached(self):
        read_file((self.path, "data.pdc", ".pdc"))
        prefix = os.path.basename(self.path) + "."
        sidecars = [f for f in os.listdir(os.path.dirname(self.path)) if f.startswith(prefix)]
        self.assertEqual(sidecars, [])


def _fake_pdcpy(ready=False):
    """A stand-in for the PDCpy ``pdc`` module."""
    fake = types.SimpleNamespace(PDCError=type("PDCError", (Exception,), {}))
    fake.ready = mock.Mock(return_value=ready)
    fake.init = mock.Mock()
    fake.main = types.SimpleNamespace(__file__="/nonexistent/pdc_main.so")
    return fake


class TestPDCClient(unittest.TestCase):
    def setUp(self):
        pdc_reader.PDCClient._instance = None
        self.addCleanup(setattr, pdc_reader.PDCClient, "_instance", None)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("PDC_TMPDIR", None)

    def test_missing_pdcpy_is_an_import_error_with_guidance(self):
        with mock.patch.dict(sys.modules, {"pdc": None}):
            with self.assertRaisesRegex(ImportError, "pip install PDCpy"):
                pdc_reader.PDCClient.get()

    def test_missing_server_cfg_refused_before_init(self):
        fake = _fake_pdcpy()
        tmp = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, tmp)
        with mock.patch.object(pdc_reader, "_require_pdcpy", return_value=fake):
            with self.assertRaisesRegex(PDCError, "No PDC server found"):
                pdc_reader.PDCClient.get(tmp)
        fake.init.assert_not_called()
        self.assertNotIn("PDC_TMPDIR", os.environ)
        self.assertIsNone(pdc_reader.PDCClient._instance)

    def test_init_once_with_tmpdir(self):
        fake = _fake_pdcpy()
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "server.cfg")
        open(cfg, "w").close()
        self.addCleanup(os.rmdir, tmp)
        self.addCleanup(os.remove, cfg)
        with mock.patch.object(pdc_reader, "_require_pdcpy", return_value=fake):
            first = pdc_reader.PDCClient.get(tmp)
            second = pdc_reader.PDCClient.get(tmp)
        self.assertIs(first, second)
        fake.init.assert_called_once()
        self.assertEqual(os.environ["PDC_TMPDIR"], tmp)

    def test_second_server_refused(self):
        fake = _fake_pdcpy(ready=True)
        with mock.patch.object(pdc_reader, "_require_pdcpy", return_value=fake):
            pdc_reader.PDCClient.get("/srv/a")
            with self.assertRaisesRegex(PDCError, "already connected"):
                pdc_reader.PDCClient.get("/srv/b")
        fake.init.assert_not_called()

    def test_init_failure_becomes_pdc_error(self):
        fake = _fake_pdcpy()
        fake.init.side_effect = fake.PDCError("Could not initialize PDC")
        with mock.patch.object(pdc_reader, "_require_pdcpy", return_value=fake):
            with self.assertRaisesRegex(PDCError, "Could not connect to a PDC server"):
                pdc_reader.PDCClient.get()


class TestConfigurePdcLogging(unittest.TestCase):
    def _configure(self, env):
        lib = mock.MagicMock()
        with mock.patch.object(pdc_reader.ctypes, "CDLL", return_value=lib), mock.patch.dict(os.environ, env):
            pdc_reader.configure_pdc_logging(_fake_pdcpy())
        return lib

    def test_logs_go_to_stderr_and_info_is_dropped(self):
        lib = self._configure({"PDC_DEBUG": "0"})
        self.assertEqual([c.args for c in lib.setLogFile.call_args_list], [(level, b"stderr") for level in range(4)])
        lib.setLogLevel.assert_called_once_with(1)  # LOG_LEVEL_WARNING

    def test_pdc_debug_keeps_info(self):
        lib = self._configure({"PDC_DEBUG": "1"})
        self.assertEqual(lib.setLogFile.call_count, 4)
        lib.setLogLevel.assert_not_called()

    def test_missing_library_is_ignored(self):
        with mock.patch.object(pdc_reader.ctypes, "CDLL", side_effect=OSError("no such file")):
            pdc_reader.configure_pdc_logging(_fake_pdcpy())


class TestCheckServer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def _cfg(self, address):
        with open(os.path.join(self.tmp, "server.cfg"), "w") as fh:
            fh.write(f"1\n{address}\n")

    def test_missing_cfg(self):
        with self.assertRaisesRegex(PDCError, "No PDC server found"):
            pdc_reader.check_server(self.tmp)

    def test_listening_server_passes(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            self._cfg(f"ofi+tcp;ofi_rxm://127.0.0.1:{listener.getsockname()[1]}")
            pdc_reader.check_server(self.tmp)

    def test_stale_cfg_is_refused(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self._cfg(f"ofi+tcp;ofi_rxm://127.0.0.1:{port}")
        with self.assertRaisesRegex(PDCError, f"No PDC server is listening at 127.0.0.1:{port}"):
            pdc_reader.check_server(self.tmp, timeout=1.0)

    def test_non_tcp_transport_not_probed(self):
        self._cfg("ofi+cxi://0x12345")
        pdc_reader.check_server(self.tmp)


if __name__ == "__main__":
    unittest.main()
