import csv

import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader

# Delimiters a file named .csv is realistically written with.
_DELIMITERS = ",;\t|"
# Enough leading bytes for the sniffer to compare several rows.
_SNIFF_BYTES = 64 * 1024


class csvReader(BaseFileReader):
    def read(self):
        return pd.read_csv(self.file_path, index_col=False, sep=self._detect_delimiter())

    def _detect_delimiter(self):
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
            with open(self.file_path, newline="", errors="replace") as handle:
                sample = handle.read(_SNIFF_BYTES)
            delimiter = csv.Sniffer().sniff(sample, delimiters=_DELIMITERS).delimiter
        except (OSError, csv.Error):
            return ","

        if delimiter != ",":
            self.logger.info("Reading %s with delimiter %r.", self.file_path, delimiter)
        return delimiter
