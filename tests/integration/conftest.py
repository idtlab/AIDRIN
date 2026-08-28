"""Shared fixtures for integration tests."""

import pytest
from web import create_app


@pytest.fixture
def app(tmp_path):
    """Create a new Flask app instance for testing."""
    app = create_app()
    app.config.update(TESTING=True)

    # Run Celery tasks eagerly (synchronously) so no Redis is required
    app.config["CELERY"]["task_always_eager"] = True
    app.config["CELERY"]["task_eager_propagates"] = True

    # Routes read these paths from current_app.config at request time, so
    # redirecting them here keeps tests from writing real files into the
    # live project folders (aidrin/custom_metrics/, data/uploads/).
    upload_folder = tmp_path / "uploads"
    upload_folder.mkdir()
    app.config["UPLOAD_FOLDER"] = str(upload_folder)

    custom_metrics_folder = tmp_path / "custom_metrics"
    custom_metrics_folder.mkdir()
    app.config["CUSTOM_METRICS_FOLDER"] = str(custom_metrics_folder)

    remedy_folder = custom_metrics_folder / "remedy_data"
    remedy_folder.mkdir()
    app.config["REMEDY_FOLDER"] = str(remedy_folder)

    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def sample_csv(tmp_path):
    """Create a temporary CSV file for upload tests."""
    csv_content = "age,income,education,gender\n25,50000,Bachelor,M\n30,60000,Master,F\n35,70000,PhD,M\n28,45000,Bachelor,F\n40,80000,PhD,M\n"
    csv_path = tmp_path / "test_data.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def uploaded_client(client, sample_csv, app):
    """A test client with a CSV file already uploaded in session.

    Returns (client, filename) tuple so tests can verify the uploaded file name.
    """
    with open(sample_csv, "rb") as f:
        response = client.post(
            "/inspector",
            data={
                "file": (f, "test_data.csv"),
                "fileTypeSelector": ".csv",
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
    assert response.status_code == 302
    return client


@pytest.fixture
def sample_json(tmp_path):
    """Create a temporary JSON file (list of records) for upload tests."""
    import json

    records = [
        {"age": 25, "income": 50000, "education": "Bachelor", "gender": "M"},
        {"age": 30, "income": 60000, "education": "Master", "gender": "F"},
        {"age": 35, "income": 70000, "education": "PhD", "gender": "M"},
    ]
    json_path = tmp_path / "test_data.json"
    json_path.write_text(json.dumps(records))
    return json_path


@pytest.fixture
def uploaded_client_json(client, sample_json, app):
    """A test client with a JSON file already uploaded in session."""
    with open(sample_json, "rb") as f:
        response = client.post(
            "/inspector",
            data={
                "file": (f, "test_data.json"),
                "fileTypeSelector": ".json",
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
    assert response.status_code == 302
    return client
