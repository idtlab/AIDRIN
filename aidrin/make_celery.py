from aidrin import app
from aidrin.logging_utils import setup_logging

setup_logging()  # Initialize logging before creating the app
celery_app = app.extensions["celery"] 