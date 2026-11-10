"""
Use the 'BaseFileReader' template and examples
below to add your own file parsing logic.

"""


from dataclasses import dataclass

import pandas as pd


def possible_rounded_integer_columns(frame):
    """Find float columns where type inference can round source integers."""
    return [name for name, column in frame.items()
            if pd.api.types.is_float_dtype(column.dtype)
            and (column.max() >= 2**53 or column.min() <= -(2**53))]


def preserve_integer_values(frame, name, values):
    """Restore source integers without changing ordinary numeric columns."""
    integers = [value for value in values if type(value) is int]
    if not any(abs(value) >= 2**53 for value in integers):
        return
    if all(value is None or type(value) is int for value in values):
        dtype = "UInt64" if max(integers) > 2**63 - 1 else "Int64"
        try:
            frame[name] = pd.array(values, dtype=dtype)
            return
        except (OverflowError, TypeError, ValueError):
            pass
    # Preserve the inferred numeric column for existing metrics and keep the
    # source values separately for audits that require exact integer ticks.
    exact_integer_values(frame, create=True)[name] = tuple(values)


@dataclass
class _ExactIntegerValues:
    columns: dict


def exact_integer_values(frame, *, create=False):
    """Return exact row-aligned values for columns without a lossless fixed dtype."""
    exact = frame.attrs.get("aidrin_exact_integer_values")
    if not isinstance(exact, _ExactIntegerValues):
        if not create:
            return {}
        exact = _ExactIntegerValues({})
        frame.attrs["aidrin_exact_integer_values"] = exact
    return exact.columns


def exact_integer_frame(frame, columns=None):
    """Use source values for requested columns without mutating the parsed table."""
    exact = exact_integer_values(frame)
    replacements = {name: values for name, values in exact.items() if columns is None or name in columns}
    if replacements:
        frame = frame.copy(deep=False)
        for name, values in replacements.items():
            frame[name] = pd.array(values, dtype=object)
    return frame


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
