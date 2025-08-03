from aidrin import create_app
from aidrin.logging import setup_logging

setup_logging()  # Initialize logging before creating the app
flask_app = create_app()
celery_app = flask_app.extensions["celery"]

# Import tasks to register them with Celery
from aidrin.structured_data_metrics.privacy_measure import calculate_single_attribute_risk_score, calculate_multiple_attribute_risk_score
