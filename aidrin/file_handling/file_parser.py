import logging
import os
import tempfile

from aidrin.file_handling.readers.csv_reader import csvReader
from aidrin.file_handling.readers.excel_reader import excelReader
from aidrin.file_handling.readers.hdf5_reader import hdf5Reader
from aidrin.file_handling.readers.json_reader import jsonReader
from aidrin.file_handling.readers.npz_reader import npzReader
from aidrin.file_handling.readers.parquet_reader import parquetReader
from aidrin.file_handling.readers.root_reader import rootReader

# Notes:
# To add support for new file types:
# - Add a new subclass of BaseFileReader with a .read() method
#       (and optionally .parse(), .filter()) to 'file_readers'.
# - Register the class in READER_MAP.
# - Add a display name and extension to SUPPORTED_FILE_TYPES for the front end.

# Reader Map. Used to create file type specific parsing
READER_MAP = {
    ".csv": csvReader,
    ".npz": npzReader,
    ".xls, .xlsb, .xlsx, .xlsm": excelReader,
    ".json": jsonReader,
    ".h5": hdf5Reader,
    ".parquet": parquetReader,
    ".root": rootReader,
    # Add additional file types here
}

# Supported file types. Read on front end to create select features.
SUPPORTED_FILE_TYPES = [
    (".csv", "CSV"),
    (".xls, .xlsb, .xlsx, .xlsm", "Excel"),
    (".json", "JSON"),
    (".npz", "NumPy"),
    (".h5", "HDF5"),
    (".parquet", "Parquet"),
    (".root", "ROOT"),
    # Add additional file types here using the format:
    # (file_type,file_type_name)
]

# logger config
file_upload_time_log = logging.getLogger("file_upload")

# ---------------------------------------------------------------------------
# Frame cache
#
# The first ``read_file`` for an upload materialises the parsed DataFrame into an
# on-disk Arrow/Feather artifact next to the source.  Subsequent calls (one per
# metric task) reload that artifact instead of re-parsing the source.
#
# Only formats whose reader output round-trips through Feather without dtype or
# value drift are cached (verified at pandas 2.2.1).  json/npz/hdf5 build object
# and list columns that Feather would silently alter or reject, so they are never
# cached and always parsed directly — preserving their exact original behaviour.
# ---------------------------------------------------------------------------
_FRAME_CACHE_SUFFIX = ".aidrin.feather"
_CACHEABLE_FILE_TYPES = {".csv", ".parquet", ".xls, .xlsb, .xlsx, .xlsm"}


def _frame_cache_enabled():
    # Opt-out switch so the cache can be disabled without code changes.
    return os.environ.get("AIDRIN_FRAME_CACHE", "1") != "0"


def _frame_cache_path(file_path):
    # Key on (size, mtime_ns) so any content change yields a different cache file
    # name: a changed source simply misses the cache (and the old artifact is
    # later reaped) rather than risking a stale read from a coarse mtime compare.
    st = os.stat(file_path)
    return f"{file_path}.{st.st_size}-{st.st_mtime_ns}{_FRAME_CACHE_SUFFIX}"


def clear_frame_cache(file_path):
    """Best-effort removal of the on-disk Feather cache sidecar for ``file_path``.

    The web app reaps its cache sidecars via the ``UPLOAD_FOLDER`` prune task
    (see ``worker.tasks.prune_upload_folder``), but CLI invocations read files
    from arbitrary, unmanaged locations on disk with nothing to sweep them
    later. Callers that own a single, short-lived invocation (e.g. the CLI's
    ``main()``) should call this once after the run so the sidecar doesn't
    linger next to the source file. Safe to call even when no cache was
    written (unsupported type, disabled cache, or write failure).
    """
    if not file_path or not os.path.exists(file_path):
        return
    try:
        cache_path = _frame_cache_path(file_path)
    except OSError:
        return
    try:
        os.remove(cache_path)
    except OSError:
        pass


def _write_frame_cache(cache_path, df):
    """Best-effort atomic Feather write of ``df`` to ``cache_path``.

    Returns ``True`` on success.  Returns ``False`` — leaving no artifact — on
    any failure (unwritable directory, unserialisable frame, missing pyarrow) so
    the caller can fall back to the in-memory frame without surfacing an error.
    """
    try:
        cache_dir = os.path.dirname(cache_path) or "."
        fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=cache_dir)
        os.close(fd)
        try:
            df.to_feather(tmp_path)
            os.replace(tmp_path, cache_path)
            return True
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    except Exception as e:
        file_upload_time_log.warning("Frame cache write skipped: %s", e)
        return False


def parse_file(file_info):
    """

    Parses a structured file to extract top-level keys or group identifiers.

    Parameters
    ----------
    file_info: tuple
        (file_path, file_name, file_type) where:
            -file_path: str, relative or absolute path of the file.
            -file_name: str, file name.
            -file_type: str, file format. Passed from front end select value.
    Returns
    ----------
    list, None, or str
    List of top-level keys if available, None if unsupported, or error
    message string if parsing fails.
    """
    file_path, file_name, file_type = file_info[:3]
    file_upload_time_log.info("Parsing File for keys...")
    try:
        if file_type in READER_MAP:
            keys = READER_MAP[file_type](file_path, file_upload_time_log).parse()
            return keys
        else:
            file_upload_time_log.warning(f"Unsupported file type: {file_type}")
            return None
    except Exception as e:
        file_upload_time_log.error(f"Error while File Parsing: {e}")
        return str(e)


def filter_file(file_info, kept_keys):
    """
    Filters the file to include only the specified
    top-level keys provided in kept_keys.

    Parameters
    ----------
    file_info: tuple
        (file_path, file_name, file_type) where:
            -file_path: str, relative or absolute path of the file.
            -file_name: str, file name.
            -file_type: str, file format. Passed from front end select value.
    Returns
    ----------
    str or None
    New filtered file path as str, None if the file type is not supported,
    or error message string if unsuccessful.
    """
    file_path, _, file_type = file_info[:3]
    file_upload_time_log.info(f"Filtering file on Keys: {kept_keys}")
    if file_type in READER_MAP:
        filtered_data_path = READER_MAP[file_type](
            file_path, file_upload_time_log
        ).filter(kept_keys)
        file_upload_time_log.info(f"Filtered File saved to: {filtered_data_path}")
    else:
        file_upload_time_log.warning(f"Unsupported file type: {file_type}")
        return None

    return filtered_data_path


# Parses the uploaded file into a pandas database


def read_file(file_info, columns=None):
    """

    Parses a given file into pandas Dataframe.

    For dtype-stable formats (csv, parquet, excel) the parsed frame is cached on
    disk so that repeated calls for the same upload reload the cached artifact
    instead of re-parsing the source.  ``columns`` lets a caller request only a
    subset of columns, read directly from the cache when available.

    Parameters
    ----------
    file_info: tuple
        (file_path, file_name, file_type) where:
            -file_path: str, relative or absolute path of the file.
            -file_name: str, file name.
            -file_type: str, file format. Passed from front end select value.
    columns: list of str, optional
        When given, only these columns are returned.
    Returns
    ----------
    pd.Dataframe, None, or str
    Parsed data as a DataFrame, None if file is unsupported,
    or error message string if an exception occurs.
    """
    file_upload_time_log.info("File parsing initiated...")

    file_path, file_name, file_type = file_info[:3]
    selected_keys = file_info[3] if len(file_info) > 3 else None
    # path and name are passed from flask, if not in session = None
    if not file_path and file_name:
        file_upload_time_log.error("Missing file path or file name.")
        return None

    # Check if the file actually exists
    if file_path and not os.path.exists(file_path):
        file_upload_time_log.error(f"File not found: {file_path}")
        return f"File not found: {file_path}"

    if file_type not in READER_MAP:
        file_upload_time_log.warning(f"Unsupported file type: {file_type}")
        return None

    try:
        cacheable = _frame_cache_enabled() and file_type in _CACHEABLE_FILE_TYPES
        cache_path = _frame_cache_path(file_path) if cacheable else None

        # Fast path: reload a fresh cache without touching the source.
        if cacheable and os.path.exists(cache_path):
            try:
                import pandas as pd

                df = pd.read_feather(cache_path, columns=columns)
                file_upload_time_log.info("File loaded from frame cache!")
                return df
            except Exception as e:
                # Corrupt/unreadable cache — fall through and re-parse.
                file_upload_time_log.warning(
                    "Frame cache unreadable, rebuilding: %s", e
                )

        # Slow path: parse the source once.
        reader_cls = READER_MAP[file_type]
        if file_type in (".h5", ".root"):
            df = reader_cls(
                file_path, file_upload_time_log, selected_keys=selected_keys
            ).read()
        else:
            df = reader_cls(file_path, file_upload_time_log).read()
        file_upload_time_log.info("File successfully parsed!")

        # Best-effort cache for future calls. Failure is non-fatal: we still
        # return the freshly parsed frame below, so a read-only directory or an
        # unserialisable frame never turns a successful parse into an error.
        if cacheable:
            _write_frame_cache(cache_path, df)

        if columns is not None:
            df = df[columns]
        return df

    except Exception as e:
        file_upload_time_log.error(f"Error while Reading File: {e}", exc_info=True)
        return "Unable to read the uploaded file."
