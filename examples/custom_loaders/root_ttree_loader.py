"""Example ROOT TTree loader for AIDRIN custom ingestion.

Requires ``uproot`` in the environment (not an AIDRIN dependency). Use until
``rootReader`` is implemented:

    aidrin run completeness sample.root --loader ./examples/custom_loaders/root_ttree_loader.py:load
"""

from __future__ import annotations

import pandas as pd


def load(path: str, **kwargs) -> pd.DataFrame:
    """Load a ROOT TTree into a pandas DataFrame via uproot."""
    import uproot

    tree_name = kwargs.get("tree", "tree")
    with uproot.open(path) as handle:
        tree = handle[tree_name]
        return tree.arrays(library="pd")
