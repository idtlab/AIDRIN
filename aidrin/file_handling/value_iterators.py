import logging
from typing import Any, Callable

import h5py
import numpy as np
import pandas as pd

from aidrin.file_handling.file_parser import read_file
from aidrin.file_handling.readers.hdf5_reader import hdf5Reader

logger = logging.getLogger(__name__)


HDF5_SUPPORTED_KINDS = {"b", "i", "u", "f", "S", "U"}
HDF5_BLOCK_ELEMENT_LIMIT = 1_000_000


def iter_targets(file_info):
    """Return selectable value targets for tabular files and native HDF5 files."""
    file_path, _file_name, file_type = file_info[:3]
    if file_type == ".h5":
        return _iter_hdf5_targets(file_path)
    return _iter_column_targets(file_info)


def iter_value_blocks(file_info, target):
    """Yield value blocks for one selectable target.

    Blocks include the planned fields plus an optional ``missing_mask`` used by
    metrics that need fill-sentinel-aware missing handling.
    """
    target_type = target.get("target_type")
    if target_type == "hdf5_dataset":
        yield from _iter_hdf5_value_blocks(file_info[0], target)
    elif target_type == "column":
        yield from _iter_column_value_blocks(file_info, target)
    else:
        raise ValueError(f"Unsupported target type: {target_type}")


def _iter_column_targets(file_info):
    df = read_file(file_info)
    if not hasattr(df, "columns"):
        return []

    targets = []
    for col in df.columns:
        series = df[col]
        name = str(col)
        targets.append({
            "name": name,
            "target_type": "column",
            "dtype": str(series.dtype),
            "shape": [int(len(series))],
            "display_label": name,
        })
    return targets


def _iter_column_value_blocks(file_info, target):
    df = read_file(file_info)
    if not hasattr(df, "columns"):
        raise ValueError("Unable to read tabular file")

    name = target["name"]
    if name not in df.columns:
        raise KeyError(f"Target not found: {name}")

    series = df[name]

    def locate(index_tuple):
        row_index = int(index_tuple[0])
        location = {"row_index": row_index, "display": f"row {row_index}"}
        if file_info[2] == ".csv":
            location["source_line"] = row_index + 2
        return location

    yield {
        "target": name,
        "target_type": "column",
        "values": series,
        "offset": None,
        "locate": locate,
    }


def _iter_hdf5_targets(file_path):
    targets = []
    with h5py.File(file_path, "r") as h5:

        def visit(name, obj):
            if not isinstance(obj, h5py.Dataset):
                return
            path = f"/{name}"
            shape = [int(dim) for dim in obj.shape]
            dtype = str(obj.dtype)
            shape_label = ", ".join(str(dim) for dim in shape) if shape else "scalar"
            targets.append({
                "name": path,
                "target_type": "hdf5_dataset",
                "dtype": dtype,
                "shape": shape,
                "display_label": f"{path} ({dtype}, {shape_label})",
            })

        h5.visititems(visit)
    return targets


def _iter_hdf5_value_blocks(file_path, target):
    path = target["name"]
    internal_path = path.lstrip("/")
    with h5py.File(file_path, "r") as h5:
        if internal_path not in h5:
            raise KeyError(f"Target not found: {path}")
        dataset = h5[internal_path]
        if not isinstance(dataset, h5py.Dataset):
            raise KeyError(f"Target is not an HDF5 dataset: {path}")

        if not _is_supported_hdf5_dataset(dataset):
            raise TypeError(f"Unsupported HDF5 dataset dtype for {path}: {dataset.dtype}")

        for selection, offset in _iter_hdf5_dataset_selections(dataset):
            values = dataset[()] if selection is None else dataset[selection]
            values = np.asarray(values)
            if values.shape == ():
                values = values.reshape(())

            missing_mask = _hdf5_missing_mask(dataset, values, internal_path)

            def locate(index_tuple, block_offset=offset):
                normalized = _global_hdf5_index(index_tuple, block_offset)
                suffix = "".join(f"[{','.join(str(i) for i in normalized)}]") if normalized else ""
                return {
                    "path": path,
                    "index": list(normalized),
                    "display": f"{path}{suffix}",
                }

            yield {
                "target": path,
                "target_type": "hdf5_dataset",
                "values": values,
                "offset": list(offset) if offset else None,
                "locate": locate,
                "missing_mask": missing_mask,
            }


def _is_supported_hdf5_dataset(dataset):
    if dataset.dtype.kind in HDF5_SUPPORTED_KINDS:
        return True
    return h5py.check_string_dtype(dataset.dtype) is not None


def _iter_hdf5_dataset_selections(dataset):
    if dataset.shape == ():
        yield None, ()
        return

    if dataset.chunks:
        for selection in dataset.iter_chunks():
            yield selection, _selection_offset(selection)
        return

    yield from _iter_regular_hdf5_slices(dataset.shape)


def _iter_regular_hdf5_slices(shape):
    trailing_elements = int(np.prod(shape[1:], dtype=np.int64)) if len(shape) > 1 else 1
    rows_per_block = max(1, HDF5_BLOCK_ELEMENT_LIMIT // max(1, trailing_elements))
    for start in range(0, int(shape[0]), rows_per_block):
        stop = min(int(shape[0]), start + rows_per_block)
        selection = (slice(start, stop),) + tuple(slice(0, int(dim)) for dim in shape[1:])
        yield selection, _selection_offset(selection)


def _selection_offset(selection):
    return tuple(int(s.start or 0) for s in selection)


def _global_hdf5_index(index_tuple, offset):
    normalized = tuple(int(i) for i in index_tuple)
    if not offset:
        return normalized
    return tuple(int(i) + int(o) for i, o in zip(normalized, offset))


def _hdf5_missing_mask(dataset, values, display_name):
    missing_mask = pd.isna(values)
    if not isinstance(missing_mask, np.ndarray):
        missing_mask = np.asarray(missing_mask)
    missing_mask = missing_mask.astype(bool, copy=False)

    if values.dtype.kind not in ("f", "i", "u"):
        return missing_mask

    reader = hdf5Reader("", logger)
    explicit_fills, uncertain_fills = reader._collect_fill_values(dataset)
    all_fills = explicit_fills | uncertain_fills
    if not all_fills:
        return missing_mask

    matched = set()
    fill_match_count = 0
    for fill_value in all_fills:
        try:
            fill_mask = values == fill_value
        except TypeError:
            continue
        if np.any(fill_mask):
            matched.add(fill_value)
            fill_match_count += int(np.asarray(fill_mask).sum())
            missing_mask |= fill_mask

    if not matched:
        return missing_mask

    uncertain_matched = matched & uncertain_fills
    if uncertain_matched:
        logger.warning(
            "Dataset '%s': %d/%d value(s) match the HDF5 default fill value %s "
            "and will be marked as missing. If zero is a valid measurement here "
            "(e.g. counts, indices), set a '_FillValue' attribute in the file to "
            "an unambiguous sentinel, or pass fill_values=[] at construction time "
            "to suppress native fill value missing handling.",
            display_name,
            fill_match_count,
            values.size,
            uncertain_matched,
        )
    else:
        logger.info(
            "Dataset '%s': marked %d/%d value(s) matching explicit fill sentinel(s) %s as missing.",
            display_name,
            fill_match_count,
            values.size,
            matched,
        )
    return missing_mask


def iter_indexed_values(values):
    """Yield ``(index_tuple, value)`` for scalar or array-like values."""
    arr = np.asarray(values)
    if arr.shape == ():
        yield (), arr.item()
        return
    for index_tuple in np.ndindex(arr.shape):
        yield index_tuple, arr[index_tuple].item() if hasattr(arr[index_tuple], "item") else arr[index_tuple]


def mask_lookup(mask: Any) -> Callable[[tuple], bool]:
    arr = np.asarray(mask)
    if arr.shape == ():
        return lambda _idx: bool(arr.item())
    return lambda idx: bool(arr[idx])
