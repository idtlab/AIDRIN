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
import pytest

from aidrin.file_handling.readers.hdf5_reader import hdf5Reader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def logger():
    return logging.getLogger("test_hdf5_reader")


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
# Uncertain fill-value source: HDF5 default zero (WARNING expected)
# ---------------------------------------------------------------------------

class TestUncertainFillValues:

    def test_zero_default_fillvalue_emits_warning(self, tmp_path, logger, caplog):
        """HDF5 default zero fillvalue (no attrs) triggers a WARNING before replacement."""
        data = np.array([0, 1, 2, 0, 4], dtype=np.int32)
        # No explicit fillvalue → h5py defaults to 0 for int32

        with caplog.at_level(logging.WARNING):
            _read_col(tmp_path, logger, data)

        assert any("default fill value" in r.message for r in caplog.records)

    def test_zero_default_fillvalue_still_replaced(self, tmp_path, logger):
        """Zeros are replaced with NaN even when a WARNING is emitted."""
        data = np.array([0, 1, 2, 0, 4], dtype=np.int32)
        col = _read_col(tmp_path, logger, data)

        assert col.isna().sum() == 2

    def test_warning_includes_replacement_count(self, tmp_path, logger, caplog):
        """The WARNING message reports how many values will be replaced."""
        data = np.array([0.0, 1.0, 0.0], dtype=np.float64)

        with caplog.at_level(logging.WARNING):
            _read_col(tmp_path, logger, data)

        warning_msgs = [r.message for r in caplog.records if "default fill value" in r.message]
        assert len(warning_msgs) == 1
        # Message should contain the count "2" and total "3"
        assert "2" in warning_msgs[0]
        assert "3" in warning_msgs[0]

    def test_zero_fillvalue_with_fill_attr_warns_zero_keeps_valid(self, tmp_path, logger, caplog):
        """
        When _FillValue attr is -9999.0 and HDF5 native fillvalue defaults to 0.0,
        zeros are still uncertain and emit a WARNING — they are NOT silently collapsed
        into explicit alongside the -9999.0 sentinel.  This guards against the bug
        where has_fill_attrs=True caused default zeros to be added to explicit,
        silently replacing legitimate zero measurements.
        """
        data = np.array([0.0, 1.0, -9999.0, 3.0], dtype=np.float64)

        with caplog.at_level(logging.WARNING):
            col = _read_col(tmp_path, logger, data, attrs={"_FillValue": -9999.0})

        # The -9999.0 sentinel is replaced (explicit)
        assert math.isnan(float(col[col.index[2]]))
        # 0.0 is replaced too (uncertain), but a WARNING was emitted
        assert any("default fill value" in r.message for r in caplog.records)
        # Valid measurements 1.0 and 3.0 survive
        non_nan = col.dropna().tolist()
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


# ---------------------------------------------------------------------------
# Multi-group guard: read() must reject files with multiple top-level groups
# ---------------------------------------------------------------------------

def _make_multigroup_hdf5(path, groups):
    """Write an HDF5 file with multiple top-level groups, each holding one dataset."""
    with h5py.File(path, "w") as f:
        for group_name, data in groups.items():
            g = f.create_group(group_name)
            g.create_dataset("data", data=data)


class TestMultiGroupGuard:

    def test_read_raises_on_multiple_top_level_groups(self, tmp_path, logger):
        """
        hdf5Reader.read() must raise ValueError when the file has more than one
        top-level group. Previously it would silently concatenate all groups into
        a single misaligned DataFrame, causing wrong completeness scores.
        """
        fpath = str(tmp_path / "multi.h5")
        _make_multigroup_hdf5(fpath, {
            "sensors": np.arange(100, dtype=np.float64),
            "waveforms": np.random.rand(50, 16),
        })

        with pytest.raises(ValueError, match="multiple top-level groups"):
            hdf5Reader(fpath, logger).read()

    def test_error_message_lists_group_names(self, tmp_path, logger):
        """The ValueError message should name the offending groups so the user knows what to pick."""
        fpath = str(tmp_path / "multi.h5")
        _make_multigroup_hdf5(fpath, {
            "injection": np.array([1.0, 2.0, 3.0]),
            "seismicity": np.array([4.0, 5.0, 6.0]),
        })

        with pytest.raises(ValueError) as exc_info:
            hdf5Reader(fpath, logger).read()

        msg = str(exc_info.value)
        assert "injection" in msg
        assert "seismicity" in msg

    def test_single_group_file_reads_without_error(self, tmp_path, logger):
        """A file with exactly one top-level group should still read fine."""
        fpath = str(tmp_path / "single.h5")
        with h5py.File(fpath, "w") as f:
            g = f.create_group("sensors")
            g.create_dataset("temperature", data=np.array([20.0, 21.0, 22.0]))

        df = hdf5Reader(fpath, logger).read()
        assert df is not None
        assert not df.empty

    def test_completeness_not_inflated_by_group_misalignment(self, tmp_path, logger):
        """
        Regression: before the guard, uploading a file with groups of different
        shapes produced a NaN-padded DataFrame. completeness() would report low
        scores on a fully-populated dataset. Verify the guard prevents this by
        ensuring a single-group file reports 100% completeness.
        """
        fpath = str(tmp_path / "single_full.h5")
        with h5py.File(fpath, "w") as f:
            g = f.create_group("measurements")
            g.create_dataset("pressure", data=np.ones(200, dtype=np.float64))

        df = hdf5Reader(fpath, logger).read()
        assert df is not None

        overall_completeness = 1 - df.isnull().any(axis=1).mean()
        assert overall_completeness == 1.0, (
            f"Expected 100% completeness for a fully-populated single-group file, "
            f"got {overall_completeness:.2%}."
        )
