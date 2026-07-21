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


def test_data_quality_duplicates_by_features(uploaded_client):
    """Submit duplicate detection restricted to selected features."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={
            "duplicate detection by features": "yes",
            "features for duplicate detection": ["gender"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "Duplicates by Selected Features" in data
    result = data["Duplicates by Selected Features"]
    assert "Error" not in result
    assert result["Total rows"] == 5
    assert result["Duplicate count"] == 3  # gender: M x3, F x2 -> (3-1)+(2-1)=3


def test_data_quality_duplicates_by_features_no_selection(uploaded_client):
    """Submitting the checkbox without picking any features returns an error, not a 500."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={"duplicate detection by features": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "Error" in data["Duplicates by Selected Features"]


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


# -------------------------------------------------
# Data Structure - Constant Feature Count
# -------------------------------------------------


def test_constant_feature_count_no_constant_columns(uploaded_client):
    """The default sample dataset (age/income/education/gender) has no constant columns."""
    response = uploaded_client.post(
        "/data-structure?return_type=json",
        data={"constant feature count": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "Constant Feature Count" in data
    result = data["Constant Feature Count"]
    assert result["Constant feature count"] == 0
    assert result["Total features"] == 4
    assert result["Constant features"] == {}


def test_constant_feature_count_detects_constant_column(client, tmp_path):
    """A dataset with a single-value column is flagged by name."""
    csv_content = "id,region\n1,us\n2,us\n3,us\n"
    csv_path = tmp_path / "constant_test.csv"
    csv_path.write_text(csv_content)

    with open(csv_path, "rb") as f:
        upload_response = client.post(
            "/inspector",
            data={"file": (f, "constant_test.csv"), "fileTypeSelector": ".csv"},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
    assert upload_response.status_code == 302

    response = client.post(
        "/data-structure?return_type=json",
        data={"constant feature count": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    result = data["Constant Feature Count"]
    assert result["Constant feature count"] == 1
    assert result["Constant features"] == {"region": "us"}


def test_constant_feature_count_no_selection(uploaded_client):
    """Submitting with nothing checked returns an empty result, not an error."""
    response = uploaded_client.post(
        "/data-structure?return_type=json",
        data={},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data == {}
