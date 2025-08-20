import os
import time

from celery import Celery, Task
from celery.schedules import crontab
from flask import Flask
from ._version import __version__
from .main import main as main_blueprint


# create app config
def create_app():
    app = Flask(__name__)

    @app.context_processor
    def inject_version():
        return dict(app_version=__version__)  # global variable to access version in templates

    app.secret_key = "aidrin"

    # Celery Config
    app.config["CELERY"] = {
        "broker_url": "redis://localhost:6379/0",
        "result_backend": "redis://localhost:6379/0",
        "task_ignore_result": True,
        "task_soft_time_limit": 6,
        "task_time_limit": 10,
        "worker_hijack_root_logger": False,
        "result_expires": 600,
        "beat_schedule": {  # Add periodic cleanup schedule
            "cleanup-old-files": {
                "task": "tasks.cleanup_files",
                "schedule": crontab(minute="*/10"),  # every 10 minutes
            },
        },
    }
    app.config.from_prefixed_env()

    # initialize in-memory cache
    app.TEMP_RESULTS_CACHE = {}

    celery_init_app(app)
    app.register_blueprint(main_blueprint, url_prefix="", name="")

    # Create upload folder (Disc storage)
    UPLOAD_FOLDER = os.path.join(app.root_path, "data", "uploads")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

    # Create custom_metrics folder
    CUSTOM_METRICS_FOLDER = os.path.join(app.root_path, "custom_metrics")
    os.makedirs(CUSTOM_METRICS_FOLDER, exist_ok=True)
    app.config["CUSTOM_METRICS_FOLDER"] = CUSTOM_METRICS_FOLDER
    app.config["ALLOWED_EXTENSIONS"] = {"py"}

    return app


# Configure Celery with Flask
def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.set_default()
    app.extensions["celery"] = celery_app

    # Register cleanup task here
    register_cleanup_task(celery_app, app)

    return celery_app


# Celery task: cleanup old files
def register_cleanup_task(celery_app: Celery, app: Flask):
    @celery_app.task(name="tasks.cleanup_files")
    def cleanup_files(max_age_seconds: int = 3600):
        """
        Delete files older than `max_age_seconds` (default 1 hour),
        except __init__.py and base_dr.py.
        """
        now = time.time()

        # Folders to clean
        folders = [app.config["UPLOAD_FOLDER"], app.config["CUSTOM_METRICS_FOLDER"]]
        exclude = {"__init__.py", "base_dr.py"}

        for folder in folders:
            for filename in os.listdir(folder):
                if filename in exclude:
                    continue
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path):
                        file_age = now - os.path.getmtime(file_path)
                        if file_age > max_age_seconds:
                            os.remove(file_path)
                            print(f"[CLEANUP] Deleted stale file: {file_path}")
                except Exception as e:
                    print(f"[CLEANUP] Failed to delete {file_path}: {e}")
