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
