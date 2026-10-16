"""Unit tests for Data Overview page helpers (issue #139)."""

import pytest

from aidrin.structured_data_metrics.summary_pagination import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    paginate_features,
    parse_page_params,
)


def test_parse_page_params_none_defaults():
    assert parse_page_params(None, None) == (DEFAULT_PAGE, DEFAULT_PAGE_SIZE)


def test_parse_page_params_rejects_non_numeric_page_size():
    with pytest.raises(ValueError, match="page_size must be a positive integer"):
        parse_page_params(1, "abc")


def test_parse_page_params_allows_max_page_size():
    assert parse_page_params(1, 100) == (1, MAX_PAGE_SIZE)
    assert parse_page_params(1, "100") == (1, MAX_PAGE_SIZE)


def test_parse_page_params_rejects_over_max_page_size():
    with pytest.raises(ValueError, match=f"page_size must be at most {MAX_PAGE_SIZE}"):
        parse_page_params(1, 101)
    with pytest.raises(ValueError, match=f"page_size must be at most {MAX_PAGE_SIZE}"):
        parse_page_params(1, "101")


@pytest.mark.parametrize("page", [0, -1, -10])
def test_parse_page_params_rejects_non_positive_page(page):
    with pytest.raises(ValueError, match="page must be a positive integer"):
        parse_page_params(page, 25)


def test_paginate_features_empty_dataset():
    result = paginate_features([], [], page=1, page_size=25)
    assert result["numerical"] == []
    assert result["categorical"] == []
    assert result["pagination"] == {
        "page": 1,
        "page_size": 25,
        "total_pages": 1,
        "total_features": 0,
        "start": 0,
        "end": 0,
    }


def test_paginate_features_page_size_larger_than_total():
    numerical = [f"n{i}" for i in range(3)]
    categorical = [f"c{i}" for i in range(2)]
    result = paginate_features(numerical, categorical, page=1, page_size=25)
    assert result["numerical"] == numerical
    assert result["categorical"] == categorical
    assert result["pagination"] == {
        "page": 1,
        "page_size": 25,
        "total_pages": 1,
        "total_features": 5,
        "start": 1,
        "end": 5,
    }


def test_paginate_features_slice_crosses_numerical_categorical_boundary():
    numerical = [f"n{i}" for i in range(30)]
    categorical = [f"c{i}" for i in range(10)]
    result = paginate_features(numerical, categorical, page=2, page_size=25)
    assert result["numerical"] == [f"n{i}" for i in range(25, 30)]
    assert result["categorical"] == [f"c{i}" for i in range(10)]
    assert result["pagination"]["start"] == 26
    assert result["pagination"]["end"] == 40
    assert result["pagination"]["total_pages"] == 2
    assert result["pagination"]["total_features"] == 40


def test_paginate_features_out_of_range_page_echoes_request_with_empty_slice():
    """An out-of-range page is not an error: empty lists, start = end = 0."""
    numerical = [f"n{i}" for i in range(30)]
    categorical = [f"c{i}" for i in range(10)]
    result = paginate_features(numerical, categorical, page=9, page_size=25)
    assert result["numerical"] == []
    assert result["categorical"] == []
    assert result["pagination"]["page"] == 9
    assert result["pagination"]["start"] == 0
    assert result["pagination"]["end"] == 0
    assert result["pagination"]["total_pages"] == 2
    assert result["pagination"]["total_features"] == 40
