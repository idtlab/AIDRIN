"""End-to-end PDC reader tests against a real PDC server through PDCpy.

Skipped unless PDCpy is installed and ``PDC_TMPDIR`` points at a running
``pdc_server``. Each run writes its own dummy objects under unique names, reads
them back through the CLI and ``read_file()``, then deletes them.

A PDC client that is not launched with MPI always binds port 8000, so only one
can run per host at a time. The objects are therefore written by a subprocess
that exits before the CLI tests start their own clients, and this test process
connects only after those (the CLI tests come first in this file), keeping the
connection until it deletes the objects at teardown.
"""

import json
import os
import subprocess
import sys
import textwrap
import uuid

import numpy as np
import pytest

pdc = pytest.importorskip("pdc")

from aidrin.file_handling.file_parser import ReaderReturnedNone, read_file  # noqa: E402
from aidrin.file_handling.readers.pdc_reader import PDCClient, PDCError, check_server  # noqa: E402

_TMPDIR = os.environ.get("PDC_TMPDIR")
if not _TMPDIR:
    pytest.skip("PDC_TMPDIR is not set; no PDC server to test against", allow_module_level=True)
try:
    check_server(_TMPDIR)
except PDCError as exc:
    pytest.skip(f"No reachable PDC server: {exc}", allow_module_level=True)

N = 50

_WRITER = textwrap.dedent(
    """
    import sys
    import numpy as np
    import pdc
    from aidrin.file_handling.readers.pdc_reader import route_logs_to_stderr

    route_logs_to_stderr(pdc)
    pdc.init()
    container = pdc.Container(sys.argv[2])
    with np.load(sys.argv[1]) as arrays:
        for name in arrays.files:
            container.object_from_array(name, arrays[name])
    """
)


def _env():
    return dict(os.environ, PDC_TMPDIR=_TMPDIR)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    """Write dummy objects to the server from a subprocess; delete them afterwards."""
    tag = uuid.uuid4().hex[:8]
    rng = np.random.default_rng(0)
    arrays = {
        f"age_{tag}": rng.integers(18, 90, N).astype(np.int32),
        f"income_{tag}": rng.normal(50000, 8000, N),
        f"score_{tag}": rng.random(N).astype(np.float32),
        f"flag_{tag}": (np.arange(N) % 2).astype(np.uint8),
        f"grid_{tag}": np.arange(N * 3, dtype=np.float64).reshape(N, 3),
        f"short_{tag}": np.arange(5, dtype=np.int64),
    }
    npz = tmp_path_factory.mktemp("pdc") / "arrays.npz"
    np.savez(npz, **arrays)
    container = f"aidrin_test_{tag}"
    result = subprocess.run(
        [sys.executable, "-c", _WRITER, str(npz), container], capture_output=True, text=True, env=_env(), timeout=120
    )
    assert result.returncode == 0, result.stderr
    yield {"tag": tag, "container": container, "arrays": arrays}

    PDCClient.get(_TMPDIR)
    for name in arrays:
        pdc.Object.get(name).delete()


def _descriptor(tmp_path, objects, **extra):
    path = tmp_path / "data.pdc"
    path.write_text(json.dumps({"objects": objects, "pdc_tmpdir": _TMPDIR, **extra}))
    return str(path)


def _names(dataset, *keys):
    return [f"{key}_{dataset['tag']}" for key in keys]


def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "aidrin.headless.cli", *args], capture_output=True, text=True, env=_env(), timeout=120
    )


# CLI tests first: each starts its own PDC client, which needs port 8000 free.


def test_cli_inventory_stdout_is_json(dataset, tmp_path):
    names = _names(dataset, "age", "income", "grid")
    result = _cli("inventory", _descriptor(tmp_path, names))
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)  # PDC's own logging must not reach stdout
    assert inventory["type"] == "multi_dataset"
    shapes = {d["path"]: (list(d["shape"]), d["dtype"]) for d in inventory["datasets"]}
    assert shapes == {names[0]: ([N], "int32"), names[1]: ([N], "float64"), names[2]: ([N, 3], "float64")}


def test_cli_completeness(dataset, tmp_path):
    names = _names(dataset, "age", "income")
    result = _cli("run", "completeness", _descriptor(tmp_path, names))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["Overall Completeness"] == 1.0


def test_cli_missing_object_fails_cleanly(dataset, tmp_path):
    result = _cli("run", "completeness", _descriptor(tmp_path, [f"missing_{dataset['tag']}"]))
    assert result.returncode == 1
    assert f"PDC object 'missing_{dataset['tag']}' not found" in result.stderr


# In-process tests: from here on this process holds the PDC connection.


def test_read_file_returns_exact_values_and_dtypes(dataset, tmp_path):
    names = _names(dataset, "age", "income", "score", "flag")
    path = _descriptor(tmp_path, names, container=dataset["container"])
    df = read_file((path, "data.pdc", ".pdc"))
    assert list(df.columns) == names
    for name in names:
        expected = dataset["arrays"][name]
        assert df[name].dtype == expected.dtype
        np.testing.assert_array_equal(df[name].to_numpy(), expected)


def test_2d_object(dataset, tmp_path):
    (grid,) = _names(dataset, "grid")
    df = read_file((_descriptor(tmp_path, [grid]), "data.pdc", ".pdc"))
    assert list(df.columns) == [f"{grid}_{i}" for i in range(3)]
    np.testing.assert_array_equal(df.to_numpy(), dataset["arrays"][grid])


def test_selected_keys(dataset, tmp_path):
    names = _names(dataset, "age", "income", "grid")
    df = read_file((_descriptor(tmp_path, names), "data.pdc", ".pdc", [names[1]]))
    assert list(df.columns) == [names[1]]


def test_mismatched_lengths_refused(dataset, tmp_path):
    with pytest.raises(ReaderReturnedNone, match="cannot form one table"):
        read_file((_descriptor(tmp_path, _names(dataset, "age", "short")), "data.pdc", ".pdc"))


def test_missing_container(dataset, tmp_path):
    path = _descriptor(tmp_path, _names(dataset, "age"), container=f"missing_{dataset['tag']}")
    with pytest.raises(PDCError, match="container .* not found"):
        read_file((path, "data.pdc", ".pdc"))
