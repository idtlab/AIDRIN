"""Tests for semantic column-role inference (continuous / categorical / identifier)."""

import numpy as np
import pandas as pd

from web.routes.utils import infer_column_roles


def _df(n=1000):
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            # genuine continuous float measures
            "pt": rng.normal(50, 10, n).astype("float32"),
            "eta": rng.normal(0, 2, n).astype("float32"),
            # low-cardinality integer code -> categorical
            "flavor": rng.choice([-1, 1, 2, 5, 21], n).astype("int32"),
            # near-unique integer -> identifier (by cardinality)
            "jetIndex": np.arange(n, dtype="uint64"),
            # moderate-cardinality integer with id-like name -> identifier (by name)
            "eventIndex": rng.integers(0, n // 5, n).astype("uint64"),
            # genuine string column -> categorical
            "label": rng.choice(["a", "b", "c"], n),
        }
    )


def test_continuous_floats():
    roles = infer_column_roles(_df())
    assert roles["pt"] == "continuous"
    assert roles["eta"] == "continuous"


def test_low_cardinality_int_is_categorical():
    roles = infer_column_roles(_df())
    assert roles["flavor"] == "categorical"


def test_near_unique_int_is_identifier():
    roles = infer_column_roles(_df())
    assert roles["jetIndex"] == "identifier"


def test_idlike_name_with_moderate_cardinality_is_identifier():
    roles = infer_column_roles(_df())
    assert roles["eventIndex"] == "identifier"


def test_string_column_is_categorical():
    roles = infer_column_roles(_df())
    assert roles["label"] == "categorical"


def test_user_override_wins():
    roles = infer_column_roles(_df(), overrides={"flavor": "continuous", "pt": "categorical"})
    assert roles["flavor"] == "continuous"
    assert roles["pt"] == "categorical"


def test_invalid_override_ignored():
    roles = infer_column_roles(_df(), overrides={"flavor": "bogus", "missing": "categorical"})
    assert roles["flavor"] == "categorical"  # heuristic retained
    assert "missing" not in roles


def test_bool_column_is_categorical():
    df = pd.DataFrame({"flag": [True, False, True, False] * 10})
    assert infer_column_roles(df)["flag"] == "categorical"


def test_empty_dataframe():
    assert infer_column_roles(pd.DataFrame()) == {}


def test_small_dataset_all_distinct_int_is_continuous():
    # In a tiny dataset every value is trivially distinct — a numeric column
    # must not be mistaken for an identifier or (via low nunique) a category.
    df = pd.DataFrame({"age": [25, 30, 35], "active": [True, False, True]})
    roles = infer_column_roles(df)
    assert roles["age"] == "continuous"
    assert roles["active"] == "categorical"


def test_identifier_requires_enough_distinct_values():
    # An id-like name with only a handful of distinct values in a small dataset
    # should not be forced to "identifier".
    df = pd.DataFrame({"user_id": [1, 2, 3, 4, 5]})
    assert infer_column_roles(df)["user_id"] != "identifier"
