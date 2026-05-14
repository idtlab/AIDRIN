"""Regression tests for string-based dtype guards (fix/dtype-string-guards).

These tests verify that metric functions correctly handle narrow numeric types
(int32, float32) and pandas 2.x StringDtype columns, which the original
string-based comparisons (dtype in ['int64', 'float64'], dtype == 'object',
select_dtypes(include='object')) silently missed.
"""

import sys
import types
import unittest

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Pre-stub heavy modules so aidrin can be imported without a running app.
# ---------------------------------------------------------------------------

# pkg_resources stub (removed from Python 3.13 stdlib without setuptools;
# needed by dython which is imported transitively by aidrin).
if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        def __init__(self):
            self.version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

# aidrin.file_handling.file_parser stub — privacy_measure.py imports read_file
# at module level, which triggers file_parser → readers → Flask context deps.
# Stubbing the module in sys.modules before any aidrin import prevents that.
# We do NOT stub 'aidrin' itself so the real package is still loaded.
if "aidrin.file_handling.file_parser" not in sys.modules:

    class _FileParserStub(types.ModuleType):
        read_file = staticmethod(lambda x: x)
        SUPPORTED_FILE_TYPES = []
        READER_MAP = {}

        def __getattr__(self, name):
            return None

    _fp = _FileParserStub("aidrin.file_handling.file_parser")
    sys.modules["aidrin.file_handling.file_parser"] = _fp

# ---------------------------------------------------------------------------
# Import functions under test (after stubs are in place)
# ---------------------------------------------------------------------------

from aidrin.structured_data_metrics.class_imbalance import calc_imbalance_degree  # noqa: E402
from aidrin.structured_data_metrics.privacy_measure import (  # noqa: E402
    generate_single_attribute_MM_risk_scores,
)


# ===========================================================================
# class_imbalance.py — calc_imbalance_degree
# ===========================================================================


class TestCalcImbalanceDegreeNarrowDtypes(unittest.TestCase):
    """float32/int32 columns with many unique values must be caught as numeric."""

    def _many_unique(self, dtype):
        return pd.DataFrame({"target": np.arange(200, dtype=dtype)})

    # calc_imbalance_degree catches ValueError internally and returns {"Error": ...}
    # rather than re-raising, so we check the returned dict, not raised exceptions.

    # --- regression: narrow types now rejected (were silently passed before) ---

    def test_float32_many_unique_rejects(self):
        result = calc_imbalance_degree(self._many_unique(np.float32), "target")
        self.assertIn("Error", result, "float32 with 200 uniques should return an error dict")

    def test_int32_many_unique_rejects(self):
        result = calc_imbalance_degree(self._many_unique(np.int32), "target")
        self.assertIn("Error", result, "int32 with 200 uniques should return an error dict")

    def test_uint16_many_unique_rejects(self):
        result = calc_imbalance_degree(self._many_unique(np.uint16), "target")
        self.assertIn("Error", result, "uint16 with 200 uniques should return an error dict")

    # --- existing dtypes still caught ---

    def test_float64_many_unique_rejects(self):
        result = calc_imbalance_degree(self._many_unique(np.float64), "target")
        self.assertIn("Error", result)

    def test_int64_many_unique_rejects(self):
        result = calc_imbalance_degree(self._many_unique(np.int64), "target")
        self.assertIn("Error", result)

    # --- few unique values → accepted (valid categorical-encoded column) ---

    def test_float32_few_unique_passes(self):
        df = pd.DataFrame(
            {"target": pd.array([1.0, 2.0, 3.0, 1.0, 2.0] * 10, dtype="float32")}
        )
        result = calc_imbalance_degree(df, "target")
        self.assertNotIn("Error", result)
        self.assertIn("Imbalance Degree score", result)

    def test_int32_few_unique_passes(self):
        df = pd.DataFrame(
            {"target": pd.array([0, 1, 2, 0, 1] * 10, dtype="int32")}
        )
        result = calc_imbalance_degree(df, "target")
        self.assertNotIn("Error", result)
        self.assertIn("Imbalance Degree score", result)


# ===========================================================================
# privacy_measure.py — generate_single_attribute_MM_risk_scores
# ===========================================================================


class TestGenerateSingleAttributeRiskNarrowDtypes(unittest.TestCase):
    """float32/int32 quasi-id columns with high cardinality must be rejected."""

    def _high_cardinality_df(self, qi_dtype):
        n = 200  # > 100 unique values threshold
        return pd.DataFrame(
            {
                "id": np.arange(n),
                "qi": np.arange(n, dtype=qi_dtype),
            }
        )

    # --- regression: narrow types now rejected ---

    def test_float32_high_cardinality_rejects(self):
        result = generate_single_attribute_MM_risk_scores(
            self._high_cardinality_df(np.float32), "id", ["qi"]
        )
        self.assertIn("Error", result)
        self.assertIn("numerical", result["Error"].lower())

    def test_int32_high_cardinality_rejects(self):
        result = generate_single_attribute_MM_risk_scores(
            self._high_cardinality_df(np.int32), "id", ["qi"]
        )
        self.assertIn("Error", result)
        self.assertIn("numerical", result["Error"].lower())

    def test_uint16_high_cardinality_rejects(self):
        result = generate_single_attribute_MM_risk_scores(
            self._high_cardinality_df(np.uint16), "id", ["qi"]
        )
        self.assertIn("Error", result)

    # --- existing dtypes still caught ---

    def test_float64_high_cardinality_rejects(self):
        result = generate_single_attribute_MM_risk_scores(
            self._high_cardinality_df(np.float64), "id", ["qi"]
        )
        self.assertIn("Error", result)

    def test_int64_high_cardinality_rejects(self):
        result = generate_single_attribute_MM_risk_scores(
            self._high_cardinality_df(np.int64), "id", ["qi"]
        )
        self.assertIn("Error", result)


# ===========================================================================
# correlation_score.py — select_dtypes dtype classification (fixed logic)
# ===========================================================================


class TestSelectDtypesStringClassification(unittest.TestCase):
    """
    The fixed select_dtypes expressions classify pd.StringDtype() columns as
    categorical, not numerical.  These tests duplicate the logic from
    calc_correlations() lines 24-25 so we can verify them without Celery.
    """

    _CATEGORICAL_INCLUDE = ["object", "string", "category"]
    _NUMERICAL_EXCLUDE = ["object", "string", "category"]

    def _classify(self, df, col):
        cat = df.select_dtypes(include=self._CATEGORICAL_INCLUDE).columns
        if col in cat:
            return "categorical"
        num = df.select_dtypes(exclude=self._NUMERICAL_EXCLUDE).columns
        if col in num:
            return "numerical"
        return "unclassified"

    # --- regression: StringDtype now treated as categorical ---

    def test_string_dtype_is_categorical(self):
        df = pd.DataFrame({"s": pd.array(["a", "b", "c"], dtype=pd.StringDtype())})
        self.assertEqual(self._classify(df, "s"), "categorical")

    def test_category_dtype_is_categorical(self):
        df = pd.DataFrame({"cat": pd.Categorical(["x", "y", "x"])})
        self.assertEqual(self._classify(df, "cat"), "categorical")

    # --- existing behavior preserved ---

    def test_object_dtype_is_categorical(self):
        df = pd.DataFrame({"s": ["a", "b", "c"]})
        self.assertEqual(self._classify(df, "s"), "categorical")

    def test_float32_is_numerical(self):
        df = pd.DataFrame({"n": pd.array([1.0, 2.0, 3.0], dtype="float32")})
        self.assertEqual(self._classify(df, "n"), "numerical")

    def test_int32_is_numerical(self):
        df = pd.DataFrame({"n": pd.array([1, 2, 3], dtype="int32")})
        self.assertEqual(self._classify(df, "n"), "numerical")

    def test_float64_is_numerical(self):
        df = pd.DataFrame({"n": [1.0, 2.0, 3.0]})
        self.assertEqual(self._classify(df, "n"), "numerical")

    def test_int64_is_numerical(self):
        df = pd.DataFrame({"n": [1, 2, 3]})
        self.assertEqual(self._classify(df, "n"), "numerical")

    # --- pre-fix behaviour: StringDtype would fall into numerical (regression guard) ---

    def test_old_include_object_misses_string_dtype(self):
        """Demonstrates the pre-fix bug: select_dtypes(include='object') omits StringDtype."""
        df = pd.DataFrame({"s": pd.array(["a", "b", "c"], dtype=pd.StringDtype())})
        old_categorical = df.select_dtypes(include="object").columns
        self.assertNotIn(
            "s",
            old_categorical,
            "StringDtype column must NOT appear in old-style select_dtypes(include='object') "
            "— confirming the bug we fixed.",
        )


# ===========================================================================
# feature_relevance.py — target column dtype detection (fixed logic)
# ===========================================================================


class TestTargetColDtypeDetection(unittest.TestCase):
    """
    The fixed condition in data_cleaning() detects pd.StringDtype() target
    columns in addition to object-dtype columns, triggering label encoding.
    """

    def _is_string_target(self, series):
        """Mirrors the fixed condition at feature_relevance.py line 231."""
        return pd.api.types.is_object_dtype(series) or isinstance(
            series.dtype, pd.StringDtype
        )

    # --- regression: StringDtype now detected ---

    def test_string_dtype_detected(self):
        s = pd.Series(pd.array(["a", "b", "c"], dtype=pd.StringDtype()))
        self.assertTrue(self._is_string_target(s))

    # --- existing behaviour preserved ---

    def test_object_dtype_detected(self):
        s = pd.Series(["a", "b", "c"])
        self.assertTrue(self._is_string_target(s))

    def test_float32_not_string(self):
        s = pd.Series(pd.array([1.0, 2.0, 3.0], dtype="float32"))
        self.assertFalse(self._is_string_target(s))

    def test_int32_not_string(self):
        s = pd.Series(pd.array([1, 2, 3], dtype="int32"))
        self.assertFalse(self._is_string_target(s))

    def test_float64_not_string(self):
        s = pd.Series([1.0, 2.0, 3.0])
        self.assertFalse(self._is_string_target(s))

    def test_int64_not_string(self):
        s = pd.Series([1, 2, 3])
        self.assertFalse(self._is_string_target(s))

    # --- pre-fix regression guard ---

    def test_old_check_misses_string_dtype(self):
        """Demonstrates the pre-fix bug: dtype == 'object' misses StringDtype."""
        s = pd.Series(pd.array(["a", "b", "c"], dtype=pd.StringDtype()))
        old_result = s.dtype == "object"
        self.assertFalse(
            old_result,
            "StringDtype must NOT equal 'object' — confirming the bug we fixed.",
        )


if __name__ == "__main__":
    unittest.main()
