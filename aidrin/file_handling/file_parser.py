import logging

from aidrin.file_handling.readers.csv_reader import csvReader
from aidrin.file_handling.readers.excel_reader import excelReader
from aidrin.file_handling.readers.hdf5_reader import hdf5Reader
from aidrin.file_handling.readers.json_reader import jsonReader
from aidrin.file_handling.readers.npz_reader import npzReader

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
    # Add additional file types here
}

# Supported file types. Read on front end to create select features.
SUPPORTED_FILE_TYPES = [
    (".csv", "CSV"),
    (".xls, .xlsb, .xlsx, .xlsm", "Excel"),
    (".json", "JSON"),
    (".npz", "NumPy"),
    (".h5", "HDF5"),
    # Add additional file types here using the format:
    # (file_type,file_type_name)
]

# logger config
file_upload_time_log = logging.getLogger("file_upload")


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
