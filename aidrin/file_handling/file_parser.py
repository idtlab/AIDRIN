import logging
import os

from aidrin.file_handling.readers.base_reader import BaseFileReader
from aidrin.file_handling.readers.csv_reader import csvReader
from aidrin.file_handling.readers.excel_reader import excelReader
from aidrin.file_handling.readers.hdf5_reader import hdf5Reader
from aidrin.file_handling.readers.json_reader import jsonReader
from aidrin.file_handling.readers.npz_reader import npzReader

# To add support for new file types without touching this file,
# use register_reader() defined below.

# Reader Map. Used to create file type specific parsing
READER_MAP = {
    ".csv": csvReader,
    ".npz": npzReader,
    ".xls, .xlsb, .xlsx, .xlsm": excelReader,
    ".json": jsonReader,
    ".h5": hdf5Reader,
}

# Supported file types. Read on front end to create select features.
SUPPORTED_FILE_TYPES = [
    (".csv", "CSV"),
    (".xls, .xlsb, .xlsx, .xlsm", "Excel"),
    (".json", "JSON"),
    (".npz", "NumPy"),
    (".h5", "HDF5"),
]

# logger config
file_upload_time_log = logging.getLogger("file_upload")


def register_reader(extension: str, reader_cls, force: bool = False):
    """Register a custom reader for a file extension.

    Example:
        from aidrin.file_handling.readers.base_reader import BaseFileReader
        from aidrin.file_handling.file_parser import register_reader
        import pandas as pd

        class MyFormatReader(BaseFileReader):
            def read(self):
                return pd.DataFrame(...)

        register_reader(".myf", MyFormatReader)
    """
    if not isinstance(extension, str) or not extension.startswith("."):
        raise ValueError(f"extension must be a dot-prefixed string like '.csv', got: {extension!r}")

    if not (isinstance(reader_cls, type) and issubclass(reader_cls, BaseFileReader)):
        raise TypeError(f"{reader_cls} must be a subclass of BaseFileReader")

    if extension in READER_MAP and not force:
        raise ValueError(
            f"A reader for '{extension}' is already registered ({READER_MAP[extension].__name__}). "
            f"Pass force=True to override."
        )

    READER_MAP[extension] = reader_cls

    # keep SUPPORTED_FILE_TYPES in sync; skip if already listed
    already_listed = any(ext == extension for ext, _ in SUPPORTED_FILE_TYPES)
    if not already_listed:
        SUPPORTED_FILE_TYPES.append((extension, extension.lstrip(".").upper()))


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
    file_path, file_name, file_type = file_info
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
    file_path, _, file_type = file_info
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


def read_file(file_info):
    """

    Parses a given file into pandas Dataframe.

    Parameters
    ----------
    file_info: tuple
        (file_path, file_name, file_type) where:
            -file_path: str, relative or absolute path of the file.
            -file_name: str, file name.
            -file_type: str, file format. Passed from front end select value.
    Returns
    ----------
    pd.Dataframe, None, or str
    Parsed data as a DataFrame, None if file is unsupported,
    or error message string if an exception occurs.
    """
    file_upload_time_log.info("File parsing initiated...")

    file_path, file_name, file_type = file_info
    # path and name are passed from flask, if not in session = None
    if not file_path and file_name:
        file_upload_time_log.error("Missing file path or file name.")
        return None

    # Check if the file actually exists
    if file_path and not os.path.exists(file_path):
        file_upload_time_log.error(f"File not found: {file_path}")
        return f"File not found: {file_path}"

    try:
        df = None
        if file_type in READER_MAP:
            df = READER_MAP[file_type](file_path, file_upload_time_log).read()
            file_upload_time_log.info("File successfully parsed!")
            # file_upload_time_log.info(df.to_string())
        else:
            file_upload_time_log.warning(f"Unsupported file type: {file_type}")

        return df

    except Exception as e:
        file_upload_time_log.error(f"Error while Reading File: {e}")
        return str(e)
