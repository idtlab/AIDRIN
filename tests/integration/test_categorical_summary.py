"""Data Overview should summarise categorical features.

The numerical describe() table ignores categorical columns and histograms are
numeric-only, so categorical features previously had no per-column summary.
``/summary-statistics`` now returns a ``categorical_summary`` with count, unique,
top (most frequent value) and its frequency per categorical column.
"""


def _upload(client, tmp_path, content, name="mixed.csv", ftype=".csv"):
    path = tmp_path / name
    path.write_text(content)
    with open(path, "rb") as f:
        resp = client.post(
            "/inspector",
            data={"file": (f, name), "fileTypeSelector": ftype},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    return client


def test_categorical_summary_present_and_correct(client, tmp_path):
    _upload(
        client,
        tmp_path,
        "name,age,department,status\n"
        "Alice,25,Engineering,Active\n"
        "Bob,30,Sales,Active\n"
        "Carol,35,Engineering,Inactive\n"
        "Dan,40,Engineering,Active\n",
    )

    resp = client.get("/summary-statistics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True

    cs = data["categorical_summary"]
    # Only categorical columns appear (age is numeric -> excluded).
    assert set(cs) == {"name", "department", "status"}

    assert cs["department"] == {
        "count": 4,
        "unique": 2,
        "top": "Engineering",
        "freq": 3,
        "freq_pct": 75.0,
    }
    assert cs["status"]["top"] == "Active"
    assert cs["status"]["freq"] == 3
    assert cs["status"]["freq_pct"] == 75.0
    assert cs["name"]["unique"] == 4


def test_summary_statistics_all_categorical(client, tmp_path):
    # No numeric columns: numerical summary is empty, categorical summary populated.
    _upload(
        client,
        tmp_path,
        "name,department,level\nAlice,Engineering,Senior\nBob,Sales,Junior\n",
        name="all_cat.csv",
    )
    resp = client.get("/summary-statistics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["numerical_features"] == []
    assert data["summary_statistics"] == {}
    assert set(data["categorical_summary"]) == {"name", "department", "level"}


def test_categorical_summary_empty_for_all_numeric(client, tmp_path):
    _upload(
        client,
        tmp_path,
        "a,b\n1,2\n3,4\n",
        name="nums.csv",
    )
    resp = client.get("/summary-statistics")
    data = resp.get_json()
    assert data["success"] is True
    assert data["categorical_summary"] == {}


def test_boolean_column_is_categorical(client, tmp_path):
    # Boolean columns are treated as categorical, not numerical.
    _upload(
        client,
        tmp_path,
        "active,age\nTrue,25\nFalse,30\nTrue,35\n",
        name="bool.csv",
    )
    resp = client.get("/summary-statistics")
    data = resp.get_json()
    assert data["success"] is True
    assert data["numerical_features"] == ["age"]
    assert "active" not in data["numerical_features"]
    assert "active" in data["categorical_summary"]
    active = data["categorical_summary"]["active"]
    assert active["count"] == 3
    assert active["unique"] == 2
    assert active["top"] == "True"
    assert active["freq"] == 2
