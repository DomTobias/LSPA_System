"""Rotas da página de consulta de produção."""
from flask import Blueprint

from app.controllers import producao_controller

producao_bp = Blueprint("producao", __name__)

producao_bp.add_url_rule("/producao", "index", producao_controller.index, methods=["GET"])
