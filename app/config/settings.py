"""Configurações da aplicação, separadas por ambiente.

Todos os valores sensíveis ou dependentes do ambiente são lidos de variáveis
de ambiente (carregadas do arquivo ``.env`` via python-dotenv). Nenhum segredo
deve ser escrito diretamente neste arquivo.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Raiz do projeto (pasta que contém run.py)
BASE_DIR = Path(__file__).resolve().parents[2]

load_dotenv(BASE_DIR / ".env")


def _bool(valor: str | None, padrao: bool = False) -> bool:
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, padrao))
    except (TypeError, ValueError):
        return padrao


def _float(nome: str, padrao: float) -> float:
    try:
        return float(os.getenv(nome, padrao))
    except (TypeError, ValueError):
        return padrao


def _caminho(nome: str, padrao: Path) -> str:
    valor = os.getenv(nome)
    if not valor:
        return str(padrao)
    caminho = Path(valor)
    if not caminho.is_absolute():
        caminho = BASE_DIR / caminho
    return str(caminho)


class Config:
    """Configuração base, compartilhada por todos os ambientes."""

    APP_NOME = "LSPA Analytics"
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    DEBUG = False
    TESTING = False

    # Banco de dados (SQLite inicialmente; ver database/connection.py)
    DATABASE_PATH = _caminho("DATABASE_PATH", BASE_DIR / "database" / "lspa.db")

    # Integração SIDRA — as URLs base são fixas e NUNCA vêm do usuário.
    SIDRA_API_URL = "https://apisidra.ibge.gov.br"
    SIDRA_METADADOS_URL = "https://servicodados.ibge.gov.br/api/v3/agregados"
    SIDRA_TIMEOUT = _float("SIDRA_TIMEOUT", 30.0)
    SIDRA_TENTATIVAS = _int("SIDRA_TENTATIVAS", 2)

    # Cache (em horas): após esse prazo os dados são consultados novamente
    # no IBGE, permitindo capturar revisões das estimativas.
    CACHE_TTL_HORAS = _float("CACHE_TTL_HORAS", 6)
    METADADOS_TTL_HORAS = _float("METADADOS_TTL_HORAS", 24)

    # Logs
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE = _caminho("LOG_FILE", BASE_DIR / "logs" / "lspa.log")

    # Interface
    ITENS_POR_PAGINA_PADRAO = 25
    ITENS_POR_PAGINA_MAXIMO = 200

    HOST = os.getenv("FLASK_RUN_HOST", "127.0.0.1")
    PORT = _int("FLASK_RUN_PORT", 5000)


class DevelopmentConfig(Config):
    DEBUG = _bool(os.getenv("FLASK_DEBUG"), True)
    SECRET_KEY = Config.SECRET_KEY or "dev-somente-local"


class ProductionConfig(Config):
    DEBUG = False
    LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING").upper()


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "testes"
    DATABASE_PATH = ":memory:"
    LOG_FILE = ""
    SIDRA_TENTATIVAS = 0


CONFIGURACOES = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def obter_configuracao(nome: str | None = None) -> type[Config]:
    """Retorna a classe de configuração do ambiente informado (ou de APP_ENV)."""
    nome = (nome or os.getenv("APP_ENV", "development")).strip().lower()
    if nome not in CONFIGURACOES:
        raise ValueError(
            f"Ambiente '{nome}' inválido. Use: {', '.join(CONFIGURACOES)}."
        )
    return CONFIGURACOES[nome]
