"""ROOT TTree reader via ``uproot`` (core dependency).

AIDRIN metrics require a tabular DataFrame; this reader loads one TTree at a
time into pandas.
"""

from __future__ import annotations

from typing import List

import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader


def _require_uproot():
    try:
        import uproot
    except ImportError as exc:
        raise ImportError(
            "Reading ROOT (.root) files requires 'uproot'. "
            "Reinstall AIDRIN or run: pip install uproot"
        ) from exc
    return uproot


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

    def _resolve_tree_name(self) -> str:
        trees = self._list_trees()
        if not trees:
            raise ValueError(
                f"No TTree found in ROOT file '{self.file_path}'. "
                "AIDRIN needs a TTree (tabular branches) to build a DataFrame."
            )

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

        raise ValueError(
            f"ROOT file '{self.file_path}' has multiple TTrees "
            f"({', '.join(trees)}). Select one tree "
            "(web key picker, or pass selected_keys for library/Celery)."
        )

    def read(self) -> pd.DataFrame:
        uproot = _require_uproot()
        tree_name = self._resolve_tree_name()
        self.logger.info("Reading ROOT TTree %r from %s", tree_name, self.file_path)
        with uproot.open(self.file_path) as handle:
            tree = handle[tree_name]
            df = tree.arrays(library="pd")

        if not isinstance(df, pd.DataFrame):
            raise ValueError(
                f"ROOT TTree '{tree_name}' did not convert to a pandas DataFrame."
            )
        if df.empty:
            raise ValueError(f"ROOT TTree '{tree_name}' produced an empty DataFrame.")
        df.columns = [str(c) for c in df.columns]
        return df
