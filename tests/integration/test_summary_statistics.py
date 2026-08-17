"""Regression test for issue #125.

The Data Overview panel (/summary-statistics) must load when the uploaded
dataset has no numerical features. Previously df.describe() fell back to
object-column stats and the numeric formatter raised
``TypeError: bad operand type for abs(): 'str'``.
"""

from unittest.mock import patch

import web.routes.core as core


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


def test_summary_statistics_second_request_is_cached(client, tmp_path):
    """A repeat GET for the same file must reuse the cached result, not recompute."""
    _upload(
        client,
        tmp_path,
        "name,age,score\nAlice,25,90.5\nBob,30,85.0\n",
        name="mixed.csv",
    )

    with patch.object(core, "summary_histograms", wraps=core.summary_histograms) as spy:
        first = client.get("/summary-statistics")
        second = client.get("/summary-statistics")
        assert spy.call_count == 1

    assert first.status_code == second.status_code == 200
    assert first.get_json() == second.get_json()


def test_summary_statistics_different_file_not_cached(client, tmp_path):
    """Switching to a different uploaded file must not return the prior file's cache."""
    _upload(
        client,
        tmp_path,
        "name,age,score\nAlice,25,90.5\nBob,30,85.0\n",
        name="mixed.csv",
    )
    first = client.get("/summary-statistics").get_json()

    _upload(
        client,
        tmp_path,
        "name,department,level\nAlice,Engineering,Senior\nBob,Sales,Junior\n",
        name="all_strings.csv",
    )
    second = client.get("/summary-statistics").get_json()

    assert first["records_count"] == second["records_count"] == 2
    assert second["numerical_features"] == []
    assert second["summary_statistics"] == {}
    assert sorted(second["categorical_features"]) == ["department", "level", "name"]
