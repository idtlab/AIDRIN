"""Shared fixtures for integration tests."""

import io
import os
import tempfile

import pytest
from web import create_app


@pytest.fixture
def app():
    """Create a new Flask app instance for testing."""
    app = create_app()
    app.config.update(TESTING=True)

    # Run Celery tasks eagerly (synchronously) so no Redis is required
    app.config["CELERY"]["task_always_eager"] = True
    app.config["CELERY"]["task_eager_propagates"] = True

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
