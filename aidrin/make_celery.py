from aidrin import create_app
from aidrin.logging import setup_logging
from flask import session, Flask
setup_logging()  # Initialize logging before creating the app
flask_app = create_app()
celery_app = flask_app.extensions["celery"]
