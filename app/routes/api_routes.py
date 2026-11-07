"""Rotas da API interna."""
from flask import Blueprint

from app.controllers import api_controller

api_bp = Blueprint("api", __name__, url_prefix="/api")

_ROTAS = {
    "/producao": api_controller.producao,
    "/produtos": api_controller.produtos,
    "/localidades": api_controller.localidades,
    "/periodos": api_controller.periodos,
    "/indicadores": api_controller.indicadores,
    "/dashboard": api_controller.dashboard,
    "/status": api_controller.status,
}

for _caminho, _funcao in _ROTAS.items():
    api_bp.add_url_rule(_caminho, _funcao.__name__, _funcao, methods=["GET"])
