"""
Abstract base class for user-defined custom ingestion plugins.

Modelled directly on BaseDRAgent in aidrin/custom_metrics/base_dr.py:
users subclass BaseIngestionPlugin, implement ingest(), upload the file
via a UI editor, and AIDRIN dynamically loads it with importlib — no
changes to core code required.

The key difference from BaseDRAgent is that a plugin converts an
arbitrary file into a DataFrame (the *input* side of the pipeline),
whereas BaseDRAgent computes a metric on an existing DataFrame (the
*analysis* side).
"""

import abc
from typing import Any

import pandas as pd


class BaseIngestionPlugin(abc.ABC):
    """Convert an arbitrary file into a pandas DataFrame for AIDRIN metrics.

    Subclass this and implement ingest().  AIDRIN will call
    ingest(file_path) with the path of the uploaded file and pass the
    returned DataFrame into the standard metric pipeline.

    Example
    -------
    A plugin that reads a fixed-width binary format (4-byte float32 per record):

        import struct, pandas as pd
        from aidrin.custom_readers.base_ingestion_plugin import BaseIngestionPlugin

        class FloatBinReader(BaseIngestionPlugin):
            def ingest(self, file_path: str) -> pd.DataFrame:
                values = []
                with open(file_path, 'rb') as f:
                    while chunk := f.read(4):
                        values.append(struct.unpack('<f', chunk)[0])
                return pd.DataFrame({'value': values})
    """

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs

    @abc.abstractmethod
    def ingest(self, file_path: str) -> pd.DataFrame:
        """Read file_path and return a non-empty pandas DataFrame.

        All column names should be strings.  Numeric columns are required
        for completeness, outlier, and correlation metrics; string/object
        columns are supported for FAIRness and class-imbalance metrics.
        """

    def validate(self, df: pd.DataFrame) -> bool:
        """Check that ingest() returned a usable DataFrame.

        Called automatically by the plugin loader after ingest().
        Raises ValueError with a user-facing message on failure.
        """
        if df is None or df.empty:
            raise ValueError(
                "ingest() returned an empty DataFrame.  "
                "Ensure the file contains data and the parser logic is correct."
            )
        if len(df.columns) == 0:
            raise ValueError("ingest() returned a DataFrame with no columns.")
        return True

    def describe(self) -> str:
        """Short description used in logs and the plugin registry UI."""
        return self.__class__.__name__
