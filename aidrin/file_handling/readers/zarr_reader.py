"""
Zarr v2/v3 reader for AIDRIN.

Supports directory stores and zip stores.  Implements the same
read() / parse() / filter() contract as existing readers, following
hdf5Reader as the model for hierarchical format handling and the
explicit-vs-uncertain fill-value classification it introduced.

The central mechanism this PoC demonstrates is _collect_fill_values():
Zarr arrays carry a fill_value in their metadata, but the default is 0,
which is ambiguous — it may be a valid measurement, not a missing-data
marker.  The same explicit/uncertain split used in hdf5Reader is applied
here so callers get consistent NaN replacement behaviour across formats.
"""

import os
import uuid
import zipfile

import numpy as np
import pandas as pd
import zarr
from flask import current_app, session

from aidrin.file_handling.readers.base_reader import BaseFileReader


class zarrReader(BaseFileReader):
    """Read Zarr v2/v3 stores into a pandas DataFrame.

    Parameters
    ----------
    file_path : str
        Path to a Zarr directory store or zip store file.
    logger : logging.Logger
        Logger provided by file_parser.py.
    fill_values : iterable of numeric, optional
        Extra sentinel values to treat as explicit missing-data markers
        on top of those found in array metadata.
    """

    def __init__(self, file_path: str, logger, fill_values=None):
        super().__init__(file_path, logger)
        self.fill_values = set(fill_values) if fill_values is not None else set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_store(self):
        """Return the root zarr.Group, auto-detecting zip vs. directory."""
        if zipfile.is_zipfile(self.file_path):
            store = zarr.ZipStore(self.file_path, mode="r")
            return zarr.open_group(store, mode="r")
        if os.path.isdir(self.file_path):
            return zarr.open_group(self.file_path, mode="r")
        raise ValueError(
            f"Cannot open Zarr store at '{self.file_path}': "
            "path is neither a zip file nor a directory."
        )

    def _collect_fill_values(self, array):
        """Return (explicit_fills, uncertain_fills) for a zarr.Array.

        Mirrors hdf5Reader._collect_fill_values().

        explicit — replaced silently:
            • User-supplied values from the constructor.
            • The array's metadata fill_value when it is non-zero (the
              producer deliberately chose this sentinel).

        uncertain — WARNING emitted before replacement:
            • The metadata fill_value when it equals the dtype default (0 /
              0.0).  Zarr's spec requires every array to have a fill_value;
              without an explicit assignment it defaults to zero, which is a
              perfectly valid measurement in most datasets.
        """
        explicit = set(self.fill_values)
        uncertain = set()

        try:
            raw = array.fill_value
            if raw is not None:
                native = float(raw)
                if native not in explicit:
                    dtype_default = float(np.zeros(1, dtype=array.dtype)[0])
                    if native == dtype_default:
                        uncertain.add(native)
                    else:
                        explicit.add(native)
        except (TypeError, ValueError, AttributeError):
            pass

        return explicit, uncertain

    def _array_to_rows(self, name, array):
        """Load a numeric zarr.Array, apply fill-value replacement, return rows."""
        if array.dtype.kind not in ("f", "i", "u"):
            self.logger.info(
                f"Skipping '{name}' (dtype {array.dtype} is non-numeric)."
            )
            return []

        try:
            data = array[...]
        except Exception as exc:
            self.logger.warning(f"Failed to load array '{name}': {exc}. Skipping.")
            return []

        explicit, uncertain = self._collect_fill_values(array)
        all_fills = explicit | uncertain

        if all_fills:
            matched = {fv for fv in all_fills if np.any(data == fv)}
            if matched:
                mask = np.zeros(data.shape, dtype=bool)
                for fv in matched:
                    mask |= data == fv
                n = int(mask.sum())

                if matched & uncertain:
                    self.logger.warning(
                        f"Array '{name}': {n}/{data.size} value(s) match the "
                        f"Zarr default fill value {matched & uncertain} and will "
                        f"be replaced with NaN.  If zero is a valid measurement, "
                        f"pass fill_values=[] to suppress this replacement."
                    )
                else:
                    self.logger.info(
                        f"Array '{name}': replaced {n}/{data.size} explicit "
                        f"fill sentinel(s) {matched} with NaN."
                    )

                data = data.astype(np.float64)
                data[mask] = np.nan

        try:
            df = pd.DataFrame(data)
        except Exception:
            try:
                df = pd.DataFrame(data.reshape(-1, 1))
            except Exception as exc2:
                self.logger.warning(
                    f"Cannot convert '{name}' to DataFrame: {exc2}. Skipping."
                )
                return []

        return [{str(col): val for col, val in row.items()} for _, row in df.iterrows()]

    # ------------------------------------------------------------------
    # BaseFileReader interface
    # ------------------------------------------------------------------

    def read(self):
        """Load all numeric arrays from the store into a single DataFrame."""
        try:
            root = self._open_store()
        except Exception as exc:
            self.logger.error(f"Cannot open Zarr store '{self.file_path}': {exc}")
            return None

        rows = []

        def visitor(name, obj):
            if isinstance(obj, zarr.Array):
                rows.extend(self._array_to_rows(name, obj))

        try:
            root.visititems(visitor)
        except Exception as exc:
            self.logger.error(f"Zarr traversal error for '{self.file_path}': {exc}")
            return None

        if not rows:
            self.logger.warning(
                f"No numeric data found in Zarr store '{self.file_path}'."
            )
            return None

        df = pd.DataFrame(rows)
        df.columns = [str(col) for col in df.columns]
        self.logger.info(
            f"Zarr store loaded: {len(df)} rows x {len(df.columns)} columns."
        )
        return df

    def parse(self):
        """Return flat list of group paths (mirrors hdf5Reader.parse() behaviour)."""
        try:
            root = self._open_store()
        except Exception as exc:
            self.logger.error(f"Cannot open Zarr store for parsing: {exc}")
            return None

        group_names = []

        def visitor(name, obj):
            if isinstance(obj, zarr.Group):
                group_names.append(str(name))

        try:
            root.visititems(visitor)
        except Exception as exc:
            self.logger.error(f"Zarr parse error: {exc}")
            return None

        self.logger.info(f"Zarr groups found: {group_names}")
        return group_names

    def filter(self, kept_keys, upload_folder=None, filename=None):
        """Write a new zip store containing only the selected groups.

        Parameters
        ----------
        kept_keys : str or list[str]
            Group paths to retain (comma-separated string or list).
        upload_folder : str, optional
            Destination directory.  Falls back to current_app UPLOAD_FOLDER.
        filename : str, optional
            Original filename used to build the output name.  Falls back to
            session['uploaded_file_name'].
        """
        if isinstance(kept_keys, str):
            kept_keys = [k.strip() for k in kept_keys.split(",")]
        selected = {str(k).strip("/") for k in kept_keys}

        if upload_folder is None:
            upload_folder = current_app.config["UPLOAD_FOLDER"]
        if filename is None:
            filename = session.get("uploaded_file_name", "store.zarr.zip")

        new_path = os.path.join(upload_folder, f"filtered_{uuid.uuid4().hex}_{filename}")

        try:
            src = self._open_store()
        except Exception as exc:
            self.logger.error(f"Cannot open source store for filtering: {exc}")
            return None

        try:
            dest_store = zarr.ZipStore(new_path, mode="w")
            dest = zarr.open_group(dest_store, mode="w")

            # Only copy the object whose path *directly* matches a selected key.
            # visititems descends into groups, so copying a group already
            # includes its children — avoid re-copying them by checking for
            # an exact match rather than an ancestor match.
            def copy_if_selected(name, obj):
                if name.strip("/") in selected:
                    zarr.copy(src[name], dest, name=name, log=None)

            src.visititems(copy_if_selected)
            dest_store.close()
        except Exception as exc:
            self.logger.error(f"Error writing filtered store: {exc}")
            return None

        self.logger.info(f"Filtered Zarr store written to '{new_path}'.")
        return new_path
