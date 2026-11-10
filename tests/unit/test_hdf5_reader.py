"""
Tests for HDF5 fill-value normalization in hdf5Reader.

Verifies that every source of fill-value information (HDF5 native fillvalue,
_FillValue attribute, missing_value attribute, and user-supplied fill_values)
is correctly translated to NaN so that pd.isnull()-based metrics report
accurate completeness scores rather than the 100% that was returned before
this fix when data contained fill-value-encoded missing entries.
"""

import logging
import math
import sys
import types

# ---------------------------------------------------------------------------
# Compatibility shim: pkg_resources was removed from the stdlib in Python 3.12+
# and is only available when setuptools is installed.  dython imports it at
# module level, which prevents the whole aidrin package from loading on clean
# Python 3.13 environments.  Inject a minimal stub before any aidrin import so
# that the test suite works without requiring a full project venv.
# ---------------------------------------------------------------------------
if "pkg_resources" not in sys.modules:
    _pkg_resources = types.ModuleType("pkg_resources")

    class _Dist:
        def __init__(self):
            self.version = "0.0.0"

    _pkg_resources.get_distribution = lambda _name: _Dist()
    sys.modules["pkg_resources"] = _pkg_resources

import h5py
import numpy as np
import pandas as pd
import pytest

from aidrin.file_handling.readers.hdf5_reader import hdf5Reader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def logger():
    return logging.getLogger("test_hdf5_reader")


def _sample_path(*parts):
    """Path to a bundled sample dataset, or None when it is not available."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "examples" / "sample_data" / Path(*parts)
    return path if path.is_file() else None


def _make_hdf5(path, data, fillvalue=None, attrs=None):
    """Write a minimal single-dataset HDF5 file for testing."""
    with h5py.File(path, "w") as f:
        kwargs = {} if fillvalue is None else {"fillvalue": fillvalue}
        ds = f.create_dataset("measurements", data=data, **kwargs)
        if attrs:
            for k, v in attrs.items():
                ds.attrs[k] = v


def _read_col(tmp_path, logger, data, fillvalue=None, attrs=None, fill_values=None):
    """Write a file, read it, and return the first DataFrame column as a Series."""
    fpath = str(tmp_path / "test.h5")
    _make_hdf5(fpath, data, fillvalue=fillvalue, attrs=attrs)
    kwargs = {} if fill_values is None else {"fill_values": fill_values}
    df = hdf5Reader(fpath, logger, **kwargs).read()
    assert df is not None, "hdf5Reader.read() returned None"
    return df.iloc[:, 0]


# ---------------------------------------------------------------------------
# Explicit fill-value sources (replaced silently, no WARNING)
# ---------------------------------------------------------------------------

class TestExplicitFillValues:

    def test_netcdf_fillvalue_attr_replaced(self, tmp_path, logger, caplog):
        """_FillValue attribute sentinel is replaced with NaN without a WARNING."""
        data = np.array([1.0, -9999.0, 3.0, -9999.0, 5.0], dtype=np.float64)

        with caplog.at_level(logging.WARNING):
            col = _read_col(tmp_path, logger, data, attrs={"_FillValue": -9999.0})

        assert col.isna().sum() == 2
        assert list(col.dropna()) == [1.0, 3.0, 5.0]
        assert not any("default fill value" in r.message for r in caplog.records)

    def test_missing_value_attr_replaced(self, tmp_path, logger, caplog):
        """missing_value attribute sentinel (NetCDF legacy) is replaced with NaN."""
        data = np.array([10, -1, 20, -1, 30], dtype=np.int32)

        with caplog.at_level(logging.WARNING):
            col = _read_col(tmp_path, logger, data, attrs={"missing_value": np.int32(-1)})

        assert col.isna().sum() == 2
        assert not any("default fill value" in r.message for r in caplog.records)

    def test_missing_value_array_attr_all_sentinels_replaced(self, tmp_path, logger):
        """missing_value may be a 1-D array listing multiple sentinels — all replaced."""
        data = np.array([1.0, -9999.0, 3.0, -1.0, 5.0], dtype=np.float64)
        col = _read_col(tmp_path, logger, data,
                        attrs={"missing_value": np.array([-9999.0, -1.0])})

        assert col.isna().sum() == 2
        assert list(col.dropna()) == [1.0, 3.0, 5.0]

    def test_nonzero_native_fillvalue_replaced_silently(self, tmp_path, logger, caplog):
        """A non-zero HDF5 native fillvalue (no attrs) is explicit — replaced without WARNING."""
        data = np.array([1.0, -9999.0, 3.0], dtype=np.float64)

        with caplog.at_level(logging.WARNING):
            col = _read_col(tmp_path, logger, data, fillvalue=-9999.0)

        assert col.isna().sum() == 1
        assert list(col.dropna()) == [1.0, 3.0]
        assert not any("default fill value" in r.message for r in caplog.records)

    def test_user_supplied_fill_values_replace_sentinel(self, tmp_path, logger, caplog):
        """fill_values constructor parameter marks an arbitrary value as explicit."""
        data = np.array([1.0, 42.0, 3.0, 42.0, 5.0], dtype=np.float64)

        with caplog.at_level(logging.WARNING):
            col = _read_col(tmp_path, logger, data, fill_values=[42.0])

        assert col.isna().sum() == 2
        assert list(col.dropna()) == [1.0, 3.0, 5.0]
        assert not any("default fill value" in r.message for r in caplog.records)

    def test_user_supplied_overrides_uncertain_classification(self, tmp_path, logger, caplog):
        """Passing fill_values=[0] moves zero from uncertain to explicit — no WARNING."""
        data = np.array([0, 1, 2, 0, 4], dtype=np.int32)

        with caplog.at_level(logging.WARNING):
            col = _read_col(tmp_path, logger, data, fill_values=[0])

        assert col.isna().sum() == 2
        assert not any("default fill value" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# HDF5 default zero: valid data, not replaced (issue #121)
# ---------------------------------------------------------------------------

class TestDefaultZeroPreserved:

    def test_zero_default_fillvalue_not_replaced(self, tmp_path, logger, caplog):
        """HDF5 default zero (no attrs) is valid data — not converted to NaN."""
        data = np.array([0, 1, 2, 0, 4], dtype=np.int32)

        with caplog.at_level(logging.WARNING):
            col = _read_col(tmp_path, logger, data)

        assert col.isna().sum() == 0
        assert col.tolist() == [0, 1, 2, 0, 4]
        assert not any("default fill value" in r.message for r in caplog.records)

    def test_float_zero_default_not_replaced(self, tmp_path, logger):
        data = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        col = _read_col(tmp_path, logger, data)

        assert col.isna().sum() == 0
        assert col.tolist() == [0.0, 1.0, 0.0]

    def test_zero_with_explicit_fill_attr_only_replaces_sentinel(self, tmp_path, logger, caplog):
        """Explicit _FillValue is replaced; default zero measurements are kept."""
        data = np.array([0.0, 1.0, -9999.0, 3.0], dtype=np.float64)

        with caplog.at_level(logging.WARNING):
            col = _read_col(tmp_path, logger, data, attrs={"_FillValue": -9999.0})

        assert math.isnan(float(col[col.index[2]]))
        assert not any("default fill value" in r.message for r in caplog.records)
        assert col.iloc[0] == 0.0
        non_nan = col.dropna().tolist()
        assert 0.0 in non_nan
        assert 1.0 in non_nan
        assert 3.0 in non_nan


# ---------------------------------------------------------------------------
# No-op cases: nothing matched, nothing logged
# ---------------------------------------------------------------------------

class TestNoReplacementNeeded:

    def test_no_matching_fill_values_no_nan(self, tmp_path, logger):
        """When no data values match any sentinel, the column is unchanged."""
        data = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        col = _read_col(tmp_path, logger, data, fillvalue=-9999.0)

        assert col.isna().sum() == 0

    def test_no_matching_fill_values_no_log_noise(self, tmp_path, logger, caplog):
        """No 'replaced' or 'default fill value' messages emitted when nothing matched."""
        data = np.array([1.0, 2.0, 3.0], dtype=np.float64)

        with caplog.at_level(logging.INFO):
            _read_col(tmp_path, logger, data, fillvalue=-9999.0)

        assert not any(
            "replaced" in r.message or "default fill value" in r.message
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# End-to-end: completeness metric reflects true missingness
# ---------------------------------------------------------------------------

class TestCompletenessAccuracy:

    def test_completeness_is_correct_not_100_percent(self, tmp_path, logger):
        """
        Before this fix, hdf5Reader returned raw fill values and pd.isnull()
        saw no NaN, so completeness was always reported as 1.0 (100%) even for
        datasets with extensive missingness.  After the fix, completeness
        reflects the true fraction of present values.
        """
        # 3 valid values, 2 fill-value-encoded missing → true completeness = 0.6
        data = np.array([1.0, -9999.0, 3.0, -9999.0, 5.0], dtype=np.float64)
        col = _read_col(tmp_path, logger, data, attrs={"_FillValue": -9999.0})

        completeness = 1 - col.isnull().mean()
        assert abs(completeness - 0.6) < 1e-9, (
            f"Expected completeness 0.6, got {completeness}. "
            "Fill values were not translated to NaN."
        )

    def test_fully_present_dataset_still_reports_100_percent(self, tmp_path, logger):
        """A genuinely complete dataset still scores 1.0 after the fix."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
        col = _read_col(tmp_path, logger, data, fillvalue=-9999.0)

        completeness = 1 - col.isnull().mean()
        assert completeness == 1.0

    def test_integer_dataset_completeness(self, tmp_path, logger):
        """Fill-value NaN replacement works for integer dtypes (promoted to float64)."""
        data = np.array([10, 32767, 20, 32767, 30], dtype=np.int16)
        col = _read_col(tmp_path, logger, data, attrs={"_FillValue": np.int16(32767)})

        completeness = 1 - col.isnull().mean()
        assert abs(completeness - 0.6) < 1e-9


class TestUndefinedNativeFillValue:

    def test_int32_without_explicit_fillvalue_reads_successfully(self, tmp_path, logger):
        """int32 datasets without _FillValue attrs must read without error."""
        data = np.array([16, 12, 21, 21, 36], dtype=np.int32)
        fpath = str(tmp_path / "undefined_fill.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("lengths", data=data)

        df = hdf5Reader(fpath, logger).read()
        assert df is not None
        assert len(df) == len(data)
        assert df.iloc[:, 0].tolist() == data.tolist()


class TestIncompatibleRootLayout:

    def _write_root_datasets(self, path, shapes):
        with h5py.File(path, "w") as f:
            for i, length in enumerate(shapes):
                f.create_dataset(f"D{i}.values", data=np.arange(length, dtype=np.int32))

    def test_parse_lists_root_dataset_paths(self, tmp_path, logger):
        fpath = str(tmp_path / "multi_root.h5")
        self._write_root_datasets(fpath, [16, 47])

        paths = hdf5Reader(fpath, logger).parse()
        assert paths == ["D0.values", "D1.values"]

    def test_read_refuses_incompatible_root_flatten(self, tmp_path, logger):
        fpath = str(tmp_path / "multi_root.h5")
        self._write_root_datasets(fpath, [16, 47])

        reader = hdf5Reader(fpath, logger)
        assert reader.inventory()["type"] == "multi_dataset"
        assert reader.read() is None

    def test_read_selected_dataset_path(self, tmp_path, logger, monkeypatch):
        mock_session = type("Session", (), {"get": lambda self, key, default=None: ["D0.values"] if key == "selected_keys" else default})()
        monkeypatch.setattr(
            "aidrin.file_handling.readers.hdf5_reader.session",
            mock_session,
        )

        fpath = str(tmp_path / "multi_root.h5")
        self._write_root_datasets(fpath, [16, 47])
        df = hdf5Reader(fpath, logger).read()

        assert df is not None
        assert len(df) == 16
        assert "D0.values" in df.columns

    def test_read_multiple_compatible_datasets(self, tmp_path, logger, monkeypatch):
        fpath = str(tmp_path / "multi_cols.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("D1.fill_starts", data=np.arange(16, dtype=np.int32))
            f.create_dataset("D1.nreqs", data=np.arange(16, 32, dtype=np.int32))
            f.create_dataset("D1.lengths", data=np.arange(47, dtype=np.int32))

        keys = ["D1.fill_starts", "D1.nreqs"]
        mock_session = type(
            "Session",
            (),
            {"get": lambda self, key, default=None: keys if key == "selected_keys" else default},
        )()
        monkeypatch.setattr(
            "aidrin.file_handling.readers.hdf5_reader.session",
            mock_session,
        )

        df = hdf5Reader(fpath, logger).read()
        assert df is not None
        assert df.shape == (16, 2)
        assert list(df.columns) == ["D1.fill_starts", "D1.nreqs"]

    def test_read_multiple_incompatible_lengths_returns_none(self, tmp_path, logger, monkeypatch):
        fpath = str(tmp_path / "multi_cols_bad.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("D1.nreqs", data=np.arange(16, dtype=np.int32))
            f.create_dataset("D1.lengths", data=np.arange(47, dtype=np.int32))

        keys = ["D1.nreqs", "D1.lengths"]
        mock_session = type(
            "Session",
            (),
            {"get": lambda self, key, default=None: keys if key == "selected_keys" else default},
        )()
        monkeypatch.setattr(
            "aidrin.file_handling.readers.hdf5_reader.session",
            mock_session,
        )

        assert hdf5Reader(fpath, logger).read() is None

    def test_inventory_includes_dot_prefix_groups(self, tmp_path, logger):
        fpath = str(tmp_path / "grouped_root.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("D1.fill_starts", data=np.arange(16, dtype=np.int32))
            f.create_dataset("D1.nreqs", data=np.arange(16, 32, dtype=np.int32))
            f.create_dataset("D2.fill_starts", data=np.arange(47, dtype=np.int32))
            f.create_dataset("D2.nreqs", data=np.arange(47, 79, dtype=np.int32))

        inv = hdf5Reader(fpath, logger).inventory()
        assert inv["type"] == "multi_dataset"
        groups = {group["id"]: group for group in inv["groups"]}
        assert set(groups) == {"D1", "D2"}
        assert groups["D1"]["dataset_paths"] == ["D1.fill_starts", "D1.nreqs"]
        assert groups["D2"]["dataset_paths"] == ["D2.fill_starts", "D2.nreqs"]

    def test_inventory_includes_hdf5_group_subtrees(self, tmp_path, logger):
        fpath = str(tmp_path / "nested_groups.h5")
        with h5py.File(fpath, "w") as f:
            grp = f.create_group("runA")
            grp.create_dataset("temp", data=np.arange(8, dtype=np.int32))
            grp.create_dataset("pressure", data=np.arange(8, 16, dtype=np.int32))
            f.create_dataset("solo", data=np.arange(3, dtype=np.int32))

        inv = hdf5Reader(fpath, logger).inventory()
        assert inv["type"] == "legacy"
        groups = inv["groups"]
        assert groups == []

        reader = hdf5Reader(fpath, logger)
        datasets = reader._list_datasets()
        groups = reader._build_picker_groups(datasets)
        assert len(groups) == 1
        assert groups[0]["id"] == "runA"
        assert set(groups[0]["dataset_paths"]) == {"runA/temp", "runA/pressure"}

    def test_read_uses_explicit_selected_keys_without_session(self, tmp_path, logger):
        fpath = str(tmp_path / "multi_cols_ok.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("D1.fill_starts", data=np.arange(16, dtype=np.int32))
            f.create_dataset("D1.nreqs", data=np.arange(16, 32, dtype=np.int32))
            f.create_dataset("D1.lengths", data=np.arange(47, dtype=np.int32))

        keys = ["D1.fill_starts", "D1.nreqs"]
        df = hdf5Reader(fpath, logger, selected_keys=keys).read()
        assert df is not None
        assert df.shape == (16, 2)

    def test_read_file_passes_selected_keys_for_celery(self, tmp_path, logger):
        from aidrin.file_handling.file_parser import read_file

        fpath = str(tmp_path / "multi_cols_ok.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("D1.fill_starts", data=np.arange(16, dtype=np.int32))
            f.create_dataset("D1.nreqs", data=np.arange(16, 32, dtype=np.int32))
            f.create_dataset("D1.lengths", data=np.arange(47, dtype=np.int32))

        keys = ["D1.fill_starts", "D1.nreqs"]
        df = read_file((fpath, "multi_cols_ok.h5", ".h5", keys))
        assert df is not None
        assert df.shape == (16, 2)

    def test_adult_sample_still_reads(self, logger):
        sample = _sample_path("h5", "adult.h5")
        if sample is None:
            pytest.skip("adult.h5 sample not available")

        df = hdf5Reader(str(sample), logger).read()
        assert df is not None
        assert not df.empty


def _make_mock_rechdf5(path, nx=2, ny=2, npts=100):
    """Minimal EQSIM/rechdf5-style station-grouped HDF5 (issue #121 repro)."""
    dt = 0.019467
    t = np.arange(npts) * dt

    with h5py.File(path, "w") as h5:
        h5["DELTA"] = [dt]
        h5["DOWNSAMPLE"] = [16]
        h5["ORIGINTIME"] = [0.0]

        for row in range(1, ny + 1):
            for col in range(1, nx + 1):
                name = f"S_{row:02d}_{col:02d}"
                g = h5.create_group(name)

                g["ISNSEW"] = [0]
                g["LOC"] = [0]
                g["NPTS"] = [npts]
                g["STLA,STLO,STDP"] = [37.5 + row * 0.01, -122.3 + col * 0.01, 0.0]
                g["STX,STY,STZ"] = [col * 1000.0, row * 1000.0, 0.0]

                wave = np.sin(2 * np.pi * 0.5 * t).astype("float32")
                wave[::257] = 0.0

                g["X"] = wave
                g["Y"] = 0.8 * wave
                g["Z"] = 0.4 * wave

                g["XCMPAZ"] = [90.0]
                g["XCMPINC"] = [0.0]
                g["YCMPAZ"] = [0.0]
                g["YCMPINC"] = [0.0]
                g["ZCMPAZ"] = [0.0]
                g["ZCMPINC"] = [90.0]


class TestGroupedEqsimLayout:
    """Station-grouped HDF5 (EQSIM/rechdf5) — issue #121."""

    def test_inventory_classifies_as_multi_dataset(self, tmp_path, logger):
        fpath = str(tmp_path / "rechdf5.h5")
        _make_mock_rechdf5(fpath, nx=2, ny=2, npts=100)

        inv = hdf5Reader(fpath, logger).inventory()
        assert inv["type"] == "multi_dataset"
        assert len(inv["groups"]) >= 2
        group_ids = {g["id"] for g in inv["groups"]}
        assert "S_01_01" in group_ids

    def test_read_refuses_blind_flatten(self, tmp_path, logger):
        fpath = str(tmp_path / "rechdf5.h5")
        _make_mock_rechdf5(fpath, nx=2, ny=2, npts=100)

        assert hdf5Reader(fpath, logger).read() is None

    def test_read_selected_waveforms_preserves_zeros(self, tmp_path, logger):
        fpath = str(tmp_path / "rechdf5.h5")
        _make_mock_rechdf5(fpath, nx=2, ny=2, npts=100)

        keys = ["S_01_01/X", "S_01_01/Y", "S_01_01/Z"]
        df = hdf5Reader(fpath, logger, selected_keys=keys).read()

        assert df is not None
        assert df.shape == (100, 3)
        assert list(df.columns) == ["S_01_01/X", "S_01_01/Y", "S_01_01/Z"]
        assert (df["S_01_01/X"] == 0.0).any()
        assert df["S_01_01/X"].isna().sum() == 0

    def test_read_selected_waveforms_keeps_station_path_context(self, tmp_path, logger):
        """Selecting the same short names from two stations stays distinguishable."""
        fpath = str(tmp_path / "rechdf5.h5")
        _make_mock_rechdf5(fpath, nx=2, ny=2, npts=50)

        keys = ["S_01_01/X", "S_01_02/X"]
        df = hdf5Reader(fpath, logger, selected_keys=keys).read()

        assert df is not None
        assert df.shape == (50, 2)
        assert list(df.columns) == ["S_01_01/X", "S_01_02/X"]

    def test_pandas_hdf5_stays_legacy_not_multi_dataset(self, logger):
        sample = _sample_path("h5", "adult.h5")
        if sample is None:
            pytest.skip("adult.h5 sample not available")

        inv = hdf5Reader(str(sample), logger).inventory()
        assert inv["type"] == "legacy"


class TestPandasHDFStoreLayouts:
    """A pandas HDFStore file must read back as the frame pandas wrote.

    Both store formats keep their real data behind pandas' private block
    layout (``axis0``, ``block0_values``, ``_i_table/…``).  Walking those
    datasets as if they were independent arrays concatenates the row index and
    the column-name arrays into the data, so the reader has to recognise the
    layout and let pandas decode it.
    """

    def test_fixed_format_adult_matches_source_csv(self, logger):
        sample = _sample_path("h5", "adult.h5")
        csv_sample = _sample_path("csv", "adult.csv")
        if sample is None or csv_sample is None:
            pytest.skip("adult sample pair not available")

        expected = pd.read_csv(csv_sample)
        df = hdf5Reader(str(sample), logger).read()

        assert df is not None
        assert list(df.columns) == list(expected.columns)
        assert df.reset_index(drop=True).equals(expected)

    def test_fixed_format_employees_reads_named_columns(self, logger):
        sample = _sample_path("h5", "employees.h5")
        if sample is None:
            pytest.skip("employees.h5 sample not available")

        df = hdf5Reader(str(sample), logger).read()

        assert df is not None
        assert df.shape == (8, 7)
        assert not any(str(col).isdigit() for col in df.columns)

    def test_table_format_reads_named_columns(self, tmp_path, logger):
        pytest.importorskip("tables")
        expected = pd.DataFrame(
            {"reading": np.arange(6, dtype=np.int64), "station": list("abcdef")}
        )
        fpath = str(tmp_path / "table_format.h5")
        expected.to_hdf(fpath, key="data", format="table")

        df = hdf5Reader(fpath, logger).read()

        assert df is not None
        assert list(df.columns) == ["reading", "station"]
        assert df.reset_index(drop=True).equals(expected)

    def test_pandas_store_offers_no_dataset_picker(self, logger):
        """A decoded store is one coherent table, so selection stays unnecessary."""
        sample = _sample_path("h5", "employees.h5")
        if sample is None:
            pytest.skip("employees.h5 sample not available")

        assert hdf5Reader(str(sample), logger).inventory()["type"] == "legacy"


class TestPandasHDFStoreMultipleFrames:
    """A store may hold several frames, so the caller has to be able to choose."""

    @staticmethod
    def _write_two_frames(path):
        pd.DataFrame({"alpha": [1, 2, 3]}).to_hdf(path, key="first", format="table")
        pd.DataFrame({"beta": [4.5, 5.5, 6.5]}).to_hdf(path, key="second", format="table")

    def test_selected_key_picks_that_frame(self, tmp_path, logger):
        pytest.importorskip("tables")
        fpath = str(tmp_path / "two_frames.h5")
        self._write_two_frames(fpath)

        df = hdf5Reader(fpath, logger, selected_keys=["second"]).read()

        assert df is not None
        assert list(df.columns) == ["beta"]

    def test_leading_slash_key_form_also_resolves(self, tmp_path, logger):
        pytest.importorskip("tables")
        fpath = str(tmp_path / "two_frames.h5")
        self._write_two_frames(fpath)

        df = hdf5Reader(fpath, logger, selected_keys=["/second"]).read()

        assert df is not None
        assert list(df.columns) == ["beta"]

    def test_defaulting_to_first_frame_is_logged(self, tmp_path, logger, caplog):
        """Choosing for the user silently would hide half the file."""
        pytest.importorskip("tables")
        fpath = str(tmp_path / "two_frames.h5")
        self._write_two_frames(fpath)

        with caplog.at_level(logging.WARNING):
            df = hdf5Reader(fpath, logger).read()

        assert df is not None
        assert list(df.columns) == ["alpha"]
        assert "second" in caplog.text


# ---------------------------------------------------------------------------
# read_file() refuses an ambiguous multi_dataset layout instead of returning
# an empty table silently (see zarr's matching contract in
# test_structured_readers.py::test_read_file_raises_for_zarr_needing_selection)
# ---------------------------------------------------------------------------

class TestReadFileRefusesAmbiguousLayout:

    def test_raises_for_incompatible_root_layout(self, tmp_path):
        from aidrin.file_handling.file_parser import ReaderReturnedNone, read_file

        fpath = str(tmp_path / "ragged.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("a", data=np.arange(10, dtype=np.int32))
            f.create_dataset("b", data=np.arange(7, dtype=np.int32))

        with pytest.raises(ReaderReturnedNone) as excinfo:
            read_file((fpath, "ragged.h5", ".h5"))

        message = str(excinfo.value)
        assert "multi_dataset" in message
        assert "aidrin inventory" in message

    def test_raises_for_empty_store(self, tmp_path):
        from aidrin.file_handling.file_parser import ReaderReturnedNone, read_file

        fpath = str(tmp_path / "empty.h5")
        with h5py.File(fpath, "w"):
            pass

        with pytest.raises(ReaderReturnedNone):
            read_file((fpath, "empty.h5", ".h5"))

    def test_does_not_raise_when_selection_resolves_it(self, tmp_path):
        from aidrin.file_handling.file_parser import read_file

        fpath = str(tmp_path / "ragged.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("a", data=np.arange(10, dtype=np.int32))
            f.create_dataset("b", data=np.arange(7, dtype=np.int32))

        df = read_file((fpath, "ragged.h5", ".h5", ["a"]))
        assert df is not None
        assert list(df.columns) == ["a"]


# ---------------------------------------------------------------------------
# aidrin.headless.api.inventory() -- the library/CLI entry point that exposes
# hdf5Reader.inventory() without going through read().
# ---------------------------------------------------------------------------

class TestApiInventory:

    def test_classifies_multi_dataset_hdf5_layout(self, tmp_path):
        from aidrin.headless.api import inventory

        fpath = str(tmp_path / "ragged.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("a", data=np.arange(10, dtype=np.int32))
            f.create_dataset("b", data=np.arange(7, dtype=np.int32))

        result = inventory(fpath)

        assert result["type"] == "multi_dataset"
        paths = {ds["path"] for ds in result["datasets"]}
        assert paths == {"a", "b"}

    def test_rejects_a_format_with_no_ambiguous_layout(self, tmp_path):
        from aidrin.headless.api import inventory

        fpath_obj = tmp_path / "plain.csv"
        fpath_obj.write_text("a,b\n1,2\n")

        with pytest.raises(ValueError) as excinfo:
            inventory(str(fpath_obj))

        assert "csv" in str(excinfo.value).lower()


class TestGridDatasetGuard:
    """Grids (ndim >= 3) must be refused, never flattened into list-valued cells.

    Every path below previously produced a DataFrame whose cells held Python
    lists (or, for the legacy walk, a mostly-NaN ragged frame).  Metrics then
    reported confident nonsense: a fully populated file scored 1.0000
    completeness over 15 list objects instead of its 1920 floats.
    """

    @staticmethod
    def _write_grid_file(path, nx, ny, nt, ntraj):
        """A gridded file: coordinate vectors plus (traj, t, x, y) fields."""
        with h5py.File(path, "w") as f:
            f.create_dataset("dimensions/x", data=np.linspace(0, 1, nx, dtype="f4"))
            f.create_dataset("dimensions/y", data=np.linspace(0, 1, ny, dtype="f4"))
            f.create_dataset("dimensions/time", data=np.arange(nt, dtype="f4"))
            f.create_dataset("scalars/viscosity", data=np.full(ntraj, 0.01, dtype="f4"))
            f.create_dataset("t0_fields/density", data=np.zeros((ntraj, nt, nx, ny), dtype="f4"))
            f.create_dataset("t0_fields/pressure", data=np.zeros((ntraj, nt, nx, ny), dtype="f4"))

    def test_equal_length_coords_still_require_selection(self, tmp_path, logger):
        """Classification must key on shape, not 1D length.

        A square grid with equal step and trajectory counts gives every
        coordinate vector the same length, which slipped past both length
        heuristics and typed the file 'legacy'.
        """
        fpath = str(tmp_path / "square_grid.h5")
        self._write_grid_file(fpath, 8, 8, 8, 8)

        assert hdf5Reader(fpath, logger).inventory()["type"] == "multi_dataset"

    def test_equal_length_coords_are_not_flattened(self, tmp_path, logger):
        fpath = str(tmp_path / "square_grid.h5")
        self._write_grid_file(fpath, 8, 8, 8, 8)

        assert hdf5Reader(fpath, logger).read() is None

    def test_distinct_length_coords_require_selection(self, tmp_path, logger):
        fpath = str(tmp_path / "rect_grid.h5")
        self._write_grid_file(fpath, 16, 8, 5, 3)

        assert hdf5Reader(fpath, logger).inventory()["type"] == "multi_dataset"

    def test_lone_grid_dataset_is_refused(self, tmp_path, logger, caplog):
        """A single grid short-circuits to 'single_dataset' and reaches the legacy walk."""
        fpath = str(tmp_path / "solo_grid.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("field", data=np.zeros((4, 5, 6), dtype="f4"))

        with caplog.at_level(logging.WARNING):
            df = hdf5Reader(fpath, logger).read()

        assert df is None
        assert "ndim >= 3" in caplog.text

    def test_selected_grid_dataset_is_read_as_a_table(self, tmp_path, logger):
        """An explicit selection is explicit intent, so the grid is flattened.

        Replaces an earlier assertion that this was refused: refusing was the
        safe interim behaviour while a grid had no tabular reading at all.
        """
        fpath = str(tmp_path / "grid.h5")
        self._write_grid_file(fpath, 4, 5, 3, 2)

        df = hdf5Reader(fpath, logger, selected_keys=["t0_fields/density"]).read()

        assert df is not None
        assert df.shape == (2 * 3 * 4 * 5, 1)


    def test_guard_reads_metadata_only(self, tmp_path, logger, monkeypatch):
        """A real grid would not fit in RAM, so the guard must fire before any read."""
        fpath = str(tmp_path / "grid.h5")
        self._write_grid_file(fpath, 4, 5, 3, 2)

        def _boom(self, item):
            raise AssertionError("dataset was materialized before the ndim check")

        monkeypatch.setattr(h5py.Dataset, "__getitem__", _boom)

        reader = hdf5Reader(fpath, logger)
        assert reader._read_dataset_path("t0_fields/density") is None

    def test_two_dimensional_dataset_still_reads(self, tmp_path, logger):
        """The guard starts at ndim 3: a 2D dataset is a table and must survive."""
        fpath = str(tmp_path / "flat.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("grid2d", data=np.arange(12, dtype="f4").reshape(3, 4))

        df = hdf5Reader(fpath, logger)._read_dataset_path("grid2d")

        assert df is not None
        assert df.shape == (3, 4)

    def test_one_dimensional_selection_unaffected(self, tmp_path, logger):
        fpath = str(tmp_path / "grid.h5")
        self._write_grid_file(fpath, 4, 5, 3, 2)

        df = hdf5Reader(fpath, logger, selected_keys=["scalars/viscosity"]).read()

        assert df is not None
        assert df.shape == (2, 1)

class TestGridTables:
    """Aligned grids flatten to one row per cell, one column per field."""

    @staticmethod
    def _write(path, grid=(2, 3, 4, 5), components=2):
        """Scalar fields on a shared grid, plus a vector field with a trailing dim."""
        cells = int(np.prod(grid))
        with h5py.File(path, "w") as f:
            f.create_dataset("dimensions/x", data=np.arange(grid[2], dtype="f4"))
            f.create_dataset("dimensions/y", data=np.arange(grid[3], dtype="f4"))
            f.create_dataset("dimensions/time", data=np.arange(grid[1], dtype="f4"))
            f.create_dataset("t0_fields/density", data=np.arange(cells, dtype="f4").reshape(grid))
            f.create_dataset(
                "t0_fields/pressure",
                data=(np.arange(cells, dtype="f4") * 2).reshape(grid),
            )
            f.create_dataset(
                "t1_fields/velocity",
                data=np.arange(cells * components, dtype="f4").reshape(grid + (components,)),
            )

    def test_aligned_fields_share_one_row_per_cell(self, tmp_path, logger):
        fpath = str(tmp_path / "grid.h5")
        self._write(fpath)

        df = hdf5Reader(
            fpath, logger, selected_keys=["t0_fields/density", "t0_fields/pressure"]
        ).read()

        assert df.shape == (2 * 3 * 4 * 5, 2)
        assert list(df.columns) == ["t0_fields/density", "t0_fields/pressure"]
        np.testing.assert_array_equal(df["t0_fields/density"].values, np.arange(120, dtype="f4"))
        np.testing.assert_array_equal(
            df["t0_fields/pressure"].values, np.arange(120, dtype="f4") * 2
        )

    def test_trailing_dimension_splits_into_components(self, tmp_path, logger):
        """A vector field is (*grid, D); one column per component keeps it aligned."""
        fpath = str(tmp_path / "grid.h5")
        self._write(fpath)

        df = hdf5Reader(
            fpath, logger, selected_keys=["t0_fields/density", "t1_fields/velocity"]
        ).read()

        assert list(df.columns) == [
            "t0_fields/density",
            "t1_fields/velocity_0",
            "t1_fields/velocity_1",
        ]
        assert len(df) == 120
        # component i of cell n is the raw element at n * 2 + i
        raw = np.arange(240, dtype="f4").reshape(2, 3, 4, 5, 2)
        np.testing.assert_array_equal(
            df["t1_fields/velocity_1"].values, raw[..., 1].reshape(-1)
        )

    def test_misaligned_selection_is_refused(self, tmp_path, logger, caplog):
        """Fields on different grids cannot share rows; merging them would be a lie."""
        fpath = str(tmp_path / "mixed.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("a/one", data=np.zeros((2, 3, 4), dtype="f4"))
            f.create_dataset("a/two", data=np.zeros((2, 3, 5), dtype="f4"))
            f.create_dataset("a/three", data=np.zeros((2, 3, 4), dtype="f4"))
            f.create_dataset("a/four", data=np.zeros((2, 3, 4), dtype="f4"))

        with caplog.at_level(logging.WARNING):
            df = hdf5Reader(fpath, logger, selected_keys=["a/one", "a/two"]).read()

        assert df is None
        assert "share one grid" in caplog.text

    def test_oversized_selection_is_refused(self, tmp_path, logger, caplog, monkeypatch):
        fpath = str(tmp_path / "grid.h5")
        self._write(fpath)
        monkeypatch.setenv("AIDRIN_HDF5_MAX_GRID_BYTES", "16")

        with caplog.at_level(logging.WARNING):
            df = hdf5Reader(fpath, logger, selected_keys=["t0_fields/density"]).read()

        assert df is None
        assert "ceiling" in caplog.text

    def test_size_is_checked_before_loading(self, tmp_path, logger, monkeypatch):
        """The ceiling exists for tables that will not fit, so it must not build one."""
        fpath = str(tmp_path / "grid.h5")
        self._write(fpath)
        monkeypatch.setenv("AIDRIN_HDF5_MAX_GRID_BYTES", "16")

        def _boom(self, item):
            raise AssertionError("dataset was materialized before the size check")

        monkeypatch.setattr(h5py.Dataset, "__getitem__", _boom)

        assert hdf5Reader(fpath, logger, selected_keys=["t0_fields/density"]).read() is None

    def test_grid_without_a_selection_is_still_refused(self, tmp_path, logger):
        """No selection means no intent; the file stays ambiguous."""
        fpath = str(tmp_path / "grid.h5")
        self._write(fpath)

        assert hdf5Reader(fpath, logger).read() is None

    def test_lone_vector_field_splits_using_the_grid_its_neighbours_share(self, tmp_path, logger):
        """Selected alone, a vector field must not interleave its components.

        Its own shape cannot say whether the trailing axis is a component or
        another spatial dimension. The grid the rest of the file sits on can,
        without reference to any particular project's metadata.
        """
        fpath = str(tmp_path / "grid.h5")
        self._write(fpath)

        df = hdf5Reader(fpath, logger, selected_keys=["t1_fields/velocity"]).read()

        assert list(df.columns) == ["t1_fields/velocity_0", "t1_fields/velocity_1"]
        assert len(df) == 120, "one row per grid cell, not per stored element"
        raw = np.arange(240, dtype="f4").reshape(2, 3, 4, 5, 2)
        np.testing.assert_array_equal(
            df["t1_fields/velocity_0"].values, raw[..., 0].reshape(-1)
        )

    def test_lone_high_rank_field_warns_with_no_grid_to_compare_against(self, tmp_path, logger, caplog):
        """With no neighbours on a shared grid, say so rather than guess silently."""
        fpath = str(tmp_path / "solo_vector.h5")
        with h5py.File(fpath, "w") as f:
            # Every dataset a different shape, so nothing establishes a grid.
            f.create_dataset("a/vector", data=np.zeros((2, 3, 4, 2), dtype="f4"))
            f.create_dataset("a/other", data=np.zeros((5, 6), dtype="f4"))
            f.create_dataset("a/more", data=np.zeros((7, 8, 9), dtype="f4"))
            f.create_dataset("a/extra", data=np.zeros((3,), dtype="f4"))

        with caplog.at_level(logging.WARNING):
            df = hdf5Reader(fpath, logger, selected_keys=["a/vector"]).read()

        assert df is not None
        assert "no other dataset in the file shares a grid" in caplog.text

    def test_one_field_sitting_on_the_grid_is_evidence_enough(self, tmp_path, logger):
        """A neighbour stopping where the vector's components begin locates the grid."""
        fpath = str(tmp_path / "pair.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("a/vector", data=np.zeros((2, 3, 4, 2), dtype="f4"))
            f.create_dataset("a/scalar", data=np.zeros((2, 3, 4), dtype="f4"))
            f.create_dataset("a/other", data=np.zeros((9, 9), dtype="f4"))
            f.create_dataset("a/more", data=np.zeros((5,), dtype="f4"))

        df = hdf5Reader(fpath, logger, selected_keys=["a/vector"]).read()

        assert len(df) == 2 * 3 * 4, "the grid is where the neighbour stops"
        assert list(df.columns) == ["a/vector_0", "a/vector_1"]

    def test_wider_fields_cannot_outvote_the_grid(self, tmp_path, logger):
        """Counting exact shapes let the widest fields elect themselves the grid.

        Real datasets carry more tensor fields than scalar ones, so two tensors
        at (*grid, D, D) outvoted the single scalar at (*grid) and folded their
        components into rows.
        """
        fpath = str(tmp_path / "tensors.h5")
        grid = (2, 3, 4)
        with h5py.File(fpath, "w") as f:
            f.create_dataset("t0/scalar", data=np.zeros(grid, dtype="f4"))
            f.create_dataset("t1/vec", data=np.zeros(grid + (2,), dtype="f4"))
            f.create_dataset("t2/D", data=np.zeros(grid + (2, 2), dtype="f4"))
            f.create_dataset("t2/E", data=np.zeros(grid + (2, 2), dtype="f4"))

        df = hdf5Reader(fpath, logger, selected_keys=["t2/D"]).read()

        assert len(df) == 2 * 3 * 4, "one row per grid cell, not per tensor entry"
        assert list(df.columns) == ["t2/D_0_0", "t2/D_0_1", "t2/D_1_0", "t2/D_1_1"]

    def test_scalar_field_selected_alone_does_not_warn(self, tmp_path, logger, caplog):
        """The warning above must not fire for an ordinary scalar field."""
        fpath = str(tmp_path / "grid.h5")
        self._write(fpath)

        with caplog.at_level(logging.WARNING):
            df = hdf5Reader(fpath, logger, selected_keys=["t0_fields/density"]).read()

        assert df.shape == (120, 1)
        assert "cannot be told" not in caplog.text

    def test_single_dataset_file_honours_its_selection(self, tmp_path, logger):
        """A file holding one grid is typed 'single_dataset' and skipped the dispatch."""
        fpath = str(tmp_path / "solo.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("field", data=np.arange(24, dtype="f4").reshape(2, 3, 4))

        df = hdf5Reader(fpath, logger, selected_keys=["field"]).read()

        assert df is not None
        assert df.shape == (24, 1)
        np.testing.assert_array_equal(df["field"].values, np.arange(24, dtype="f4"))

    def test_budget_accounts_for_fill_value_promotion(self, tmp_path, logger, caplog, monkeypatch):
        """Replacing a fill sentinel casts to float64, so project the wider type."""
        fpath = str(tmp_path / "fill.h5")
        with h5py.File(fpath, "w") as f:
            for name in ("a", "b"):
                d = f.create_dataset("g/" + name, shape=(2, 3, 4), dtype="f4", fillvalue=-999.0)
                d[...] = np.arange(24, dtype="f4").reshape(2, 3, 4)
            f.create_dataset("g/c", data=np.arange(24, dtype="f4").reshape(2, 3, 4))

        # 24 cells * 1 column: 96 bytes as float32, 192 as float64.
        monkeypatch.setenv("AIDRIN_HDF5_MAX_GRID_BYTES", "150")

        with caplog.at_level(logging.WARNING):
            df = hdf5Reader(fpath, logger, selected_keys=["g/a"]).read()

        assert df is None
        assert "ceiling" in caplog.text

    def test_dominant_grid_is_independent_of_walk_order(self, tmp_path, logger):
        """Two shapes can be equally common; the answer must not depend on order."""
        fpath = str(tmp_path / "tie.h5")
        with h5py.File(fpath, "w") as f:
            for name in ("a", "b"):
                f.create_dataset("g/" + name, data=np.zeros((4, 5), dtype="f4"))
            for name in ("c", "d"):
                f.create_dataset("g/" + name, data=np.zeros((5, 4), dtype="f4"))

        answers = {hdf5Reader(fpath, logger)._dominant_grid_shape() for _ in range(5)}

        assert len(answers) == 1

    def test_a_selection_off_the_dominant_grid_still_reads(self, tmp_path, logger):
        """The file's majority grid must not override a selection that shares another."""
        fpath = str(tmp_path / "two_grids.h5")
        with h5py.File(fpath, "w") as f:
            for i in range(5):
                f.create_dataset("big/f%d" % i, data=np.zeros((8, 9, 10), dtype="f4"))
            for i in range(2):
                f.create_dataset("small/g%d" % i, data=np.zeros((3, 4, 5), dtype="f4"))

        df = hdf5Reader(fpath, logger, selected_keys=["small/g0", "small/g1"]).read()

        assert df is not None
        assert df.shape == (3 * 4 * 5, 2)

    def test_rank_two_arrays_do_not_trigger_the_component_warning(self, tmp_path, logger, caplog):
        """A short second axis on a rank-2 array is an ordinary table, not components."""
        fpath = str(tmp_path / "flat.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("a/pairs", data=np.zeros((100, 3, 2), dtype="f4"))
            f.create_dataset("a/other", data=np.zeros((7, 8), dtype="f4"))
            f.create_dataset("a/more", data=np.zeros((9, 10, 11), dtype="f4"))
            f.create_dataset("a/extra", data=np.zeros((5,), dtype="f4"))

        with caplog.at_level(logging.WARNING):
            hdf5Reader(fpath, logger, selected_keys=["a/pairs"]).read()

        # rank 3 with a trailing 2 is a plausible vector field, so this one warns
        assert "no other dataset in the file shares a grid" in caplog.text

    def test_an_array_dtype_is_refused(self, tmp_path, logger, caplog):
        """A dtype can carry its own dimension, and then shape understates a cell.

        A (4, 3, 2) dataset of dtype ('<i4', (3,)) reads back as (4, 3, 2, 3),
        so counting its shape gives three values for every grid cell. Too rare
        to model, and silently mis-counting rows is the thing to avoid.
        """
        fpath = str(tmp_path / "arraydtype.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("g/vec", shape=(4, 3, 2), dtype=np.dtype(("<i4", (3,))))
            f.create_dataset("g/plain", data=np.zeros((4, 3, 2), dtype="u1"))
            f.create_dataset("g/other", data=np.zeros((4, 3, 2), dtype="u1"))

        with caplog.at_level(logging.WARNING):
            df = hdf5Reader(fpath, logger, selected_keys=["g/vec", "g/plain"]).read()

        assert df is None
        assert "array dtype" in caplog.text

    def test_a_coordinate_array_cannot_pose_as_the_grid(self, tmp_path, logger):
        """A per-sample coordinate precedes every field but is not the grid.

        Real datasets store a 2D time array at (S, T) alongside fields at
        (S, T, Y, X). Counting prefixes alone elected (S, T), which turned each
        field's spatial extent into a quarter of a million columns.
        """
        fpath = str(tmp_path / "coords.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("dimensions/time", data=np.zeros((2, 5), dtype="f4"))
            f.create_dataset("t0_fields/a", data=np.zeros((2, 5, 16, 16), dtype="f4"))
            f.create_dataset("t0_fields/b", data=np.zeros((2, 5, 16, 16), dtype="f4"))
            f.create_dataset("t1_fields/v", data=np.zeros((2, 5, 16, 16, 2), dtype="f4"))

        reader = hdf5Reader(fpath, logger, selected_keys=["t1_fields/v"])

        assert reader._dominant_grid_shape() == (2, 5, 16, 16)
        df = reader.read()
        assert len(df) == 2 * 5 * 16 * 16
        assert list(df.columns) == ["t1_fields/v_0", "t1_fields/v_1"]

    def test_same_shape_two_dimensional_fields_share_a_grid(self, tmp_path, logger):
        """Several 2D datasets of one shape are fields on a grid, not tables each.

        A single 2D dataset stays an ordinary table; only a selection of them
        flattens, which is how netCDF and PDE benchmarks store a static field
        beside its coordinates.
        """
        fpath = str(tmp_path / "flat_fields.h5")
        with h5py.File(fpath, "w") as f:
            f.create_dataset("depth", data=np.arange(12, dtype="f4").reshape(3, 4))
            f.create_dataset("lat", data=np.arange(12, dtype="f4").reshape(3, 4))
            f.create_dataset("lon", data=np.arange(12, dtype="f4").reshape(3, 4))
            f.create_dataset("time", data=np.arange(7, dtype="f4"))

        df = hdf5Reader(fpath, logger, selected_keys=["depth", "lat", "lon"]).read()
        assert df.shape == (12, 3)

        single = hdf5Reader(fpath, logger, selected_keys=["depth"]).read()
        assert single.shape == (3, 4), "one 2D dataset is still a table"

    def test_an_image_is_refused_rather_than_scored(self, tmp_path, logger, caplog):
        """Images flatten into a table perfectly well and mean nothing there.

        A real photograph scored a duplicity of 0.4, which only says many pixels
        share a colour, and an outlier fraction over its channels. AIDRIN
        assesses tabular data, so it should say so instead.
        """
        fpath = str(tmp_path / "image.h5")
        with h5py.File(fpath, "w") as f:
            d = f.create_dataset("rgb", data=np.zeros((4, 5, 3), dtype="u1"))
            d.attrs["CLASS"] = np.bytes_("IMAGE")
            d.attrs["IMAGE_SUBCLASS"] = np.bytes_("IMAGE_TRUECOLOR")
            f.create_dataset("other", data=np.zeros((4, 5), dtype="u1"))
            f.create_dataset("more", data=np.zeros((4, 5), dtype="u1"))

        with caplog.at_level(logging.WARNING):
            df = hdf5Reader(fpath, logger, selected_keys=["rgb"]).read()

        assert df is None
        assert "does not support images" in caplog.text

    def test_a_two_dimensional_image_is_refused_too(self, tmp_path, logger):
        """An indexed image is rank 2, so it reaches the single-dataset path.

        The web picker already rejected it there while the reader read it as a
        table of pixel rows, so the two disagreed about the same file.
        """
        fpath = str(tmp_path / "indexed.h5")
        with h5py.File(fpath, "w") as f:
            d = f.create_dataset("indexed", data=np.zeros((40, 30), dtype="u1"))
            d.attrs["CLASS"] = np.bytes_("IMAGE")
            d.attrs["IMAGE_SUBCLASS"] = np.bytes_("IMAGE_INDEXED")
            f.create_dataset("other", data=np.zeros((4, 5), dtype="u1"))
            f.create_dataset("more", data=np.zeros((4, 5), dtype="u1"))

        reader = hdf5Reader(fpath, logger, selected_keys=["indexed"])

        assert reader.read() is None
        assert "does not support images" in reader.validate_selection(["indexed"])

    def test_a_grid_frame_says_what_a_row_is(self, tmp_path, logger):
        """A row is a grid cell, and a metric counting rows needs to know."""
        from aidrin.file_handling.row_units import row_unit

        fpath = str(tmp_path / "grid.h5")
        self._write(fpath)

        df = hdf5Reader(
            fpath, logger, selected_keys=["t0_fields/density", "t0_fields/pressure"]
        ).read()

        assert row_unit(df) == "grid cell"
