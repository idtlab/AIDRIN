"""Shared fixtures for integration tests."""

import io
import os
import tempfile

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

    # Isolate runtime dirs from the real data/ folder so tests don't pollute it
    # (uploads, the per-user file lists under <UPLOAD_FOLDER>/../filelists, and
    # generated custom metrics).
    uploads = tmp_path / "uploads"
    custom_metrics = tmp_path / "custom_metrics"
    remedy = custom_metrics / "remedy_data"
    for d in (uploads, custom_metrics, remedy):
        d.mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(uploads)
    app.config["CUSTOM_METRICS_FOLDER"] = str(custom_metrics)
    app.config["REMEDY_FOLDER"] = str(remedy)

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
