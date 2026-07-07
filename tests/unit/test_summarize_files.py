import os
import tempfile

import pandas as pd

from aidrin.batch import summarize_files


def _csv(rows="a,b\n1,2\n3,4\n"):
    f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    f.write(rows)
    f.close()
    return f.name


def test_ok_file_reports_structure_no_metrics():
    path = _csv()
    try:
        out = summarize_files([(path, "data.csv", ".csv")])
    finally:
        os.unlink(path)
    row = out["files"][0]
    assert row["status"] == "ok"
    assert row["records"] == 2
    assert row["features"] == 2
    assert row["numerical"] == 2  # both columns are integers
    assert row["categorical"] == 0
    assert row["size_bytes"] > 0
    assert row["error"] is None
    assert set(row.keys()) == {"name", "type", "records", "features",
                               "numerical", "categorical",
                               "size_bytes", "status", "error"}


def test_numeric_and_categorical_counts():
    import pandas as pd
    f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    pd.DataFrame({"age": [1, 2], "city": ["A", "B"], "score": [1.0, 2.0]}).to_csv(
        f.name, index=False
    )
    f.close()
    try:
        row = summarize_files([(f.name, "d.csv", ".csv")])["files"][0]
    finally:
        os.unlink(f.name)
    assert row["numerical"] == 2  # age, score
    assert row["categorical"] == 1  # city


def test_unsupported_type_is_error_not_crash():
    out = summarize_files([("/nope/x.txt", "x.txt", ".txt")])
    row = out["files"][0]
    assert row["status"] == "error"
    assert row["records"] is None and row["features"] is None
    assert row["error"]


def test_missing_file_is_error():
    out = summarize_files([("/nope/missing.csv", "missing.csv", ".csv")])
    assert out["files"][0]["status"] == "error"


def test_none_path_reports_clear_error():
    out = summarize_files([(None, "data.csv", ".csv")])
    row = out["files"][0]
    assert row["status"] == "error"
    assert "path" in row["error"].lower()


def test_one_bad_file_does_not_abort_batch():
    good = _csv()
    try:
        out = summarize_files([
            (good, "good.csv", ".csv"),
            ("/nope/bad.csv", "bad.csv", ".csv"),
        ])
    finally:
        os.unlink(good)
    assert [f["status"] for f in out["files"]] == ["ok", "error"]


def test_totals():
    a = _csv("a,b\n1,2\n3,4\n5,6\n")
    b = _csv("x\n1\n")
    try:
        out = summarize_files([
            (a, "a.csv", ".csv"),
            (b, "b.csv", ".csv"),
            ("/nope/c.csv", "c.csv", ".csv"),
        ])
    finally:
        try:
            os.unlink(a)
        except OSError:
            pass
        try:
            os.unlink(b)
        except OSError:
            pass
    t = out["totals"]
    assert t["file_count"] == 3
    assert t["ok_count"] == 2
    assert t["error_count"] == 1
    assert t["total_records"] == 4
    assert t["total_size_bytes"] > 0
    assert t["by_type"] == {".csv": 3}


def test_empty_input():
    out = summarize_files([])
    assert out["files"] == []
    assert out["totals"]["file_count"] == 0
