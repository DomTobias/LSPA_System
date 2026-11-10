"""Processo Worker — nó de processamento do LSPA-System.

Enquanto o nó Manager (ver ``run.py`` / serviço ``manager`` no Docker Swarm)
apenas coordena requisições HTTP e serve dados já em cache, este processo
roda nos nós Worker do cluster e faz o trabalho pesado: consulta a API SIDRA
do IBGE, interpreta as respostas e grava/atualiza o banco local (ETL),
mantendo o cache sempre pronto para o Manager responder sem latência.

Uso:
    python worker.py

Variáveis de ambiente relevantes (ver .env.example):
    WORKER_INTERVALO_SEGUNDOS  Intervalo entre ciclos de processamento (padrão: 1800)
"""
from __future__ import annotations

import logging
import os
import socket
import time

from app.config.settings import obter_configuracao
from app.exceptions import LSPAError
from app.integrations.ibge.sidra_client import SidraClient
from app.repositories.producao_repository import ProducaoRepository
from app.services.dashboard_service import DashboardService
from app.services.producao_service import ProducaoService
from app.services.sidra_service import SidraService
from database.connection import Database

logger = logging.getLogger(__name__)

INTERVALO_PADRAO_SEGUNDOS = 1800


def _configurar_logs(nivel: str) -> None:
    logging.basicConfig(
        level=getattr(logging, (nivel or "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def montar_servicos() -> tuple[SidraService, ProducaoService, DashboardService]:
    config = obter_configuracao()
    banco = Database(config.DATABASE_PATH)
    banco.inicializar()
    repositorio = ProducaoRepository(banco)
    cliente = SidraClient(
        url_valores=config.SIDRA_API_URL,
        url_metadados=config.SIDRA_METADADOS_URL,
        timeout=config.SIDRA_TIMEOUT,
        tentativas=config.SIDRA_TENTATIVAS,
    )
    sidra = SidraService(
        cliente, repositorio,
        cache_ttl_horas=config.CACHE_TTL_HORAS,
        metadados_ttl_horas=config.METADADOS_TTL_HORAS,
    )
    producao = ProducaoService(
        sidra,
        itens_por_pagina=config.ITENS_POR_PAGINA_PADRAO,
        maximo_por_pagina=config.ITENS_POR_PAGINA_MAXIMO,
    )
    dashboard = DashboardService(sidra, producao, produto_padrao=os.getenv("DASHBOARD_PRODUTO_PADRAO") or None)
    return sidra, producao, dashboard


def processar_ciclo(sidra: SidraService, producao: ProducaoService, dashboard: DashboardService) -> None:
    """Um ciclo de processamento: atualiza metadados e pré-aquece o dashboard padrão."""
    sidra.obter_produtos()
    sidra.obter_indicadores()
    sidra.obter_periodos()
    sidra.obter_localidades()

    produto_padrao = dashboard.produto_inicial(producao.listar_produtos())
    dashboard.obter_dashboard({"produto": produto_padrao.codigo})
    logger.info("Ciclo concluído (produto padrão: %s)", produto_padrao.nome)


def main() -> None:
    config = obter_configuracao()
    _configurar_logs(config.LOG_LEVEL)
    intervalo = int(os.getenv("WORKER_INTERVALO_SEGUNDOS", INTERVALO_PADRAO_SEGUNDOS))
    host = socket.gethostname()
    sidra, producao, dashboard = montar_servicos()

    logger.info("Worker de processamento iniciado (host=%s, intervalo=%ss)", host, intervalo)
    while True:
        try:
            logger.info("Worker %s: iniciando ciclo de processamento", host)
            processar_ciclo(sidra, producao, dashboard)
        except LSPAError as exc:
            logger.warning("Worker %s: falha no ciclo (%s)", host, exc.mensagem)
        except Exception:
            logger.exception("Worker %s: erro inesperado no ciclo de processamento", host)
        time.sleep(intervalo)


if __name__ == "__main__":
    main()
