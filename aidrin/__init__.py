import os
from celery import Celery, Task
from flask import Flask
from ._version import __version__
from .main import main as main_blueprint
from .tasks import delete_old_custom_metrics


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
        "beat_schedule": {
            "delete-old-custom-metrics": {
                "task": "delete_old_custom_metrics",
                "schedule": 120.0,
            }
        }

    }
    app.config.from_prefixed_env()

    # initialize in-memory cache
    app.TEMP_RESULTS_CACHE = {}

    celery_init_app(app)
    app.register_blueprint(
        main_blueprint, url_prefix="", name=""
    )  # register main blueprint

    # Create upload folder (Disc storage)
    UPLOAD_FOLDER = os.path.join(app.root_path, "data", "uploads")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    # clear uploads folder on app start
    for filename in os.listdir(UPLOAD_FOLDER):
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}: {e}")

    # Create custom_metrics folder
    CUSTOM_METRICS_FOLDER = os.path.join(app.root_path, "custom_metrics")
    os.makedirs(CUSTOM_METRICS_FOLDER, exist_ok=True)
    app.config["CUSTOM_METRICS_FOLDER"] = CUSTOM_METRICS_FOLDER
    app.config["CUSTOM_ALLOWED_EXTENSIONS"] = {'py'}  # Allowed file extensions for custom metrics

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

    return celery_app
