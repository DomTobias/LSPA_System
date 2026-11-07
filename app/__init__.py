"""Fábrica da aplicação Flask (padrão *application factory*).

Aqui são feitas a composição das camadas (cliente SIDRA → repositório →
services), a configuração de logs, o tratamento centralizado de exceções e
os cabeçalhos de segurança.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from app.config.settings import BASE_DIR, Config, obter_configuracao
from app.exceptions import LSPAError
from app.integrations.ibge.sidra_client import SidraClient
from app.repositories.producao_repository import ProducaoRepository
from app.routes import registrar_rotas
from app.services.dashboard_service import DashboardService
from app.services.producao_service import ProducaoService
from app.services.sidra_service import SidraService
from database.connection import Database

logger = logging.getLogger(__name__)

VIEWS_DIR = Path(__file__).resolve().parent / "views"

CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@dataclass
class Servicos:
    """Contêiner simples de dependências, acessível em ``app.extensions``."""

    banco: Database
    repositorio: ProducaoRepository
    cliente: SidraClient
    sidra: SidraService
    producao: ProducaoService
    dashboard: DashboardService


def create_app(configuracao: str | type[Config] | None = None, cliente_sidra: SidraClient | None = None) -> Flask:
    """Cria e configura a aplicação.

    Args:
        configuracao: nome do ambiente ("development", "production",
            "testing") ou uma classe de configuração.
        cliente_sidra: cliente alternativo (usado nos testes com mocks).
    """
    classe = configuracao if isinstance(configuracao, type) else obter_configuracao(configuracao)

    app = Flask(
        __name__,
        template_folder=str(VIEWS_DIR / "templates"),
        static_folder=str(VIEWS_DIR / "static"),
    )
    app.config.from_object(classe)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY não configurada. Defina-a no arquivo .env.")
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    _configurar_logs(app)

    banco = Database(app.config["DATABASE_PATH"])
    banco.inicializar()
    repositorio = ProducaoRepository(banco)
    cliente = cliente_sidra or SidraClient(
        url_valores=app.config["SIDRA_API_URL"],
        url_metadados=app.config["SIDRA_METADADOS_URL"],
        timeout=app.config["SIDRA_TIMEOUT"],
        tentativas=app.config["SIDRA_TENTATIVAS"],
    )
    sidra = SidraService(
        cliente,
        repositorio,
        cache_ttl_horas=app.config["CACHE_TTL_HORAS"],
        metadados_ttl_horas=app.config["METADADOS_TTL_HORAS"],
    )
    producao = ProducaoService(
        sidra,
        itens_por_pagina=app.config["ITENS_POR_PAGINA_PADRAO"],
        maximo_por_pagina=app.config["ITENS_POR_PAGINA_MAXIMO"],
    )
    dashboard = DashboardService(sidra, producao, produto_padrao=os.getenv("DASHBOARD_PRODUTO_PADRAO") or None)
    app.extensions["lspa"] = Servicos(banco, repositorio, cliente, sidra, producao, dashboard)

    registrar_rotas(app)
    _registrar_tratamento_erros(app)
    _registrar_contexto_templates(app)
    _registrar_cabecalhos_seguranca(app)

    logger.info("Aplicação iniciada (ambiente: %s)", classe.__name__)
    return app


# --------------------------------------------------------------------------
def _configurar_logs(app: Flask) -> None:
    nivel = getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO)
    formato = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(nivel)

    if not any(getattr(h, "_lspa", False) for h in raiz.handlers):
        console = logging.StreamHandler()
        console.setFormatter(formato)
        console._lspa = True
        raiz.addHandler(console)

        arquivo_log = app.config.get("LOG_FILE")
        if arquivo_log:
            Path(arquivo_log).parent.mkdir(parents=True, exist_ok=True)
            arquivo = RotatingFileHandler(arquivo_log, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
            arquivo.setFormatter(formato)
            arquivo._lspa = True
            raiz.addHandler(arquivo)

    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _quer_json() -> bool:
    return request.path.startswith("/api/")


def _registrar_tratamento_erros(app: Flask) -> None:
    def responder(status: int, titulo: str, mensagem: str, detalhes: dict | None = None):
        if _quer_json():
            corpo = {"erro": titulo, "mensagem": mensagem, "status": status}
            if detalhes:
                corpo["detalhes"] = detalhes
            return jsonify(corpo), status
        return render_template("errors/erro.html", status=status, titulo=titulo, mensagem=mensagem), status

    @app.errorhandler(LSPAError)
    def erro_aplicacao(erro: LSPAError):
        nivel = logging.WARNING if erro.status_http < 500 else logging.ERROR
        logger.log(nivel, "%s em %s: %s", type(erro).__name__, request.path, erro.mensagem)
        return responder(erro.status_http, type(erro).__name__, erro.mensagem, erro.detalhes)

    @app.errorhandler(HTTPException)
    def erro_http(erro: HTTPException):
        mensagens = {
            404: "A página ou recurso solicitado não foi encontrado.",
            405: "Método HTTP não permitido para este recurso.",
        }
        return responder(erro.code or 500, erro.name, mensagens.get(erro.code, erro.description or ""))

    @app.errorhandler(Exception)
    def erro_inesperado(erro: Exception):
        logger.exception("Erro inesperado em %s", request.path)
        return responder(500, "Erro interno", "Ocorreu um erro inesperado. Consulte os logs da aplicação.")


def _registrar_contexto_templates(app: Flask) -> None:
    @app.context_processor
    def contexto():
        return {"app_nome": app.config["APP_NOME"]}

    @app.template_filter("numero")
    def formatar_numero(valor, casas: int = 0):
        if valor is None:
            return "—"
        texto = f"{valor:,.{casas}f}"
        return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _registrar_cabecalhos_seguranca(app: Flask) -> None:
    @app.after_request
    def cabecalhos(resposta):
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "DENY")
        resposta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resposta.headers.setdefault("Content-Security-Policy", CSP)
        if request.path.startswith("/api/"):
            resposta.headers.setdefault("Cache-Control", "no-store")
        return resposta
