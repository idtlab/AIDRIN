import csv
import io

import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader, possible_rounded_integer_columns

# Delimiters a file named .csv is realistically written with.
_DELIMITERS = ",;\t|"
# Enough leading bytes for the sniffer to compare several rows.
_SNIFF_BYTES = 64 * 1024


class csvReader(BaseFileReader):
    def read(self):
        return self._read(self.file_path, self._detect_delimiter())

    def read_sample(self, rows, columns):
        with open(self.file_path, "rb") as handle:
            prefix = handle.read(_SNIFF_BYTES + 1)
        if len(prefix) > _SNIFF_BYTES:
            prefix = prefix[:_SNIFF_BYTES].rpartition(b"\n")[0]
        delimiter = self._detect_delimiter(prefix.decode("utf-8-sig", errors="replace"))
        return self._read(io.BytesIO(prefix), delimiter, nrows=rows, usecols=columns)

    @staticmethod
    def _read(source, delimiter, nrows=None, usecols=None):
        frame = pd.read_csv(source, index_col=False, sep=delimiter, nrows=nrows, usecols=usecols)
        candidates = possible_rounded_integer_columns(frame)
        if not candidates:
            return frame
        if hasattr(source, "seek"):
            source.seek(0)
        # Read only suspect columns as text so a blank cell cannot cause
        # binary64 rounding before the exact integer conversion.
        raw = pd.read_csv(source, index_col=False, sep=delimiter, nrows=nrows, usecols=candidates, dtype="string")
        for name in candidates:
            values = raw[name].dropna().str.strip()
            if not values.str.fullmatch(r"[+-]?[0-9]+").all():
                continue
            integers = [int(value) if not pd.isna(value) else None for value in raw[name]]
            dtype = "UInt64" if max(value for value in integers if value is not None) > 2**63 - 1 else "Int64"
            try:
                frame[name] = pd.array(integers, dtype=dtype)
            except (OverflowError, TypeError, ValueError):
                # Integers outside both native 64-bit ranges stay exact as text.
                frame[name] = raw[name]
        return frame

    def _detect_delimiter(self, sample=None):
        """Delimiter reported by csv.Sniffer, or comma when it cannot tell.

        A file named .csv is not always comma-separated. Parsing a pipe-, tab-
        or semicolon-separated file as comma-separated counts the separators
        inside quoted text as fields, so the rows look ragged: pandas then
        either raises a ParserError or, when the header has fewer commas than
        the data rows, warns and silently drops columns.

        csv.Sniffer is quoting-aware, so a delimiter inside a quoted column
        name does not mislead it. It raises when there is nothing to detect,
        as in a single-column file, and comma is the right answer there.

        The result is handed to read_csv as ``sep``: passing ``sep=None``
        instead would select pandas' python engine, whose stdlib csv backend
        rejects any field larger than 128 KiB.
        """
        try:
            if sample is None:
                with open(self.file_path, newline="", errors="replace") as handle:
                    sample = handle.read(_SNIFF_BYTES)
            delimiter = csv.Sniffer().sniff(sample, delimiters=_DELIMITERS).delimiter
        except (OSError, csv.Error):
            return ","

        if delimiter != ",":
            self.logger.info("Reading %s with delimiter %r.", self.file_path, delimiter)
        return delimiter
