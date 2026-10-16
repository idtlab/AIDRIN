"""Regression test for issue #125.

The Data Overview panel (/summary-statistics) must load when the uploaded
dataset has no numerical features. Previously df.describe() fell back to
object-column stats and the numeric formatter raised
``TypeError: bad operand type for abs(): 'str'``.

Wide datasets are paged: only the requested features are described.
"""

from unittest.mock import patch

import pandas as pd
import pytest

import web.routes.core as core
from web.routes.utils import generate_metric_cache_key


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


def _wide_csv(blank_categorical=False):
    """30 numeric columns then 10 categorical columns, two varying rows."""
    header = [f"n{i}" for i in range(30)] + [f"c{i}" for i in range(10)]
    row_a = [str(i) for i in range(30)] + [f"a{i}" for i in range(10)]
    row_b = [str(i + 1) for i in range(30)] + [f"b{i}" for i in range(10)]
    if blank_categorical:
        row_b[30] = ""
    return ",".join(header) + "\n" + ",".join(row_a) + "\n" + ",".join(row_b) + "\n"


def _dataset_fields(data):
    return {
        "records_count": data["records_count"],
        "features_count": data["features_count"],
        "numerical_features": data["numerical_features"],
        "categorical_features": data["categorical_features"],
        "all_features": data["all_features"],
    }


def test_summary_statistics_default_page_returns_25_features(client, tmp_path):
    _upload(client, tmp_path, _wide_csv(), name="wide.csv")
    data = client.get("/summary-statistics").get_json()
    assert data["success"] is True
    pagination = data["pagination"]
    assert pagination == {
        "page": 1,
        "page_size": 25,
        "total_pages": 2,
        "total_features": 40,
        "start": 1,
        "end": 25,
    }
    assert list(data["summary_statistics"]) == [f"n{i}" for i in range(25)]
    assert data["categorical_summary"] == {}


def test_summary_statistics_explicit_page_keeps_numerical_order(client, tmp_path):
    _upload(client, tmp_path, _wide_csv(), name="wide.csv")
    data = client.get("/summary-statistics?page=2&page_size=25").get_json()
    assert data["success"] is True
    assert list(data["summary_statistics"]) == [f"n{i}" for i in range(25, 30)]
    assert list(data["categorical_summary"]) == [f"c{i}" for i in range(10)]
    assert data["pagination"]["start"] == 26
    assert data["pagination"]["end"] == 40
    assert data["pagination"]["page"] == 2


def test_summary_statistics_final_page_is_shorter(client, tmp_path):
    _upload(client, tmp_path, _wide_csv(), name="wide.csv")
    data = client.get("/summary-statistics?page=2&page_size=25").get_json()
    page_features = list(data["summary_statistics"]) + list(data["categorical_summary"])
    assert len(page_features) == 15
    assert data["pagination"]["end"] - data["pagination"]["start"] + 1 == 15


def test_summary_statistics_empty_and_out_of_range_pages(client, tmp_path):
    path = tmp_path / "times.parquet"
    pd.DataFrame({"when": pd.to_datetime(["2020-01-01", "2020-01-02"])}).to_parquet(path)
    with open(path, "rb") as handle:
        uploaded = client.post(
            "/inspector",
            data={"file": (handle, "times.parquet"), "fileTypeSelector": ".parquet"},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
    assert uploaded.status_code == 302
    empty = client.get("/summary-statistics").get_json()
    assert empty["success"] is True
    assert empty["numerical_features"] == []
    assert empty["categorical_features"] == []
    assert empty["pagination"]["total_features"] == 0
    assert empty["pagination"]["total_pages"] == 1
    assert empty["pagination"]["start"] == 0
    assert empty["pagination"]["end"] == 0

    _upload(client, tmp_path, _wide_csv(), name="wide.csv")
    beyond = client.get("/summary-statistics?page=9&page_size=25").get_json()
    assert beyond["success"] is True
    assert beyond["summary_statistics"] == {}
    assert beyond["categorical_summary"] == {}
    assert beyond["histograms"] == {}
    assert beyond["pagination"]["page"] == 9
    assert beyond["pagination"]["total_pages"] == 2
    assert beyond["pagination"]["start"] == 0
    assert beyond["pagination"]["end"] == 0
    assert beyond["pagination"]["total_features"] == 40


@pytest.mark.parametrize("query", [
    "page=0",
    "page=-1",
    "page=abc",
    "page=1.5",
    "page_size=0",
    "page_size=101",
])
def test_summary_statistics_rejects_invalid_page_params(client, tmp_path, app, query):
    _upload(client, tmp_path, _wide_csv(), name="wide.csv")
    before = set(app.TEMP_RESULTS_CACHE)
    with patch.object(core, "load_dataframe") as loader:
        response = client.get(f"/summary-statistics?{query}")
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["message"]
    assert loader.call_count == 0
    assert set(app.TEMP_RESULTS_CACHE) == before


def test_summary_statistics_dataset_fields_are_stable_across_pages(client, tmp_path):
    _upload(client, tmp_path, _wide_csv(), name="wide.csv")
    first = client.get("/summary-statistics?page=1&page_size=25").get_json()
    second = client.get("/summary-statistics?page=2&page_size=25").get_json()
    assert _dataset_fields(first) == _dataset_fields(second)
    assert first["numerical_features"] == [f"n{i}" for i in range(30)]
    assert first["categorical_features"] == [f"c{i}" for i in range(10)]
    assert first["features_count"] == 40
    assert first["records_count"] == 2


def test_summary_statistics_pages_do_not_share_features(client, tmp_path):
    _upload(client, tmp_path, _wide_csv(), name="wide.csv")
    first = client.get("/summary-statistics?page=1&page_size=10").get_json()
    second = client.get("/summary-statistics?page=2&page_size=10").get_json()
    first_names = set(first["summary_statistics"]) | set(first["categorical_summary"])
    second_names = set(second["summary_statistics"]) | set(second["categorical_summary"])
    assert first_names == {f"n{i}" for i in range(10)}
    assert second_names == {f"n{i}" for i in range(10, 20)}
    assert first_names.isdisjoint(second_names)
    assert set(first["histograms"]) == {f"n{i}_light" for i in range(10)}
    assert set(second["histograms"]) == {f"n{i}_light" for i in range(10, 20)}


def test_summary_statistics_computes_only_the_requested_page(client, tmp_path):
    """Spies fail an implementation that computes every column and slices after."""
    _upload(client, tmp_path, _wide_csv(), name="wide.csv")
    original_describe = pd.DataFrame.describe

    def _describe(self, *args, **kwargs):
        return original_describe(self, *args, **kwargs)

    with (
        patch.object(core, "summary_histograms", wraps=core.summary_histograms) as histograms,
        patch.object(pd.DataFrame, "describe", autospec=True, side_effect=_describe) as describe,
        patch.object(core, "hashable_series", wraps=core.hashable_series) as hashed,
    ):
        numeric_page = client.get("/summary-statistics?page=2&page_size=10")
        categorical_page = client.get("/summary-statistics?page=4&page_size=10")

    assert numeric_page.status_code == 200
    assert categorical_page.status_code == 200
    assert histograms.call_count == 1
    assert list(histograms.call_args.args[0].columns) == [f"n{i}" for i in range(10, 20)]
    assert describe.call_count == 1
    assert list(describe.call_args.args[0].columns) == [f"n{i}" for i in range(10, 20)]
    assert [call.args[0].name for call in hashed.call_args_list] == [f"c{i}" for i in range(10)]


def test_summary_statistics_cache_is_per_page(client, tmp_path):
    _upload(client, tmp_path, _wide_csv(), name="wide.csv")
    with patch.object(core, "summary_histograms", wraps=core.summary_histograms) as spy:
        first = client.get("/summary-statistics?page=1&page_size=25")
        second = client.get("/summary-statistics?page=1&page_size=25")
        assert spy.call_count == 1
        third = client.get("/summary-statistics?page=2&page_size=25")
        assert spy.call_count == 2
        fourth = client.get("/summary-statistics?page=1&page_size=10")
        assert spy.call_count == 3
    assert first.get_json() == second.get_json()
    assert third.get_json()["pagination"]["page"] == 2
    assert fourth.get_json()["pagination"]["page_size"] == 10
    assert list(fourth.get_json()["summary_statistics"]) == [f"n{i}" for i in range(10)]


def test_summarystats_cache_key_includes_page_size_and_selection(app):
    with app.test_request_context():
        from flask import session

        session["user_id"] = "user-a"
        page1 = generate_metric_cache_key(
            "data.csv", "summarystats", selected_keys=["b", "a"], page=1, page_size=25,
        )
        page2 = generate_metric_cache_key(
            "data.csv", "summarystats", selected_keys=["b", "a"], page=2, page_size=25,
        )
        size10 = generate_metric_cache_key(
            "data.csv", "summarystats", selected_keys=["b", "a"], page=1, page_size=10,
        )
        other_selection = generate_metric_cache_key(
            "data.csv", "summarystats", selected_keys=["a"], page=1, page_size=25,
        )
        assert len({page1, page2, size10, other_selection}) == 4
        assert page1.endswith("summarystats:keys:a, b:page:1:size:25")
        assert page1 == generate_metric_cache_key(
            "data.csv", "summarystats", selected_keys=["b", "a"],
        )

        session["user_id"] = "user-b"
        other_user = generate_metric_cache_key(
            "data.csv", "summarystats", selected_keys=["b", "a"], page=1, page_size=25,
        )
        other_file = generate_metric_cache_key(
            "other.csv", "summarystats", selected_keys=["b", "a"], page=1, page_size=25,
        )
        assert page1 != other_user
        assert "user:user-a" in page1 and "file:data.csv" in page1
        assert "user:user-b" in other_user
        assert "file:other.csv" in other_file
