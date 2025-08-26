import os

from celery import Celery, Task
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
        "broker_url": "redis://localhost:6379/0",  #
        "result_backend": "redis://localhost:6379/0",
        "task_ignore_result": False,  # Store task results in backend for status checking
        "task_soft_time_limit": 300,  # Task is soft killed
        "task_time_limit": 360,  # Task is force killed after this time
        "worker_hijack_root_logger": False,  # prevent default celery logging configuration
        "result_expires": 600,  # Delete results from db after 10 min
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

    # Clean up old uploaded files on app start (older than 1 hour)
    import time
    current_time = time.time()
    max_age_seconds = 3600  # 1 hour
    files_removed = 0

    for filename in os.listdir(UPLOAD_FOLDER):
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        try:
            if os.path.isfile(file_path):
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > max_age_seconds:
                    os.remove(file_path)
                    files_removed += 1
                    print(f"Cleaned up old file on startup: {filename}")
        except Exception as e:
            print(f"Failed to delete {file_path}: {e}")

    if files_removed > 0:
        print(f"Startup cleanup completed: {files_removed} old files removed")

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
