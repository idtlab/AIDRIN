import logging
import os
import time
from celery import Celery, Task
from flask import Flask
from aidrin._version import __version__
from aidrin.logging import setup_logging

startup_log = logging.getLogger("startup")


def _configure_matplotlib():
    """Set matplotlib defaults for clean white-background plots."""
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": "none",
        "axes.facecolor": "none",
        "axes.edgecolor": "#6b7280",
        "axes.labelcolor": "#6b7280",
        "text.color": "#6b7280",
        "xtick.color": "#6b7280",
        "ytick.color": "#6b7280",
        "figure.figsize": (8, 6),
        "savefig.facecolor": "none",
        "savefig.edgecolor": "none",
        "savefig.transparent": True,
    })


def create_app():
    _configure_matplotlib()
    setup_logging()
    app = Flask(__name__)

    # Optional OpenTelemetry instrumentation
    from web.telemetry import init_telemetry
    init_telemetry(app)

    @app.context_processor
    def inject_version():
        return dict(app_version=__version__)

    app.secret_key = os.environ.get("AIDRIN_SECRET_KEY", "aidrin")

    # Celery config
    app.config["CELERY"] = {
        "broker_url": "redis://localhost:6379/0",
        "result_backend": "redis://localhost:6379/0",
        "beat_schedule": {
            "delete-old-custom-metrics": {
                "task": "delete_old_custom_metrics",
                "schedule": 120.0,
            }
        },
        "task_ignore_result": False,
        "task_soft_time_limit": 300,
        "task_time_limit": 360,
        "worker_hijack_root_logger": False,
        "result_expires": 600,
    }
    app.config.from_prefixed_env()

    # Maximum upload size (default 1 GB; override via AIDRIN_MAX_UPLOAD_MB).
    try:
        max_upload_mb = int(os.environ.get("AIDRIN_MAX_UPLOAD_MB", 1024))
    except ValueError:
        max_upload_mb = 1024
    app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024

    # Maximum number of files per upload batch.
    try:
        app.config["AIDRIN_MAX_UPLOAD_FILES"] = int(
            os.environ.get("AIDRIN_MAX_UPLOAD_FILES", 50)
        )
    except ValueError:
        app.config["AIDRIN_MAX_UPLOAD_FILES"] = 50

    @app.errorhandler(413)
    def _request_too_large(error):
        from flask import jsonify, request
        msg = "Upload too large for the server limit."
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"success": False, "message": msg}), 413
        return msg, 413

    # Initialize in-memory cache
    app.TEMP_RESULTS_CACHE = {}

    celery_init_app(app)

    # Register all blueprints
    from web.routes import register_blueprints
    register_blueprints(app)

    # Import task so Celery discovers it on startup
    from worker.tasks import delete_old_custom_metrics  # noqa: F401

    # project_root is the parent of web/
    project_root = os.path.dirname(app.root_path)

    # Upload folder at project root (outside the package)
    upload_folder = os.path.join(project_root, "data", "uploads")
    os.makedirs(upload_folder, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = upload_folder

    # Clean up old uploaded files on startup (older than 1 hour)
    current_time = time.time()
    max_age_seconds = 3600
    files_removed = 0

    for filename in os.listdir(upload_folder):
        file_path = os.path.join(upload_folder, filename)
        try:
            if os.path.isfile(file_path):
                if current_time - os.path.getmtime(file_path) > max_age_seconds:
                    os.remove(file_path)
                    files_removed += 1
                    startup_log.info("Cleaned up old file on startup: %s", filename)
        except Exception as e:
            startup_log.warning("Failed to delete %s: %s", file_path, e)

    # Runtime custom-metric files live OUTSIDE the package, at the project root,
    # so writing/deleting them does NOT trigger the Flask --debug auto-reloader
    # (which watches .py files under the package). The base class they import,
    # `aidrin.custom_metrics.base_dr`, still resolves via the installed package.
    custom_metrics_folder = os.path.join(project_root, "data", "custom_metrics")
    os.makedirs(custom_metrics_folder, exist_ok=True)
    app.config["CUSTOM_METRICS_FOLDER"] = custom_metrics_folder
    app.config["CUSTOM_ALLOWED_EXTENSIONS"] = {"py"}

    remedy_folder = os.path.join(custom_metrics_folder, "remedy_data")
    os.makedirs(remedy_folder, exist_ok=True)
    app.config["REMEDY_FOLDER"] = remedy_folder

    metrics_removed = 0
    exclude = {"__init__.py", "base_dr.py"}
    for filename in os.listdir(custom_metrics_folder):
        if filename in exclude:
            continue
        file_path = os.path.join(custom_metrics_folder, filename)
        try:
            if os.path.isfile(file_path):
                if current_time - os.path.getmtime(file_path) > max_age_seconds:
                    os.remove(file_path)
                    metrics_removed += 1
                    startup_log.info("Deleted old custom metric: %s", filename)
        except Exception as e:
            startup_log.warning("Failed to delete %s: %s", file_path, e)

    remedy_removed = 0
    for filename in os.listdir(remedy_folder):
        file_path = os.path.join(remedy_folder, filename)
        try:
            if os.path.isfile(file_path):
                if current_time - os.path.getmtime(file_path) > max_age_seconds:
                    os.remove(file_path)
                    remedy_removed += 1
                    startup_log.info("Deleted old remedy file: %s", filename)
        except Exception as e:
            startup_log.warning("Failed to delete %s: %s", file_path, e)

    if files_removed > 0 or metrics_removed > 0 or remedy_removed > 0:
        startup_log.info(
            "Startup cleanup completed: %d upload(s) + %d custom metric(s) + %d remedy file(s) removed",
            files_removed, metrics_removed, remedy_removed,
        )

    return app


def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.set_default()
    app.extensions["celery"] = celery_app

    return celery_app


__all__ = ["create_app", "celery_init_app"]
