"""
Use the 'BaseFileReader' template and examples
below to add your own file parsing logic.

"""


import pandas as pd


def possible_rounded_integer_columns(frame):
    """Find floats that may be integer source values promoted by nulls."""
    return [name for name, column in frame.items()
            if pd.api.types.is_float_dtype(column.dtype) and column.hasnans
            and (column.max() >= 2**53 or column.min() <= -(2**53))]


class BaseFileReader:
    def __init__(self, file_path: str, logger):
        self.file_path = file_path
        self.logger = logger

    def read(self):
        raise NotImplementedError("Subclasses must implement the read() method.")

    # Optional method: parse hierarchical group identifiers
    def parse(self):
        return None

    # Optional method: filter by keys for hierarchical data
    def filter(self, kept_keys):
        return None
