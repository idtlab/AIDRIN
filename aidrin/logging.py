import logging
import os


# Initialize time log
def setup_logging():
    log_dir = os.path.join(os.path.dirname(__file__), "data", "logs")
    os.makedirs(log_dir, exist_ok=True)  # Ensure logs directory exists

    log_path = os.path.join(log_dir, "aidrin.log")
    open(log_path, "w").close()  # Clear the log file on startup
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M.%S",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )
    # Suppress specific Celery loggers
    for name in [
        "celery.app.trace",
        "celery.worker.strategy",
        "kombu.transport.redis",
        "celery.worker.consumer",
        "celery.redirected",
    ]:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Suppress werkzeug logs for POST and GET requests to declutter -- but keep start up messages
    class SuppressRequestsFilter(logging.Filter):
        def filter(self, record):
            return not ("GET" in record.getMessage() or "POST" in record.getMessage())

    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.addFilter(SuppressRequestsFilter())
