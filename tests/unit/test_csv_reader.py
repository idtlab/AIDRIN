"""Unit tests for the CSV reader's delimiter handling.

A file named .csv is not always comma-separated. When separators appear inside
quoted text, parsing such a file as comma-separated makes the rows look ragged
and pandas raises a ParserError, which the web layer turned into "The CSV file
could not be read."
"""

import logging

import pandas as pd
import pytest

from aidrin.file_handling.file_parser import read_file
from aidrin.file_handling.readers.csv_reader import csvReader


@pytest.fixture
def logger():
    return logging.getLogger("test_csv_reader")


def _write(path, rows, delimiter):
    """Write rows as a quoted, delimiter-separated file."""
    lines = [delimiter.join(f'"{cell}"' for cell in row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# Commas inside the quoted text are what break the comma parse.
ROWS = [
    ["id", "description", "value"],
    ["1", "first, with a comma", "10"],
    ["2", "second, also with, commas", "20"],
    ["3", "third, and, several, more, commas", "30"],
]


@pytest.mark.parametrize("delimiter", ["|", ";", "\t"])
def test_non_comma_delimiters_are_detected(tmp_path, logger, delimiter):
    path = _write(tmp_path / "data.csv", ROWS, delimiter)
    frame = csvReader(str(path), logger).read()

    assert list(frame.columns) == ["id", "description", "value"]
    assert len(frame) == 3
    assert frame["description"].iloc[0] == "first, with a comma"


def test_comma_delimited_file_is_unaffected(tmp_path, logger):
    path = _write(tmp_path / "data.csv", [["a", "b"], ["1", "2"]], ",")
    frame = csvReader(str(path), logger).read()

    assert list(frame.columns) == ["a", "b"]
    assert frame["a"].iloc[0] == 1


def test_field_larger_than_the_stdlib_csv_limit(tmp_path, logger):
    """The sniffed delimiter must go to the C engine.

    sep=None would select pandas' python engine, whose stdlib csv backend
    refuses any field over 128 KiB; the reported file has one.
    """
    big = "x" * (200 * 1024)
    path = _write(tmp_path / "data.csv", [["id", "blob"], ["1", f"a, {big}"]], "|")
    frame = csvReader(str(path), logger).read()

    assert len(frame) == 1
    assert len(frame["blob"].iloc[0]) > 128 * 1024


def test_delimiter_inside_a_quoted_column_name(tmp_path, logger):
    """Counting separators would tie here and wrongly pick comma.

    csv.Sniffer is quoting-aware, so the commas inside the first column name
    do not count as separators.
    """
    path = tmp_path / "data.csv"
    path.write_text('"x,y,z"|a|b\n1|2|3\n4|5|6\n', encoding="utf-8")

    frame = csvReader(str(path), logger).read()
    assert list(frame.columns) == ["x,y,z", "a", "b"]
    assert len(frame) == 2


def test_single_column_file_still_reads(tmp_path, logger):
    """No delimiter to sniff; the plain comma read already handles it."""
    path = tmp_path / "data.csv"
    path.write_text("only\n1\n2\n", encoding="utf-8")

    frame = csvReader(str(path), logger).read()
    assert list(frame.columns) == ["only"]
    assert len(frame) == 2


def test_unreadable_file_keeps_the_original_parser_error(tmp_path, logger):
    """A genuinely ragged comma file must not be masked by the retry."""
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n3,4,5,6\n", encoding="utf-8")

    with pytest.raises(pd.errors.ParserError):
        csvReader(str(path), logger).read()


def test_read_file_returns_a_frame_for_a_pipe_delimited_csv(tmp_path):
    """End to end through read_file, which every dataset read funnels through."""
    path = _write(tmp_path / "piped.csv", ROWS, "|")
    frame = read_file((str(path), "piped.csv", ".csv"))

    assert isinstance(frame, pd.DataFrame)
    assert list(frame.columns) == ["id", "description", "value"]
