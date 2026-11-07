"""Registro das rotas (blueprints) da aplicação."""
from flask import Flask

from app.routes.api_routes import api_bp
from app.routes.dashboard_routes import dashboard_bp
from app.routes.producao_routes import producao_bp


def registrar_rotas(app: Flask) -> None:
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(producao_bp)
    app.register_blueprint(api_bp)
