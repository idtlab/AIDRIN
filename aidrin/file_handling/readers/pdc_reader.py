"""Proactive Data Containers (PDC) reader.

PDC (https://github.com/hpc-io/pdc) is a high-performance, object-centric data
management framework for moving data across memory and storage systems. Its data
lives in objects on a running PDC server, not in files, so AIDRIN reads it
through a small JSON *descriptor* file with the ``.pdc`` extension that names
the objects to load::

    {
        "objects": ["age", "income", "score"],
        "container": "census",
        "pdc_tmpdir": "/path/to/pdc_tmp"
    }

``objects`` is required: the PDC client API cannot list the objects a server
holds, only the ones the current process opened. ``container`` is optional and
only checked for existence. ``pdc_tmpdir`` is optional and points at the
directory holding the server's ``server.cfg`` (the same ``PDC_TMPDIR`` the
server was started with); a relative path is resolved against the descriptor's
directory. When omitted, the ``PDC_TMPDIR`` environment variable is used, and
when that is unset too, PDC's own default ``./pdc_tmp``.

Objects are read with PDCpy (https://github.com/hpc-io/PDCpy), PDC's official
Python interface, which has to be built against the same PDC installation the
server runs.

Objects map to DataFrame columns with the same rules as the Zarr reader: one
object of up to 2 dimensions, or several 1D objects of equal length. Objects of
3 or more dimensions are refused rather than flattened. ``selected_keys`` picks
which of the descriptor's objects to read.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import socket
import threading
from typing import Any

import numpy as np
import pandas as pd

from aidrin.file_handling.readers.structured import (
    INVENTORY_EMPTY,
    INVENTORY_LEGACY,
    INVENTORY_MULTI,
    INVENTORY_SINGLE,
    DatasetEntry,
    InventoryResult,
    StructuredFileReader,
    make_inventory,
)


_log = logging.getLogger(__name__)

# The PDC client falls back to this when PDC_TMPDIR is unset (pdc_client_connect.c).
DEFAULT_PDC_TMPDIR = "pdc_tmp"


class PDCError(RuntimeError):
    """A PDC descriptor, connection, or object read failed."""


def _require_pdcpy():
    try:
        import pdc
    except ImportError as exc:
        raise ImportError(
            "PDC support requires PDCpy (https://github.com/hpc-io/PDCpy), built against your PDC "
            "installation: set PDC_DIR and MERCURY_DIR, put PDC's lib directory on LD_LIBRARY_PATH, "
            "then run: pip install PDCpy"
        ) from exc
    return pdc


def load_descriptor(path: str) -> dict[str, Any]:
    """Parse and validate a ``.pdc`` descriptor file."""
    try:
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)
    except json.JSONDecodeError as exc:
        raise PDCError(f"PDC descriptor '{path}' is not valid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise PDCError(f"PDC descriptor '{path}' must be a JSON object.")

    objects = spec.get("objects")
    if not isinstance(objects, list) or not objects or not all(isinstance(o, str) and o for o in objects):
        raise PDCError(f"PDC descriptor '{path}' needs \"objects\": a non-empty list of object names.")
    if len(set(objects)) != len(objects):
        raise PDCError(f"PDC descriptor '{path}' lists an object more than once.")

    container = spec.get("container")
    if container is not None and (not isinstance(container, str) or not container):
        raise PDCError(f"PDC descriptor '{path}': \"container\" must be a non-empty string.")

    tmpdir = spec.get("pdc_tmpdir")
    if tmpdir is not None:
        if not isinstance(tmpdir, str) or not tmpdir:
            raise PDCError(f"PDC descriptor '{path}': \"pdc_tmpdir\" must be a non-empty string.")
        if not os.path.isabs(tmpdir):
            tmpdir = os.path.join(os.path.dirname(os.path.abspath(path)), tmpdir)
        tmpdir = os.path.normpath(tmpdir)

    return {"objects": list(objects), "container": container, "pdc_tmpdir": tmpdir}


def resolve_tmpdir(tmpdir: str | None) -> tuple[str, str]:
    """Return ``(absolute path, where it came from)`` for the server's PDC_TMPDIR.

    Precedence matches the PDC client: the descriptor's ``pdc_tmpdir``, then
    ``PDC_TMPDIR``, then PDC's default ``./pdc_tmp`` under the working directory.
    """
    if tmpdir:
        source = '"pdc_tmpdir" in the descriptor'
    elif os.environ.get("PDC_TMPDIR"):
        tmpdir, source = os.environ["PDC_TMPDIR"], "PDC_TMPDIR"
    else:
        tmpdir = DEFAULT_PDC_TMPDIR
        source = 'PDC\'s default ./pdc_tmp, since neither "pdc_tmpdir" in the descriptor nor PDC_TMPDIR is set'
    return os.path.normpath(os.path.abspath(tmpdir)), source


_TCP_ADDRESS = re.compile(r"^(?P<transport>[^:]+)://\[?(?P<host>[^\]/]+?)\]?:(?P<port>\d+)$")


def check_server(tmpdir: str, timeout: float = 2.0, source: str | None = None) -> None:
    """Raise PDCError unless a PDC server looks reachable through ``tmpdir``.

    ``pdc.init()`` blocks and then kills the process when no server answers, so
    this runs first. It needs ``server.cfg`` (a server count, then one address
    per line) and, for TCP-based transports, connects to the first address; a
    leftover ``server.cfg`` from a stopped server fails here instead of in
    ``pdc.init()``. Other transports (e.g. ``ofi+cxi``) are not probed.
    ``source`` says where ``tmpdir`` came from, for the error message.
    """
    cfg = os.path.join(tmpdir, "server.cfg")
    try:
        with open(cfg, encoding="utf-8") as fh:
            lines = [line.strip() for line in fh if line.strip()]
    except OSError:
        origin = f" (from {source})" if source else ""
        raise PDCError(
            f"No PDC server found: '{cfg}'{origin} does not exist. Start pdc_server with this "
            "PDC_TMPDIR, or point \"pdc_tmpdir\" in the descriptor or the PDC_TMPDIR environment "
            "variable at the server's directory."
        ) from None
    match = _TCP_ADDRESS.match(lines[1]) if len(lines) > 1 else None
    if not match or not any(t in match["transport"] for t in ("tcp", "sockets")):
        return
    host, port = match["host"], int(match["port"])
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        raise PDCError(
            f"No PDC server is listening at {host}:{port} (from '{cfg}'): {exc}. "
            "The server may have stopped and left server.cfg behind."
        ) from None


# PDC_LogLevel (pdc_logger.h)
_LOG_LEVEL_WARNING = 1
_LOG_LEVELS = range(4)  # LOG_LEVEL_ERROR .. LOG_LEVEL_DEBUG


def _pdc_debug_enabled() -> bool:
    try:
        return int(os.environ.get("PDC_DEBUG", "0")) != 0
    except ValueError:
        return False


def configure_pdc_logging(pdc):
    """Route PDC's C logging to stderr and, unless ``PDC_DEBUG`` is set, drop its INFO lines.

    The PDC C library logs every level to stdout by default, which would mix
    with AIDRIN's JSON output, and prints INFO lines on every object access.
    PDCpy does not expose the logger, so call ``setLogFile`` and
    ``setLogLevel`` (pdc_logger.h) through the already-loaded PDCpy
    extension, whose dependencies include libpdc. Warnings and errors are
    kept; set ``PDC_DEBUG=1`` to see everything. Call before ``pdc.init()``.
    Older PDC releases lack these functions; logging is then left alone and a
    warning says so, since PDC's INFO lines will then land on stdout.
    """
    try:
        lib = ctypes.CDLL(pdc.main.__file__)
    except (AttributeError, OSError) as exc:
        _log.warning("Could not load the PDC library to redirect its logging (%s); PDC may log to stdout.", exc)
        return
    missing = [name for name in ("setLogFile", "setLogLevel") if not hasattr(lib, name)]
    if missing:
        _log.warning(
            "This PDC build lacks %s, so its logging stays on stdout and INFO lines are not filtered.",
            " and ".join(missing),
        )
        return
    set_log_file, set_log_level = lib.setLogFile, lib.setLogLevel
    set_log_file.restype = None
    set_log_file.argtypes = [ctypes.c_int, ctypes.c_char_p]
    for level in _LOG_LEVELS:
        set_log_file(level, b"stderr")
    if not _pdc_debug_enabled():
        set_log_level.restype = None
        set_log_level.argtypes = [ctypes.c_int]
        set_log_level(_LOG_LEVEL_WARNING)


class PDCClient:
    """Process-wide PDC connection through PDCpy.

    PDCpy initializes PDC once per process and closes it at exit, and AIDRIN
    calls ``read_file()`` once per metric, so every reader shares this client.
    """

    _instance: PDCClient | None = None
    _lock = threading.Lock()

    def __init__(self, pdc, tmpdir: str):
        self._pdc = pdc
        self.tmpdir = tmpdir

    @classmethod
    def get(cls, tmpdir: str | None = None) -> PDCClient:
        requested, source = resolve_tmpdir(tmpdir)
        with cls._lock:
            if cls._instance is not None:
                active = cls._instance.tmpdir
                if requested != active:
                    raise PDCError(
                        f"This process is already connected to the PDC server in '{active}'; "
                        f"cannot also connect to '{requested}' (from {source})."
                    )
                return cls._instance

            pdc = _require_pdcpy()
            if not pdc.ready():
                check_server(requested, source=source)
                # The client library reads PDC_TMPDIR at init to find server.cfg.
                os.environ["PDC_TMPDIR"] = requested
                configure_pdc_logging(pdc)
                try:
                    pdc.init()
                except pdc.PDCError as exc:
                    raise PDCError(f"Could not connect to a PDC server: {exc}") from exc
            cls._instance = cls(pdc, requested)
            return cls._instance

    def check_container(self, name: str):
        try:
            self._pdc.Container.get(name)
        except self._pdc.PDCError as exc:
            raise PDCError(f"PDC container '{name}' not found.") from exc

    def _object(self, name: str):
        try:
            return self._pdc.Object.get(name)
        except self._pdc.PDCError as exc:
            raise PDCError(f"PDC object '{name}' not found.") from exc

    def describe(self, name: str) -> tuple[tuple[int, ...], np.dtype | None]:
        """Return ``(shape, dtype)`` for an object; ``dtype`` is None for types PDCpy cannot map."""
        obj = self._object(name)
        shape = tuple(int(d) for d in obj.dims)
        try:
            dtype = obj.type.as_numpy_type()
        except (self._pdc.PDCError, ValueError):
            dtype = None
        return shape, dtype

    def read(self, name: str) -> np.ndarray:
        """Read a whole object into a NumPy array."""
        obj = self._object(name)
        try:
            obj.type.as_numpy_type()
        except (self._pdc.PDCError, ValueError) as exc:
            raise PDCError(f"PDC object '{name}' has a data type PDCpy cannot read: {exc}") from exc
        try:
            return np.asarray(obj.get_data().wait())
        except self._pdc.PDCError as exc:
            raise PDCError(f"Reading PDC object '{name}' failed: {exc}") from exc


class pdcReader(StructuredFileReader):
    """Read objects from a running PDC server, named by a ``.pdc`` descriptor."""

    def __init__(self, file_path: str, logger, selected_keys=None, client=None):
        super().__init__(file_path, logger)
        self._explicit_selected_keys = selected_keys
        self._client = client
        self._spec = None

    def _descriptor(self):
        if self._spec is None:
            self._spec = load_descriptor(self.file_path)
        return self._spec

    def _connect(self):
        if self._client is None:
            spec = self._descriptor()
            self._client = PDCClient.get(spec["pdc_tmpdir"])
            if spec["container"]:
                self._client.check_container(spec["container"])
        return self._client

    def _list_datasets(self) -> list[DatasetEntry]:
        client = self._connect()
        datasets: list[DatasetEntry] = []
        for name in self._descriptor()["objects"]:
            shape, dtype = client.describe(name)
            datasets.append(
                {
                    "path": name,
                    "shape": shape,
                    "ndim": len(shape),
                    "dtype": str(dtype) if dtype is not None else "unsupported",
                    "size": int(np.prod(shape)) if shape else 0,
                }
            )
        return datasets

    @staticmethod
    def _can_auto_read(datasets) -> bool:
        if len(datasets) == 1:
            return datasets[0]["ndim"] in (1, 2)
        if not all(ds["ndim"] == 1 for ds in datasets):
            return False
        return len({ds["shape"][0] for ds in datasets}) == 1

    def inventory(self) -> InventoryResult:
        datasets = self._list_datasets()
        if not datasets:
            layout = INVENTORY_EMPTY
        elif len(datasets) == 1:
            layout = INVENTORY_SINGLE
        elif self._can_auto_read(datasets):
            layout = INVENTORY_LEGACY
        else:
            layout = INVENTORY_MULTI
        return make_inventory(layout, datasets)

    def parse(self):
        return list(self._descriptor()["objects"])

    def get_metadata(self) -> dict[str, Any]:
        spec = self._descriptor()
        return {"(root)": {"container": spec["container"], "objects": spec["objects"]}}

    def _selected_objects(self) -> list[str]:
        objects = self._descriptor()["objects"]
        keys = self._explicit_selected_keys
        if keys is None:
            return objects
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split(",") if k.strip()]
        keys = [str(k) for k in keys if k]
        unknown = [k for k in keys if k not in objects]
        if unknown:
            raise PDCError(f"Selected keys not listed in the PDC descriptor: {', '.join(unknown)}")
        repeated = sorted({k for k in keys if keys.count(k) > 1})
        if repeated:
            raise PDCError(f"Selected keys name an object more than once: {', '.join(repeated)}")
        return keys or objects

    def _frame(self, names: list[str]) -> pd.DataFrame | None:
        client = self._connect()
        shapes = {name: client.describe(name)[0] for name in names}
        entries = [{"ndim": len(s), "shape": s} for s in shapes.values()]
        if not self._can_auto_read(entries):
            self.logger.warning(
                "PDC objects %s cannot be combined into one table (shapes %s). Select one object of up to "
                "2 dimensions, or 1D objects of equal length.",
                names,
                [shapes[n] for n in names],
            )
            return None

        if len(names) == 1 and len(shapes[names[0]]) == 2:
            data = client.read(names[0])
            df = pd.DataFrame(data, columns=[f"{names[0]}_{i}" for i in range(data.shape[1])])
        else:
            df = pd.DataFrame({name: client.read(name) for name in names})
        return df if not df.empty else None

    def read(self):
        names = self._selected_objects()
        df = self._frame(names)
        if df is None:
            # Imported here: file_parser imports this module.
            from aidrin.file_handling.file_parser import ReaderReturnedNone

            raise ReaderReturnedNone(
                f"PDC descriptor '{self.file_path}' selects objects that cannot form one table. Run "
                f"`aidrin inventory {self.file_path}` to see their shapes, then pass --selected-keys (CLI) "
                "or selected_keys=[...] (library) with one object of up to 2 dimensions, or 1D objects of "
                "equal length."
            )
        return df
