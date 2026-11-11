"""Trusted example adapter for explicit time columns in separate component files.

The manifest supplies record identity, never inferred from file names. This is
a time-only projection: amplitudes, orientation and scientific eligibility are
not assessed. No time axis is synthesized, shifted, sorted or repaired.
"""

import json
from pathlib import Path

import pandas as pd

from aidrin.file_handling.custom_loader import using_custom_loader
from aidrin.file_handling.file_parser import read_file


def load(path, **kwargs):
    """Read a JSON manifest and return independent sequences in manifest order."""
    manifest_path = Path(path)
    records = json.loads(manifest_path.read_text())
    if not isinstance(records, list) or not records:
        raise ValueError("Manifest must be a non-empty list of records")
    frames = []
    identities = set()
    for record in records:
        required = ("record_id", "station", "component", "path", "timestamp_column")
        if not isinstance(record, dict) or any(
            not isinstance(record.get(key), str) or not record[key].strip() for key in required
        ):
            raise ValueError(f"Each record needs non-empty strings: {', '.join(required)}")
        identity = record["record_id"]
        if identity in identities:
            raise ValueError(f"Duplicate record_id: {identity}")
        identities.add(identity)
        source = manifest_path.parent / record["path"]
        file_type = record.get("file_type", source.suffix.lower())
        # The outer read_file is invoking this loader. Suspend it for member
        # reads, which must go through the ordinary AIDRIN readers.
        with using_custom_loader(None):
            frame = read_file((str(source), source.name, file_type))
        column = record["timestamp_column"]
        if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique or column not in frame:
            raise ValueError(f"Record {identity}: no unique timestamp column {column}")
        if frame.empty:
            raise ValueError(f"Record {identity}: empty component file")
        frames.append(pd.DataFrame({
            "record_id": identity,
            "station": record["station"],
            "component": record["component"],
            "source_row_position": range(len(frame)),
            "time": frame[column].reset_index(drop=True),
        }))
    # Object time columns preserve integer ticks when another record contains
    # floating-point times. Let the audit validate each value independently.
    for frame in frames:
        frame["time"] = frame["time"].astype(object)
    return pd.concat(frames, ignore_index=True)
