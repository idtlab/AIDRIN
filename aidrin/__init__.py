import os

from celery import Celery, Task
from flask import Flask

from .main import main as main_blueprint
from aidrin.structured_data_metrics.completeness import calculate_completeness  # noqa: F401
from aidrin.structured_data_metrics.class_imbalance import calculate_class_distribution  # noqa: F401
from aidrin.structured_data_metrics.correlation_score import calculate_correlations  # noqa: F401
from aidrin.structured_data_metrics.duplicity import calculate_duplicates  # noqa: F401
from aidrin.structured_data_metrics.feature_relevance import calculate_feature_relevance  # noqa: F401
from aidrin.structured_data_metrics.outliers import calculate_outliers  # noqa: F401
from aidrin.structured_data_metrics.statistical_rate import calculate_statistical_rates  # noqa: F401
from aidrin.structured_data_metrics.privacy_measure import compute_k_anonymity, compute_l_diversity, \
        compute_t_closeness, compute_entropy_risk  # noqa: F401


# create app config
def create_app():
    app = Flask(__name__)
    app.secret_key = "aidrin"
    # Celery Config
    app.config["CELERY"] = {
        "broker_url": "redis://localhost:6379/0",  #
        "result_backend": "redis://localhost:6379/0",
        "task_ignore_result": True,  # Do not store task results in backend, unless methods call for it
        "task_soft_time_limit": 6,  # Task is soft killed
        "task_time_limit": 10,  # Task is force killed after this time
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
    # clear uploads folder on app start
    for filename in os.listdir(UPLOAD_FOLDER):
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}: {e}")

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
