"""ROOT TTree reader via ``uproot`` (core dependency).

AIDRIN metrics require a tabular DataFrame; this reader loads one TTree at a
time into pandas.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader
from aidrin.file_handling.readers.structured import (
    DROPPED_COLUMNS_ATTR,
    INVENTORY_EMPTY,
    INVENTORY_SINGLE,
    INVENTORY_MULTI,
    InventoryResult,
    make_inventory,
)


def _require_uproot():
    try:
        import uproot
    except ImportError as exc:
        raise ImportError(
            "Reading ROOT (.root) files requires 'uproot'. "
            "Reinstall AIDRIN or run: pip install uproot"
        ) from exc
    return uproot


def _is_jagged(series: pd.Series) -> bool:
    """True when the column holds per-row sequences (array-valued branches).

    uproot loads jagged branches (``vector<float>`` etc.) as object columns
    whose cells are arrays; those are not tabular and break any metric that
    hashes or aggregates cell values. An extension dtype (not a plain numpy
    dtype, e.g. awkward-pandas) is inspected too, since those stacks hold
    sequences under a non-object dtype. Cells are sampled rather than trusting
    the first one, so a column whose early rows happen to be scalar still gets
    caught.
    """
    if isinstance(series.dtype, np.dtype) and series.dtype.kind != "O":
        return False
    non_null = series.dropna()
    if non_null.empty:
        return False
    return any(
        hasattr(value, "__len__") and not isinstance(value, (str, bytes))
        for value in non_null.head(50)
    )


def _branch_typenames(tree) -> dict:
    """``{branch name: ROOT type name}`` for a TTree or an RNTuple."""
    typenames = tree.typenames
    return typenames() if callable(typenames) else dict(typenames)


def _is_array_typename(typename) -> bool:
    """True for ROOT types that hold a sequence per entry.

    Covers ``std::vector<float>``, ``float[]``, ``float[3]``, ``std::map<...>``
    and friends; plain scalars (``float``, ``std::int32_t``, ``std::string``)
    carry neither bracket.
    """
    text = str(typename)
    return "[" in text or "<" in text


def _strip_cycle(name: str) -> str:
    """Normalize ``tree;1`` style keys to ``tree``."""
    if ";" in name:
        return name.split(";", 1)[0]
    return name


class rootReader(BaseFileReader):
    def __init__(self, file_path: str, logger, selected_keys=None):
        super().__init__(file_path, logger)
        # Tree path(s). None = auto (single tree) or require selection when many.
        self._explicit_selected_keys = selected_keys

    def inventory(self) -> InventoryResult:
        uproot = _require_uproot()
        datasets = []
        with uproot.open(self.file_path) as handle:
            for name in self._list_trees():
                tree = handle[name]
                rows, columns = int(tree.num_entries), len(tree.keys())
                datasets.append({
                    "path": name,
                    "shape": (rows, columns),
                    "ndim": 2,
                    "dtype": "ROOT tree",
                    "size": rows * columns,
                })
        kind = INVENTORY_EMPTY if not datasets else INVENTORY_SINGLE if len(datasets) == 1 else INVENTORY_MULTI
        return make_inventory(kind, datasets)

    def _list_trees(self) -> List[str]:
        uproot = _require_uproot()
        trees: List[str] = []
        with uproot.open(self.file_path) as handle:
            for key, obj in handle.items():
                # TTree / RNTuple-like objects expose arrays(); skip directories/histograms.
                if hasattr(obj, "arrays"):
                    trees.append(_strip_cycle(str(key)))
        # Stable unique order
        seen = set()
        unique = []
        for name in trees:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        return unique

    def parse(self):
        """Return TTree names for the web key picker."""
        try:
            return self._list_trees()
        except Exception as exc:
            self.logger.error("ROOT parse failed: %s", exc)
            return str(exc)

    def _resolve_tree_name(self) -> str | None:
        """The tree to read, or ``None`` when the file cannot pick one itself.

        Returning None rather than raising lets ``read_file`` answer with the
        same layout-aware message HDF5 and Zarr give for an ambiguous store
        (which tree to pick, and how to pass it); a ValueError would be
        flattened into "Unable to read the uploaded file."
        """
        trees = self._list_trees()
        if not trees:
            self.logger.error(
                "No TTree found in ROOT file '%s'; AIDRIN needs a TTree "
                "(tabular branches) to build a DataFrame.",
                self.file_path,
            )
            return None

        selected = self._explicit_selected_keys
        if selected is None:
            try:
                from flask import has_request_context, session

                if has_request_context():
                    selected = session.get("selected_keys") or None
            except Exception:
                selected = None

        if isinstance(selected, str):
            selected = [s.strip() for s in selected.split(",") if s.strip()]
        elif selected is not None and not isinstance(selected, list):
            selected = None

        if selected:
            # One tree at a time for v1 (metrics need a single tabular frame).
            tree_name = _strip_cycle(str(selected[0]))
            if tree_name not in trees:
                raise ValueError(
                    f"TTree '{tree_name}' not found in '{self.file_path}'. "
                    f"Available: {', '.join(trees)}"
                )
            if len(selected) > 1:
                self.logger.warning(
                    "Multiple ROOT trees selected (%s); using only '%s'.",
                    selected,
                    tree_name,
                )
            return tree_name

        if len(trees) == 1:
            return trees[0]

        self.logger.error(
            "ROOT file '%s' has multiple TTrees (%s) and needs an explicit "
            "selection.",
            self.file_path,
            ", ".join(trees),
        )
        return None

    def read(self) -> pd.DataFrame | None:
        uproot = _require_uproot()
        tree_name = self._resolve_tree_name()
        if tree_name is None:
            # read_file turns this into the layout-aware "pick a tree" error.
            return None
        self.logger.info("Reading ROOT TTree %r from %s", tree_name, self.file_path)
        only_arrays = (
            f"ROOT TTree '{tree_name}' contains only array-valued branches "
            "(per-event sequences). AIDRIN metrics need scalar branches to "
            "build a tabular DataFrame."
        )

        # Array-valued branches (per-event sequences, e.g. vector<float> or
        # float[3]) are not representable as tabular columns: metrics that hash
        # or aggregate cells crash on them (unhashable numpy.ndarray). Skip
        # them at read time rather than after conversion: a real TTree routes
        # them through the optional 'awkward-pandas' stack, so asking for them
        # fails the whole read. Keep the names for df.attrs so callers can
        # disclose the exclusion.
        with uproot.open(self.file_path) as handle:
            tree = handle[tree_name]
            typenames = _branch_typenames(tree)
            jagged = [
                name
                for name, typename in typenames.items()
                if _is_array_typename(typename)
            ]
            scalar = [name for name in typenames if name not in set(jagged)]
            if not scalar:
                raise ValueError(only_arrays)
            df = tree.arrays(scalar, library="pd")

        if not isinstance(df, pd.DataFrame):
            raise ValueError(
                f"ROOT TTree '{tree_name}' did not convert to a pandas DataFrame."
            )
        if df.empty:
            raise ValueError(f"ROOT TTree '{tree_name}' produced an empty DataFrame.")
        df.columns = [str(c) for c in df.columns]

        # Backstop: the type name does not catch every sequence (object
        # branches, multi-leaf branches), so drop whatever still arrived as
        # per-row arrays.
        missed = [col for col in df.columns if _is_jagged(df[col])]
        if missed:
            if len(missed) == len(df.columns):
                raise ValueError(only_arrays)
            df = df.drop(columns=missed)
            jagged += missed

        if jagged:
            self.logger.warning(
                "Dropped %d array-valued ROOT branch(es) from '%s' (per-event "
                "sequences, not representable as tabular columns): %s",
                len(jagged),
                tree_name,
                ", ".join(jagged),
            )
            df.attrs[DROPPED_COLUMNS_ATTR] = jagged
        return df
