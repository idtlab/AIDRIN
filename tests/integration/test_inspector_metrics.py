"""Tests for metric submission from the inspector."""

import json


# -------------------------------------------------
# Summary statistics endpoint
# -------------------------------------------------


def test_summary_statistics_with_file(uploaded_client):
    """/summary-statistics should return JSON with dataset info."""
    response = uploaded_client.get("/summary-statistics")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["records_count"] == 5
    assert data["features_count"] == 4
    assert "age" in data["numerical_features"]
    assert "gender" in data["categorical_features"]
    assert "summary_statistics" in data
    assert "histograms" in data


def test_summary_statistics_without_file(client):
    """/summary-statistics without a file should return error."""
    response = client.get("/summary-statistics")
    data = response.get_json()
    assert data["success"] is False


# -------------------------------------------------
# Feature set endpoint
# -------------------------------------------------


def test_feature_set_with_file(uploaded_client):
    """/feature-set should return feature lists."""
    response = uploaded_client.post("/feature-set")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert "age" in data["numerical_features"]
    assert "gender" in data["categorical_features"]
    assert "all_features" in data


def test_feature_set_without_file(client):
    """/feature-set without a file should return error."""
    response = client.post("/feature-set")
    data = response.get_json()
    assert data["success"] is False


# -------------------------------------------------
# Data Quality metric
# -------------------------------------------------


def test_data_quality_completeness(uploaded_client):
    """Submit completeness check — should return JSON results."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={"completeness": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert "Completeness" in data


def test_data_quality_outliers(uploaded_client):
    """Submit outliers check."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={"outliers": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert "Outliers" in data


def test_data_quality_duplicity(uploaded_client):
    """Submit duplicity check."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={"duplicity": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert "Duplicity" in data


def test_data_quality_no_selection(uploaded_client):
    """Submit with no metrics selected — should still return 200."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={},
        follow_redirects=True,
    )
    assert response.status_code == 200


# -------------------------------------------------
# Fairness metric
# -------------------------------------------------


def test_fairness_representation_rate(uploaded_client):
    """Submit representation rate check."""
    response = uploaded_client.post(
        "/fairness?return_type=json",
        data={
            "representation rate": "yes",
            "features for representation rate": "gender",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None


# -------------------------------------------------
# Class Imbalance metric
# -------------------------------------------------


def test_class_imbalance(uploaded_client):
    """Submit class imbalance check."""
    response = uploaded_client.post(
        "/class-imbalance?return_type=json",
        data={
            "class imbalance": "yes",
            "target features for class imbalance": "gender",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None


# -------------------------------------------------
# Error handling
# -------------------------------------------------


def test_metric_without_file(client):
    """Posting to a metric route without a file should not crash."""
    response = client.post(
        "/data-quality?return_type=json",
        data={"completeness": "yes"},
        follow_redirects=True,
    )
    # Should either redirect or return an error — not 500
    assert response.status_code in (200, 302)
