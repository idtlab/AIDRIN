from web.routes.admin import admin_bp
from web.routes.core import core_bp
from web.routes.custom import custom_bp
from web.routes.metrics import metrics_bp


def register_blueprints(app):
    app.register_blueprint(admin_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(custom_bp)
    app.register_blueprint(metrics_bp)
