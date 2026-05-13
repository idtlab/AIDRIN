from web.routes.admin import admin_bp
from web.routes.core import core_bp
from web.routes.custom import custom_bp
from web.routes.metrics import metrics_bp


def register_blueprints(app):
    app.register_blueprint(admin_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(custom_bp)
    app.register_blueprint(metrics_bp)

    # Globus Compute — optional, only if SDK is installed
    from web.globus import is_globus_available
    if is_globus_available():
        from web.routes.globus import globus_bp
        app.register_blueprint(globus_bp)

    # LLM explanations — optional, only if openai is installed
    from web.llm import is_llm_available
    if is_llm_available():
        from web.routes.llm import llm_bp
        app.register_blueprint(llm_bp)
