"""Tests for Flask app setup and configuration."""

import os

from aidrin._version import __version__


# -------------------------------------------------
# App setup tests
# -------------------------------------------------


def test_celery_extension_initialized(app):
    """Check Celery is initialized and attached to Flask app."""
    assert "celery" in app.extensions
    celery = app.extensions["celery"]
    assert celery.conf.task_always_eager is True
    assert celery.conf.task_eager_propagates is True


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


def test_app_version(app):
    """Check version string is set."""
    assert __version__
