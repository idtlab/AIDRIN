"""Structural file summaries shared by the local workspace and Compute worker."""

import logging
from pathlib import Path

import pandas as pd

from aidrin.file_handling.file_parser import read_file


logger = logging.getLogger(__name__)


def overview_columns(frame):
    numerical = [
        name for name, dtype in frame.dtypes.items()
        if pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype)
    ]
    categorical = [
        name for name, dtype in frame.dtypes.items()
        if pd.api.types.is_string_dtype(dtype) or pd.api.types.is_bool_dtype(dtype)
    ]
    return numerical, categorical


def summarize_workspace_file(path, name, file_type):
    """Read one file and return counts, or an actionable error for that row."""
    try:
        size = Path(path).stat().st_size
    except OSError:
        return {"error": "File is unavailable."}
    try:
        frame = read_file((path, name, file_type))
    except Exception:
        logger.warning("Unable to summarize workspace file", exc_info=True)
        frame = None
    if not isinstance(frame, pd.DataFrame):
        return {"size": size, "error": "Unable to read a table. Open the file to check its format and dataset selection."}
    numerical, categorical = overview_columns(frame)
    return {
        "size": size, "records": len(frame), "features": len(frame.columns),
        "numerical": len(numerical), "categorical": len(categorical),
    }


def summarize_workspace_directory(path, limit):
    """Discover supported immediate children and summarize them on the worker."""
    from aidrin.file_handling.file_parser import GLOBUS_FILE_TYPES
    from aidrin.headless.runners import _normalize_file_type

    supported = {file_type for file_type, _ in GLOBUS_FILE_TYPES}
    files = []
    try:
        for item in Path(path).iterdir():
            file_type = _normalize_file_type(None, item.name)
            if file_type not in supported or item.is_symlink():
                continue
            if not item.is_file() and not (file_type == ".zarr" and item.is_dir()):
                continue
            files.append((item, file_type))
            if len(files) > limit:
                return {"Error": f"The directory contains more than {limit} supported files."}
    except OSError:
        return {"Error": "Unable to open the directory on the Compute endpoint."}
    if not files:
        return {"Error": "No supported files found in the directory."}
    return {"format": "aidrin.workspace-directory", "files": [
        {"path": str(item), "name": item.name, "file_type": file_type,
         "summary": summarize_workspace_file(str(item), item.name, file_type)}
        for item, file_type in sorted(files, key=lambda file: (file[0].name.casefold(), file[0].name))
    ]}
