"""
Shared contract for structured file readers (HDF5, Zarr, ROOT).

Structured formats may hold many arrays or tables under paths. Readers classify
the on-disk layout via ``inventory()`` before ``read()`` loads tabular data.

Inventory ``type`` values
-------------------------
empty
    No readable datasets or arrays.
single_dataset
    One dataset; auto-read without a picker.
multi_dataset
    Incompatible or grouped layout; caller must select paths.
legacy
    Internal auto-read path for compatible multi-array layouts (and HDF5
    PyTables stores). Never surface this label in API or UI responses.
unsupported
    Reader stub or format not implemented yet. Never treat as auto-read.
"""

from __future__ import annotations

from typing import Any, TypedDict

from aidrin.file_handling.readers.base_reader import BaseFileReader

INVENTORY_EMPTY = "empty"
INVENTORY_SINGLE = "single_dataset"
INVENTORY_MULTI = "multi_dataset"
INVENTORY_LEGACY = "legacy"
INVENTORY_UNSUPPORTED = "unsupported"

# Types that may be shown to users when driving picker or error messages.
USER_FACING_INVENTORY_TYPES = frozenset(
    {INVENTORY_EMPTY, INVENTORY_SINGLE, INVENTORY_MULTI}
)


class DatasetEntry(TypedDict):
    path: str
    shape: tuple[int, ...]
    ndim: int
    dtype: str
    size: int


class PickerGroup(TypedDict, total=False):
    id: str
    label: str
    type: str
    dataset_paths: list[str]


class InventoryResult(TypedDict):
    type: str
    datasets: list[DatasetEntry]
    groups: list[dict[str, Any]]


def make_inventory(
    inv_type: str,
    datasets: list[DatasetEntry] | None = None,
    groups: list[dict[str, Any]] | None = None,
) -> InventoryResult:
    """Build a normalized inventory dict."""
    return {
        "type": inv_type,
        "datasets": datasets or [],
        "groups": groups or [],
    }


class StructuredFileReader(BaseFileReader):
    """Base for hierarchical array/tree formats with inventory and metadata hooks."""

    def inventory(self) -> InventoryResult:
        return make_inventory(INVENTORY_UNSUPPORTED)

    def get_metadata(self) -> dict[str, Any]:
        """Embedded file metadata for FAIR assessment (``.zattrs``, ROOT headers, etc.)."""
        return {}
