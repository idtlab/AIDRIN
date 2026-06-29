"""Regression test for issue #125.

The Data Overview panel (/summary-statistics) must load when the uploaded
dataset has no numerical features. Previously df.describe() fell back to
object-column stats and the numeric formatter raised
``TypeError: bad operand type for abs(): 'str'``.
"""


def _upload(client, tmp_path, content, name="all_strings.csv", ftype=".csv"):
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


def test_summary_statistics_all_categorical(client, tmp_path):
    _upload(
        client,
        tmp_path,
        "name,department,level\nAlice,Engineering,Senior\nBob,Sales,Junior\n",
    )

    resp = client.get("/summary-statistics")
    assert resp.status_code == 200
    data = resp.get_json()

    # The panel must succeed, not fall back to the generic error handler.
    assert data["success"] is True
    # Record/feature counts still appear.
    assert data["records_count"] == 2
    assert data["features_count"] == 3
    # No numerical features -> empty numerical summary, rest of panel intact.
    assert data["numerical_features"] == []
    assert data["summary_statistics"] == {}
    assert sorted(data["categorical_features"]) == ["department", "level", "name"]


def test_summary_statistics_mixed_still_works(client, tmp_path):
    # A mix of numeric + categorical still reports numeric stats as before.
    _upload(
        client,
        tmp_path,
        "name,age,score\nAlice,25,90.5\nBob,30,85.0\n",
        name="mixed.csv",
    )

    resp = client.get("/summary-statistics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert sorted(data["numerical_features"]) == ["age", "score"]
    assert "age" in data["summary_statistics"]
    assert data["categorical_features"] == ["name"]
