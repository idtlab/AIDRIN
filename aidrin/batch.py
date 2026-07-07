"""Session-free batch helpers shared by the web UI, CLI, and library users."""

import os

import pandas as pd

from aidrin.file_handling.file_parser import read_file


def _summarize_one(file_info):
    path, name, file_type = file_info
    if not path:
        return {
            "name": name, "type": file_type,
            "records": None, "features": None,
            "numerical": None, "categorical": None,
            "size_bytes": None, "status": "error",
            "error": "No file path provided.",
        }
    size = None
    try:
        if path and os.path.exists(path):
            size = os.path.getsize(path)
    except OSError:
        size = None

    result = read_file(file_info)  # DataFrame | None | str
    if isinstance(result, pd.DataFrame):
        # Same dtype convention as the Data Overview panel: numeric vs string.
        numerical = int(sum(pd.api.types.is_numeric_dtype(d) for d in result.dtypes))
        categorical = int(sum(pd.api.types.is_string_dtype(d) for d in result.dtypes))
        return {
            "name": name, "type": file_type,
            "records": int(len(result)),
            "features": int(len(result.columns)),
            "numerical": numerical, "categorical": categorical,
            "size_bytes": size, "status": "ok", "error": None,
        }

    message = result if isinstance(result, str) else (
        "Could not read the file. The format may be unsupported or the file "
        "may be corrupted."
    )
    return {
        "name": name, "type": file_type,
        "records": None, "features": None,
        "numerical": None, "categorical": None,
        "size_bytes": size, "status": "error", "error": message,
    }


def summarize_files(file_infos):
    """Return {"files": [per_file, ...], "totals": {...}} for a list of files.

    Computes structural facts only (records, features, size, load status) — no
    metrics. A file that fails to load becomes a status:"error" row and never
    aborts the batch. ``file_infos`` is a list of (path, name, type) tuples.
    """
    files = [_summarize_one(fi) for fi in file_infos]
    by_type = {}
    for f in files:
        by_type[f["type"]] = by_type.get(f["type"], 0) + 1
    totals = {
        "file_count": len(files),
        "ok_count": sum(1 for f in files if f["status"] == "ok"),
        "error_count": sum(1 for f in files if f["status"] == "error"),
        "total_records": sum(f["records"] or 0 for f in files),
        "total_size_bytes": sum(f["size_bytes"] or 0 for f in files),
        "by_type": by_type,
    }
    return {"files": files, "totals": totals}
