"""Ordered collections of tabular inputs, independent of any upload interface.

Provenance is kept beside the measurements. A metric must explicitly request
source columns before they become part of its input table.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import json
import logging

import pandas as pd

from aidrin.file_handling.file_parser import read_file


SOURCE_COLUMNS = ("__aidrin_source_id", "__aidrin_source_row")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionMember:
    """One selected source, identified independently of its display filename."""

    id: str
    path: str
    name: str = ""
    file_type: str | None = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Each collection member needs a non-empty string id")
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("Each collection member needs a non-empty string path")
        if not isinstance(self.name, str):
            raise ValueError("Collection member name must be a string")
        if self.file_type is not None and not isinstance(self.file_type, str):
            raise ValueError("Collection file_type must be a string or null")

    @property
    def display_name(self):
        return self.name or Path(self.path).name

    def load(self):
        # Reuse the same format aliases as CLI/library calls. Import lazily to
        # avoid a dependency cycle while the metric registry is being imported.
        from aidrin.headless.runners import _normalize_file_type
        from aidrin.file_handling.custom_loader import using_builtin_readers

        file_type = _normalize_file_type(self.file_type, self.path)
        try:
            with using_builtin_readers():
                frame = read_file((self.path, self.display_name, file_type))
        except Exception as exc:
            logger.exception("Collection member read failed: %s", self.id)
            raise ValueError(f"{self.display_name}: unable to read a table; verify its format and dataset layout") from exc
        if not isinstance(frame, pd.DataFrame) or frame.empty or not frame.columns.is_unique:
            raise ValueError(f"{self.display_name}: expected a non-empty table with unique columns")
        if any(not isinstance(column, str) for column in frame.columns):
            raise ValueError(f"{self.display_name}: collection columns must have string names")
        if set(frame.columns).intersection(SOURCE_COLUMNS):
            raise ValueError(f"{self.display_name}: input uses a reserved collection source column")
        return frame.reset_index(drop=True)


def normalize_members(files):
    """Validate an explicit ordered selection; never discover files by globbing."""
    if not isinstance(files, (list, tuple)) or not files:
        raise ValueError("files must be a non-empty ordered list")
    members = []
    for member in files:
        if isinstance(member, CollectionMember):
            members.append(member)
        elif isinstance(member, dict):
            try:
                members.append(CollectionMember(**member))
            except TypeError as exc:
                raise ValueError("Each member accepts id, path, optional name and file_type") from exc
        else:
            raise ValueError("Each collection member must be a CollectionMember or an object")
    if len({member.id for member in members}) != len(members):
        raise ValueError("Collection member ids must be unique")
    return members


def load_collection_config(path):
    """Read JSON config, resolving member paths relative to the config file."""
    path = Path(path)
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Collection configuration must be a JSON object")
    config = dict(config)
    files = config.get("files")
    members = normalize_members(files)
    config["files"] = [CollectionMember(
        id=member.id, path=str(path.parent / member.path),
        name=member.name, file_type=member.file_type,
    ) for member in members]
    return config


@dataclass
class CollectionTable:
    """A measurement table and an ordered map back to source row positions."""

    frame: pd.DataFrame
    sources: list

    def for_metric(self, source_columns=()):
        if not isinstance(source_columns, (list, tuple)) or any(column not in SOURCE_COLUMNS for column in source_columns):
            raise ValueError(f"source_columns must be a list chosen from {SOURCE_COLUMNS}")
        if len(set(source_columns)) != len(source_columns):
            raise ValueError("source_columns must be distinct")
        frame = self.frame.copy(deep=True)
        for column in source_columns:
            values = []
            for source in self.sources:
                values.extend([source["id"]] * source["row_count"] if column == SOURCE_COLUMNS[0] else range(source["row_count"]))
            frame[column] = values
        return frame


def make_collection_table(members, frames):
    """Stack equal schemas without sorting, coercing types, or dropping members.

    Column order follows the first member. Reordered columns are aligned by
    name, but names and parsed dtypes must match exactly. This deliberately
    refuses implicit numeric conversions that can round large integer ticks.
    """
    first = frames[0]
    sources = []
    offset = 0
    aligned = []
    for member, frame in zip(members, frames):
        if set(frame.columns) != set(first.columns):
            raise ValueError(f"{member.display_name}: stacked inputs must have the same column names")
        if any(frame[column].dtype != first[column].dtype for column in first.columns):
            raise ValueError(f"{member.display_name}: stacked inputs must have the same parsed column dtypes")
        sources.append({"id": member.id, "name": member.display_name, "start_row": offset, "row_count": len(frame)})
        offset += len(frame)
        aligned.append(frame.loc[:, first.columns])
    return CollectionTable(pd.concat(aligned, ignore_index=True), sources)


@contextmanager
def using_collection_table(table, source_columns=()):
    """Let existing table metrics read a request-local input through read_file."""
    from aidrin.file_handling.file_parser import using_loaded_table

    with using_loaded_table(table.for_metric(source_columns)) as file_info:
        yield file_info
