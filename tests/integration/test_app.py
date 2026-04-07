import os
import pytest
from web import create_app
from aidrin._version import __version__


@pytest.fixture
def app():
    """Create a new Flask app instance for testing."""
    app = create_app()
    app.config.update(
        TESTING=True,
    )

    # Run Celery tasks eagerly (synchronously) so no Redis is required in tests
    app.config["CELERY"]["task_always_eager"] = True
    app.config["CELERY"]["task_eager_propagates"] = True

    return app


@pytest.fixture
def client(app):
    """Fixture for test client."""
    return app.test_client()


# -------------------------------------------------
# Route tests
# -------------------------------------------------

def test_home(client):
    response = client.get("/")
    assert response.status_code == 200


def test_upload_file_route(client):
    response = client.get("/upload-file")
    assert response.status_code == 200


def test_publications(client):
    response = client.get("/publications")
    assert response.status_code == 200


def test_fair(client):
    response = client.get("/fair-assessment")
    assert response.status_code == 200


def test_non_existent_route(client):
    response = client.get("/non-existent")
    assert response.status_code == 404


# -------------------------------------------------
# App setup tests from __init__.py
# -------------------------------------------------

def test_celery_extension_initialized(app):
    """Check Celery is initialized and attached to Flask app."""
    assert "celery" in app.extensions
    celery = app.extensions["celery"]
    assert celery.conf.task_always_eager is True
    assert celery.conf.task_eager_propagates is True


def test_app_version_injection(client):
    """Check that app_version from context processor appears in rendered HTML."""
    response = client.get("/")
    html = response.data.decode()
    assert f"v{__version__}" in html


def test_upload_folder_created(app):
    """Check that the upload folder is created at app startup."""
    upload_folder = app.config["UPLOAD_FOLDER"]
    assert os.path.isdir(upload_folder)


def test_temp_results_cache_exists(app):
    """Check that TEMP_RESULTS_CACHE exists and is dict-like."""
    assert hasattr(app, "TEMP_RESULTS_CACHE")
    assert isinstance(app.TEMP_RESULTS_CACHE, dict)


def test_celery_task_execution(app):
    """Define and run a simple Celery task inside the app context."""
    celery = app.extensions["celery"]

    @celery.task
    def add(x, y):
        return x + y

    result = add.delay(2, 3)
    output = result.get(timeout=5)
    assert output == 5
