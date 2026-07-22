"""Normalize unhashable cell values so pandas set-based operations work.

pandas operations that hash values — ``nunique()``, ``duplicated()``,
``value_counts()``, ``groupby()`` — raise ``TypeError: unhashable type`` on
object columns holding arrays, lists, dicts or sets. Parquet, HDF5 and JSON
datasets routinely carry such columns (e.g. a per-node measurement array), so
any code that counts distinct values must normalize them first or it will fail
on a whole class of real datasets.

Converting to nested tuples preserves value equality, so distinct-counting and
duplicate detection stay correct — two rows with equal arrays still compare
equal after conversion.
"""

import numpy as np
import pandas as pd


def make_hashable(value):
    """Recursively convert an unhashable value to a hashable equivalent.

    Arrays/lists/tuples become tuples, dicts become sorted key/value tuples, and
    sets become sorted tuples. Scalars pass through untouched.
    """
    if isinstance(value, np.ndarray):
        return tuple(make_hashable(v) for v in value.tolist())
    if isinstance(value, (list, tuple)):
        return tuple(make_hashable(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in value.items()))
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(make_hashable(v) for v in value))
    return value


def is_unhashable_column(series: pd.Series) -> bool:
    """Whether *series* holds values pandas cannot hash.

    Only object columns can carry such values; the first non-null value is used
    as the probe, matching how the rest of the codebase samples column contents.
    """
    if series.dtype != object:
        return False
    non_null = series.dropna()
    if non_null.empty:
        return False
    return isinstance(
        non_null.iloc[0], (np.ndarray, list, tuple, dict, set, frozenset)
    )


def hashable_series(series: pd.Series) -> pd.Series:
    """Return *series* with unhashable values converted, else unchanged."""
    if is_unhashable_column(series):
        return series.apply(make_hashable)
    return series


def hashable_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of *df* with every unhashable object column converted."""
    out = df.copy()
    for col in out.columns:
        if is_unhashable_column(out[col]):
            out[col] = out[col].apply(make_hashable)
    return out


def safe_nunique(series: pd.Series, dropna: bool = True) -> int:
    """``nunique()`` that tolerates unhashable values.

    Tries the fast path first and only converts on failure, so mixed columns
    (whose first value looks hashable but whose later values do not) are handled
    too — a case the first-value probe alone would miss.
    """
    try:
        return int(series.nunique(dropna=dropna))
    except TypeError:
        return int(series.apply(make_hashable).nunique(dropna=dropna))
