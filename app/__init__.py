from __future__ import annotations

from flask import Flask

from .config import Config
from .extensions import cors
from .routes.api import api_bp
from .routes.views import views_bp


def create_app(config_class: type[Config] = Config) -> Flask:
    """Application factory wiring blueprints and extensions."""
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config.from_object(config_class)
    _init_extensions(app)
    _register_blueprints(app)
    return app


def _init_extensions(app: Flask) -> None:
    """Attach Flask extensions to the instance."""
    cors.init_app(app, resources={r'/api/*': {'origins': '*'}})


def _register_blueprints(app: Flask) -> None:
    """Expose user-facing routes with clear prefixes."""
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
