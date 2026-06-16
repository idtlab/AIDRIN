"""Regression tests for the HDF5 heterogeneous-schema silent merger bug.

Before the fix, hdf5Reader.read() accumulated row-dicts from every dataset in
an HDF5 file into a single list and then called pd.DataFrame(rows).  When two
datasets had different column sets pandas performed an implicit outer join,
injecting NaN into every column absent from a given row.  This caused the
completeness metric to report artificially low scores on fully-complete data.

After the fix, read() detects the schema mismatch and raises ValueError with a
message directing the user to use the parse/filter workflow, so the failure is
surfaced rather than silently corrupting metric results.
"""

import logging
import sys
import tempfile
import types
import unittest

import h5py
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Prevent aidrin/__init__.py from running (it requires a live Flask+Celery
# app context) while still allowing submodule imports to resolve to the
# real files on disk.  We inject a namespace-style stub for "aidrin" that
# exposes __path__ so Python can find aidrin.file_handling.readers.*.
# ---------------------------------------------------------------------------

_AIDRIN_ROOT = __file__.replace("test_hdf5_schema_merger.py", "aidrin")

if "aidrin" not in sys.modules:
    _aidrin_stub = types.ModuleType("aidrin")
    _aidrin_stub.__path__ = [_AIDRIN_ROOT]
    _aidrin_stub.__package__ = "aidrin"
    sys.modules["aidrin"] = _aidrin_stub

# Also stub any heavy transitive imports that would fail outside a Flask app.
for _mod in ("aidrin.file_handling.file_parser",):
    if _mod not in sys.modules:
        _m = types.ModuleType(_mod)
        _m.read_file = staticmethod(lambda x: x)
        _m.SUPPORTED_FILE_TYPES = []
        _m.READER_MAP = {}
        sys.modules[_mod] = _m

# pkg_resources may be absent on Python 3.13+ without setuptools.
if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

# ---------------------------------------------------------------------------

from aidrin.file_handling.readers.hdf5_reader import hdf5Reader  # noqa: E402

_LOG = logging.getLogger("test_hdf5")


def _reader(path):
    return hdf5Reader(path, _LOG)


# ---------------------------------------------------------------------------
# Helpers to build test HDF5 files
# ---------------------------------------------------------------------------


def _write_single_structured(path):
    """One structured dataset: /jets with fields pt, eta.  100 % complete."""
    with h5py.File(path, "w") as f:
        dt = np.dtype([("pt", "f8"), ("eta", "f8")])
        data = np.zeros(100, dtype=dt)
        data["pt"] = np.random.exponential(50, 100)
        data["eta"] = np.random.uniform(-2.5, 2.5, 100)
        f.create_dataset("jets", data=data)


def _write_same_schema_two_datasets(path):
    """Two structured datasets with the same fields: /jets, /muons."""
    with h5py.File(path, "w") as f:
        dt = np.dtype([("pt", "f8"), ("eta", "f8")])

        jets = np.zeros(80, dtype=dt)
        jets["pt"] = np.random.exponential(50, 80)
        jets["eta"] = np.random.uniform(-2.5, 2.5, 80)
        f.create_dataset("jets", data=jets)

        muons = np.zeros(40, dtype=dt)
        muons["pt"] = np.random.exponential(30, 40)
        muons["eta"] = np.random.uniform(-2.4, 2.4, 40)
        f.create_dataset("muons", data=muons)


def _write_heterogeneous_schema(path):
    """Two datasets with different field sets: /jets (pt, eta) and /photons (E, phi, is_tight).

    Before the fix this silently produced a 5-column DataFrame where 60 % of
    values were NaN despite both source datasets being 100 % complete.
    """
    with h5py.File(path, "w") as f:
        jets_dt = np.dtype([("pt", "f8"), ("eta", "f8")])
        jets = np.zeros(100, dtype=jets_dt)
        jets["pt"] = np.random.exponential(50, 100)
        jets["eta"] = np.random.uniform(-2.5, 2.5, 100)
        f.create_dataset("jets", data=jets)

        photon_dt = np.dtype([("E", "f8"), ("phi", "f8"), ("is_tight", "?")])
        photons = np.zeros(50, dtype=photon_dt)
        photons["E"] = np.random.exponential(30, 50)
        photons["phi"] = np.random.uniform(-3.14159, 3.14159, 50)
        photons["is_tight"] = np.random.choice([True, False], 50)
        f.create_dataset("photons", data=photons)


# ===========================================================================
# Tests: single dataset (existing behaviour must be preserved)
# ===========================================================================


class TestSingleDataset(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".h5", delete=False)
        self._tmp.close()
        _write_single_structured(self._tmp.name)

    def test_read_returns_dataframe(self):
        df = _reader(self._tmp.name).read()
        self.assertIsInstance(df, pd.DataFrame)

    def test_correct_shape(self):
        df = _reader(self._tmp.name).read()
        self.assertEqual(len(df), 100)
        self.assertSetEqual(set(df.columns), {"pt", "eta"})

    def test_no_nulls(self):
        """Single fully-complete dataset must have zero NaN values."""
        df = _reader(self._tmp.name).read()
        self.assertFalse(df.isnull().any().any(), "Expected zero NaN values")

    def test_completeness_is_one(self):
        df = _reader(self._tmp.name).read()
        per_col = 1 - df.isnull().mean()
        for col, score in per_col.items():
            self.assertAlmostEqual(
                score, 1.0, msg=f"Column {col!r} completeness should be 1.0, got {score}"
            )


# ===========================================================================
# Tests: two datasets with the SAME schema (existing behaviour preserved)
# ===========================================================================


class TestSameSchemaMultiDataset(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".h5", delete=False)
        self._tmp.close()
        _write_same_schema_two_datasets(self._tmp.name)

    def test_read_returns_dataframe(self):
        df = _reader(self._tmp.name).read()
        self.assertIsInstance(df, pd.DataFrame)

    def test_correct_row_count(self):
        df = _reader(self._tmp.name).read()
        self.assertEqual(len(df), 120)  # 80 jets + 40 muons

    def test_correct_columns(self):
        df = _reader(self._tmp.name).read()
        self.assertSetEqual(set(df.columns), {"pt", "eta"})

    def test_no_nulls(self):
        df = _reader(self._tmp.name).read()
        self.assertFalse(df.isnull().any().any())


# ===========================================================================
# Tests: two datasets with DIFFERENT schemas — the bug scenario
# ===========================================================================


class TestHeterogeneousSchemaRaisesError(unittest.TestCase):
    """After the fix, reading an HDF5 file whose datasets have incompatible
    schemas raises ValueError instead of silently merging them with NaN fill."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".h5", delete=False)
        self._tmp.close()
        _write_heterogeneous_schema(self._tmp.name)

    def test_raises_value_error(self):
        with self.assertRaises(ValueError):
            _reader(self._tmp.name).read()

    def test_error_message_names_datasets(self):
        """The error message must list the conflicting dataset paths so the
        user knows which groups to select via the parse/filter workflow."""
        with self.assertRaises(ValueError) as ctx:
            _reader(self._tmp.name).read()
        msg = str(ctx.exception)
        self.assertIn("jets", msg)
        self.assertIn("photons", msg)

    def test_error_message_mentions_filter_workflow(self):
        """The error message must direct the user to the parse/filter step."""
        with self.assertRaises(ValueError) as ctx:
            _reader(self._tmp.name).read()
        msg = str(ctx.exception).lower()
        self.assertTrue(
            "filter" in msg or "select" in msg or "group" in msg,
            f"Error must mention filter/select workflow, got: {msg!r}",
        )


# ===========================================================================
# Regression guard: demonstrate what the pre-fix code would have produced
# ===========================================================================


class TestPreFixBehaviourDemonstration(unittest.TestCase):
    """These tests replicate the pre-fix accumulation logic directly to prove
    that the old code produced false completeness scores on fully-complete data.
    They do NOT call hdf5Reader — they document the bug for the record."""

    def _old_read_heterogeneous(self, path):
        """Replicates the pre-fix path: all datasets merged unconditionally."""
        rows = []
        with h5py.File(path, "r") as f:
            def visit(name, obj):
                if isinstance(obj, h5py.Dataset):
                    data = obj[()]
                    try:
                        df = pd.DataFrame(data)
                    except Exception:
                        df = pd.DataFrame(data.tolist())
                    for _, row in df.iterrows():
                        rows.append(row.to_dict())
            f.visititems(visit)
        return pd.DataFrame(rows)

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".h5", delete=False)
        self._tmp.close()
        _write_heterogeneous_schema(self._tmp.name)

    def test_pre_fix_produces_nan_inflation(self):
        """The pre-fix merger injects NaN into fully-complete data."""
        df = self._old_read_heterogeneous(self._tmp.name)
        self.assertTrue(
            df.isnull().any().any(),
            "Pre-fix code must produce NaN-inflated DataFrame from heterogeneous datasets",
        )

    def test_pre_fix_overall_completeness_is_zero(self):
        """Pre-fix: no row has all columns filled, so overall completeness = 0 %."""
        df = self._old_read_heterogeneous(self._tmp.name)
        overall = 1 - df.isnull().any(axis=1).mean()
        self.assertAlmostEqual(
            overall,
            0.0,
            places=5,
            msg=f"Pre-fix overall completeness should be 0.0, got {overall:.4f}",
        )


if __name__ == "__main__":
    unittest.main()
