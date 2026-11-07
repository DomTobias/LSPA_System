"""Rotas das páginas do dashboard."""
from flask import Blueprint

from app.controllers import dashboard_controller

dashboard_bp = Blueprint("dashboard", __name__)

dashboard_bp.add_url_rule("/", "raiz", dashboard_controller.index, methods=["GET"])
dashboard_bp.add_url_rule("/dashboard", "index", dashboard_controller.index, methods=["GET"])
