"""Tests for additional metric submission paths."""


# -------------------------------------------------
# HIPAA Compliance
# -------------------------------------------------


def test_hipaa_scan(uploaded_client):
    """Submit HIPAA identifier scan."""
    response = uploaded_client.post(
        "/hipaa-compliance?return_type=json",
        data={
            "hipaa identifier scan": "yes",
            "HIPAA identifiers for HIPAA compliance": "age,income",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None


# -------------------------------------------------
# Privacy Preservation (sync metrics)
# -------------------------------------------------


def test_privacy_k_anonymity(uploaded_client):
    """Submit k-anonymity check."""
    response = uploaded_client.post(
        "/privacy-preservation?return_type=json",
        data={
            "k-anonymity": "yes",
            "quasi identifiers for k-anonymity": "gender,education",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None


def test_privacy_no_selection(uploaded_client):
    """Submit privacy with no metrics selected."""
    response = uploaded_client.post(
        "/privacy-preservation?return_type=json",
        data={},
        follow_redirects=True,
    )
    assert response.status_code == 200


# -------------------------------------------------
# Fairness - statistical rate
# -------------------------------------------------


def test_fairness_statistical_rate(uploaded_client):
    """Submit statistical rate check."""
    response = uploaded_client.post(
        "/fairness?return_type=json",
        data={
            "statistical rate": "yes",
            "features for statistical rate": "gender",
            "target for statistical rate": "income",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None


# -------------------------------------------------
# Class Imbalance with distance metric
# -------------------------------------------------


def test_class_imbalance_with_distance(uploaded_client):
    """Submit class imbalance with custom distance metric."""
    response = uploaded_client.post(
        "/class-imbalance?return_type=json",
        data={
            "class imbalance": "yes",
            "target features for class imbalance": "gender",
            "distance metric for class imbalance": "CH",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None


# -------------------------------------------------
# Data Quality - all three at once
# -------------------------------------------------


def test_data_quality_all_metrics(uploaded_client):
    """Submit all three data quality metrics at once."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={
            "completeness": "yes",
            "outliers": "yes",
            "duplicity": "yes",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "Completeness" in data
    assert "Outliers" in data
    assert "Duplicity" in data


# -------------------------------------------------
# Correlation Analysis
# -------------------------------------------------


def test_correlation_analysis(uploaded_client):
    """Submit correlation analysis."""
    response = uploaded_client.post(
        "/correlation-analysis?return_type=json",
        data={
            "correlations": "yes",
            "numerical features": "age,income",
            "categorical features": "gender",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None


def test_correlation_no_selection(uploaded_client):
    """Submit correlation with nothing selected."""
    response = uploaded_client.post(
        "/correlation-analysis?return_type=json",
        data={},
        follow_redirects=True,
    )
    assert response.status_code == 200
