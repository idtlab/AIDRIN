import pytest
from aidrin.file_handling.file_parser import infer_file_type, READER_MAP, file_extension


@pytest.mark.parametrize("filename,expected", [
    ("data.csv", ".csv"),
    ("DATA.CSV", ".csv"),
    ("set.json", ".json"),
    ("a.npz", ".npz"),
    ("b.h5", ".h5"),
    ("c.parquet", ".parquet"),
    ("sheet.xlsx", ".xls, .xlsb, .xlsx, .xlsm"),
    ("sheet.xls", ".xls, .xlsb, .xlsx, .xlsm"),
])
def test_infer_known_extensions(filename, expected):
    if expected not in READER_MAP:
        pytest.skip(f"{expected} reader not registered on this branch")
    assert infer_file_type(filename) == expected


def test_infer_unknown_extension_returns_none():
    assert infer_file_type("notes.txt") is None
    assert infer_file_type("noext") is None
    assert infer_file_type(None) is None


def test_infer_real_extension_helper():
    assert file_extension("Sheet.XLSX") == ".xlsx"
    assert file_extension("a.csv") == ".csv"
    assert file_extension("noext") == ""


def test_infer_double_extension_uses_last_segment():
    assert infer_file_type("data.csv.bak") is None
    assert infer_file_type("data.bak.csv") == ".csv"
