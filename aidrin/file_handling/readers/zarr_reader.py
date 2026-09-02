"""Zarr store reader for directory paths (CLI, library, Globus).

Local browser upload of Zarr stores is intentionally not registered in
``SUPPORTED_FILE_TYPES``; use a directory path with CLI/library or Globus.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from aidrin.file_handling.readers.structured import (
    INVENTORY_EMPTY,
    INVENTORY_LEGACY,
    INVENTORY_MULTI,
    INVENTORY_SINGLE,
    DatasetEntry,
    InventoryResult,
    StructuredFileReader,
    make_inventory,
)


def _require_zarr():
    try:
        import zarr
    except ImportError as exc:
        raise ImportError(
            "Zarr support requires the 'zarr' package on Python >=3.11. "
            "Install with: pip install 'aidrin[zarr]' or pip install 'zarr>=3.0.8,<3.2'"
        ) from exc
    return zarr


class zarrReader(StructuredFileReader):
    """Read Zarr directory stores into pandas DataFrames.

    Same selection model as HDF5: pass ``selected_keys`` to choose array paths.
    Only tabular-friendly arrays (0D/1D, or a single 2D array) are converted;
    higher-dimensional arrays are refused so metrics see raw values, not aggregates.
    """

    def __init__(self, file_path: str, logger, selected_keys=None):
        super().__init__(file_path, logger)
        self._explicit_selected_keys = selected_keys

    def _open_store(self):
        zarr = _require_zarr()
        return zarr.open(self.file_path, mode="r")

    def _list_group_paths(self):
        zarr = _require_zarr()
        root = self._open_store()
        if isinstance(root, zarr.Array):
            return []

        groups = []

        def walk(group, prefix=""):
            # sorted(): zarr group keys come back in store order, which varies
            # between runs. Walk in name order so paths, and therefore
            # DataFrame column order, are stable (h5py.visititems already is).
            for key in sorted(group.keys()):
                child = group[key]
                path = f"{prefix}/{key}" if prefix else key
                if isinstance(child, zarr.Group):
                    groups.append(path)
                    walk(child, path)

        walk(root)
        return groups

    def _list_datasets(self) -> list[DatasetEntry]:
        zarr = _require_zarr()
        root = self._open_store()
        datasets: list[DatasetEntry] = []

        if isinstance(root, zarr.Array):
            return [
                {
                    "path": "",
                    "shape": tuple(int(s) for s in root.shape),
                    "ndim": int(root.ndim),
                    "dtype": str(root.dtype),
                    "size": int(root.size),
                }
            ]

        def walk(group, prefix=""):
            for key in sorted(group.keys()):
                child = group[key]
                path = f"{prefix}/{key}" if prefix else key
                if isinstance(child, zarr.Array):
                    datasets.append(
                        {
                            "path": path,
                            "shape": tuple(int(s) for s in child.shape),
                            "ndim": int(child.ndim),
                            "dtype": str(child.dtype),
                            "size": int(child.size),
                        }
                    )
                elif isinstance(child, zarr.Group):
                    walk(child, path)

        walk(root)
        return datasets

    def _build_picker_groups(self, datasets: list[DatasetEntry]):
        paths = {ds["path"] for ds in datasets if ds["path"]}
        assigned = set()
        groups = {}

        for group_path in sorted(self._list_group_paths(), key=len, reverse=True):
            prefix = f"{group_path}/"
            members = sorted(p for p in paths if p.startswith(prefix) and p not in assigned)
            if len(members) >= 2:
                groups[group_path] = {
                    "id": group_path,
                    "label": group_path,
                    "type": "zarr_group",
                    "dataset_paths": members,
                }
                assigned.update(members)

        return sorted(groups.values(), key=lambda group: group["label"].lower())

    def _can_auto_read(self, datasets: list[DatasetEntry]):
        """Whether ``read()`` can build a frame without an explicit selection.

        This mirrors ``_auto_read_all`` exactly so that a layout is never
        labelled auto-readable in ``inventory()`` and then refused at read time
        — e.g. a root store holding one 1D array alongside one 2D array, which
        no shape heuristic flags as "incompatible" but which cannot be merged.
        """
        if len(datasets) == 1:
            return datasets[0]["ndim"] <= 2

        ones = [ds for ds in datasets if ds["ndim"] == 1]
        if len(ones) != len(datasets):
            return False
        lengths = {ds["shape"][0] for ds in ones if ds["shape"]}
        return len(lengths) == 1

    def _needs_dataset_selection(self, datasets: list[DatasetEntry]):
        return not self._can_auto_read(datasets)

    def inventory(self) -> InventoryResult:
        try:
            datasets = self._list_datasets()
        except ImportError:
            # A missing 'zarr' package must reach the caller with its install
            # hint; swallowing it here would report the store as empty.
            raise
        except Exception as e:
            self.logger.error("Failed to inventory Zarr store: %s", e, exc_info=True)
            return make_inventory(INVENTORY_EMPTY)

        if not datasets:
            layout = INVENTORY_EMPTY
        elif len(datasets) == 1:
            layout = INVENTORY_SINGLE
        elif self._needs_dataset_selection(datasets):
            layout = INVENTORY_MULTI
        else:
            layout = INVENTORY_LEGACY

        groups = self._build_picker_groups(datasets) if layout == INVENTORY_MULTI else []
        return make_inventory(layout, datasets, groups)

    def parse(self):
        return [ds["path"] or "(root)" for ds in self._list_datasets()]

    def get_metadata(self) -> dict[str, Any]:
        zarr = _require_zarr()
        root = self._open_store()
        metadata: dict[str, Any] = {}

        def attrs_to_dict(attrs):
            try:
                return dict(attrs)
            except Exception:
                return {}

        if isinstance(root, zarr.Array):
            metadata["(root)"] = attrs_to_dict(root.attrs)
            return metadata

        metadata["(root)"] = attrs_to_dict(root.attrs)

        def walk(group, prefix=""):
            for key in sorted(group.keys()):
                child = group[key]
                path = f"{prefix}/{key}" if prefix else key
                child_attrs = attrs_to_dict(child.attrs)
                if child_attrs:
                    metadata[path] = child_attrs
                if isinstance(child, zarr.Group):
                    walk(child, path)

        walk(root)
        return metadata

    def _normalize_selected_keys(self, keys):
        if isinstance(keys, str):
            keys = [key.strip() for key in keys.split(",") if key.strip()]
        return [str(key) for key in keys if key]

    def _get_selected_dataset_keys(self):
        # Explicit keys only. Unlike HDF5 there is no Zarr key picker, so
        # session["selected_keys"] can only hold paths from some other file —
        # reading it here would apply a previous HDF5 selection to this store.
        if self._explicit_selected_keys is None:
            return []
        return self._normalize_selected_keys(self._explicit_selected_keys)

    def _resolve_array(self, root, path: str):
        zarr = _require_zarr()
        if path in ("", "(root)"):
            if isinstance(root, zarr.Array):
                return root
            self.logger.warning("Zarr root path requested but store is a group")
            return None
        try:
            obj = root[path]
        except Exception:
            self.logger.warning("Zarr array path not found: %s", path)
            return None
        if not isinstance(obj, zarr.Array):
            self.logger.warning("Zarr path is not an array: %s", path)
            return None
        return obj

    def _prepare_array_data(self, arr):
        """Load array data; refuse ndim >= 3 (no averaging / reshape for metrics).

        The dimensionality check reads ``arr.ndim`` (store metadata) rather than
        the loaded data: multi-dimensional grids are exactly the arrays this
        refuses, and they are also the largest, so materializing one only to
        reject it would exhaust memory on a real (time, lat, lon) store.
        """
        ndim = int(getattr(arr, "ndim", 0))
        if ndim >= 3:
            self.logger.warning(
                "Zarr array has ndim=%s; refusing to aggregate or flatten. "
                "Select 1D (or a single 2D) arrays via selected_keys.",
                ndim,
            )
            return None
        # Ellipsis, not [:]: a 0D array rejects a slice with IndexError.
        return np.asarray(arr[...])

    def _column_name_from_path(self, path: str, used_names):
        full = path.strip("/") if path not in ("", "(root)") else "value"
        if not full:
            full = "value"
        if full not in used_names:
            return full
        short = path.split("/")[-1] or full
        if short not in used_names:
            return short
        dotted = full.replace("/", ".")
        if dotted not in used_names:
            return dotted
        suffix = 2
        while f"{full}_{suffix}" in used_names:
            suffix += 1
        return f"{full}_{suffix}"

    def _array_to_frame(self, path: str, arr):
        data = self._prepare_array_data(arr)
        if data is None:
            return None

        col_name = self._column_name_from_path(path, set())
        if getattr(data, "ndim", 0) == 0:
            df = pd.DataFrame({col_name: [data]})
        elif data.ndim == 1:
            df = pd.DataFrame({col_name: data})
        elif data.ndim == 2:
            try:
                df = pd.DataFrame(data)
            except Exception:
                df = pd.DataFrame(data.tolist())
            df.columns = [f"{col_name}_{i}" for i in range(df.shape[1])]
        else:
            self.logger.warning(
                "Cannot convert ndim=%s Zarr array '%s' to a DataFrame",
                getattr(data, "ndim", None),
                path,
            )
            return None
        df.columns = [str(col) for col in df.columns]
        return df if not df.empty else None

    def _read_array_path(self, path: str):
        root = self._open_store()
        arr = self._resolve_array(root, path)
        if arr is None:
            return None
        return self._array_to_frame(path, arr)

    def _read_compatible_array_paths(self, paths):
        if not paths:
            return None

        columns = {}
        expected_len = None
        root = self._open_store()

        for path in paths:
            arr = self._resolve_array(root, path)
            if arr is None:
                return None
            data = self._prepare_array_data(arr)
            if data is None:
                return None
            data = np.asarray(data)
            if data.ndim != 1:
                self.logger.warning(
                    "Zarr multi-select requires 1D arrays; '%s' has ndim=%s",
                    path,
                    data.ndim,
                )
                return None
            length = int(data.shape[0])
            if expected_len is None:
                expected_len = length
            elif length != expected_len:
                self.logger.warning(
                    "Zarr selected arrays have incompatible lengths (%d vs %d)",
                    expected_len,
                    length,
                )
                return None
            name = self._column_name_from_path(path, set(columns))
            columns[name] = data

        df = pd.DataFrame(columns)
        return df if not df.empty else None

    def _auto_read_all(self, datasets: list[DatasetEntry]):
        """Auto-read when layout does not require explicit selection."""
        if len(datasets) == 1:
            return self._read_array_path(datasets[0]["path"] or "")

        ones = [ds for ds in datasets if ds["ndim"] == 1]
        if ones and len(ones) == len(datasets):
            lengths = {ds["shape"][0] for ds in ones if ds["shape"]}
            if len(lengths) == 1:
                return self._read_compatible_array_paths([ds["path"] for ds in ones])

        self.logger.warning(
            "Zarr store has %d arrays that cannot be auto-merged; "
            "pass selected_keys to read specific paths.",
            len(datasets),
        )
        return None

    def read(self):
        try:
            inv = self.inventory()
            if inv["type"] == INVENTORY_EMPTY:
                self.logger.warning("No arrays found in Zarr store")
                return None

            # Honor explicit selection for any non-empty layout (CLI/library/Globus).
            selected = self._get_selected_dataset_keys()
            if selected:
                if len(selected) == 1:
                    return self._read_array_path(selected[0])
                return self._read_compatible_array_paths(selected)

            if inv["type"] == INVENTORY_MULTI:
                self.logger.warning(
                    "Zarr store has %d arrays in an incompatible layout; "
                    "refusing to flatten. Pass selected_keys to choose paths.",
                    len(inv["datasets"]),
                )
                return None

            return self._auto_read_all(inv["datasets"])
        except ImportError:
            raise
        except Exception as e:
            self.logger.error("Error reading Zarr store: %s", e, exc_info=True)
            return None
