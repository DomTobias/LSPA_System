"""Serviço de acesso aos dados do SIDRA com cache persistente.

Regras de cache:

1. Toda consulta tem um caminho canônico (ver ``ConsultaValores.caminho``),
   registrado na tabela ``consultas`` com a data da última execução.
2. Se a última execução bem-sucedida está dentro do prazo (TTL), os dados
   são lidos do banco local — nenhuma chamada é feita ao IBGE.
3. Vencido o prazo, a consulta é refeita no IBGE e os registros são
   atualizados (upsert), capturando eventuais revisões das estimativas.
4. Se o IBGE estiver indisponível e houver dados locais (mesmo vencidos),
   eles são devolvidos com um aviso; sem dados locais, o erro é propagado.
5. Requisições simultâneas para a mesma consulta aguardam a primeira, para
   não repetir chamadas à API.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.exceptions import ParametroInvalidoError, SidraError
from app.integrations.ibge import sidra_parser as parser
from app.integrations.ibge.sidra_client import SidraClient
from app.integrations.ibge.sidra_endpoints import (
    LIMITE_VALORES_POR_CONSULTA,
    NIVEIS_TERRITORIAIS,
    TABELA_LSPA_SERIE_HISTORICA,
    ConsultaValores,
    caminho_localidades,
    caminho_metadados,
    caminho_periodos,
)
from app.models import Indicador, Localidade, Periodo, Producao, Produto
from app.repositories.producao_repository import ProducaoRepository

logger = logging.getLogger(__name__)

ORIGEM_API = "api"
ORIGEM_CACHE = "cache"
ORIGEM_CACHE_EXPIRADO = "cache_expirado"

AVISO_DADOS_LOCAIS = (
    "O SIDRA/IBGE está indisponível. Exibindo os últimos dados armazenados localmente, "
    "que podem estar desatualizados."
)


@dataclass
class ResultadoConsulta:
    observacoes: list[Producao]
    origem: str
    atualizado_em: str | None
    caminho: str
    avisos: list[str] = field(default_factory=list)


class SidraService:
    def __init__(
        self,
        cliente: SidraClient,
        repositorio: ProducaoRepository,
        tabela: int = TABELA_LSPA_SERIE_HISTORICA,
        cache_ttl_horas: float = 6,
        metadados_ttl_horas: float = 24,
        relogio: Callable[[], datetime] | None = None,
    ):
        self.cliente = cliente
        self.repositorio = repositorio
        self.tabela = tabela
        self.cache_ttl = timedelta(hours=cache_ttl_horas)
        self.metadados_ttl = timedelta(hours=metadados_ttl_horas)
        self._agora = relogio or (lambda: datetime.now(timezone.utc))
        self._locks: dict[str, threading.Lock] = {}
        self._lock_global = threading.Lock()
        self.avisos_metadados: list[str] = []

    # ------------------------------------------------------------------
    # Auxiliares de cache
    # ------------------------------------------------------------------
    def _lock_para(self, chave: str) -> threading.Lock:
        with self._lock_global:
            return self._locks.setdefault(chave, threading.Lock())

    def _cache_valido(self, registro: dict | None, ttl: timedelta) -> bool:
        if not registro or not registro.get("executada_em"):
            return False
        try:
            executada = datetime.fromisoformat(registro["executada_em"])
        except ValueError:
            return False
        if executada.tzinfo is None:
            executada = executada.replace(tzinfo=timezone.utc)
        return self._agora() - executada < ttl

    def _carregar_metadado(self, tipo: str, caminho: str, buscar_remoto, salvar, ler_local):
        """Fluxo de cache genérico para metadados."""
        with self._lock_para(caminho):
            registro = self.repositorio.obter_consulta(caminho)
            if self._cache_valido(registro, self.metadados_ttl):
                local = ler_local()
                if local:
                    return local
            try:
                dados = buscar_remoto()
            except SidraError as exc:
                self.repositorio.registrar_consulta(
                    tipo, self.tabela, caminho, sucesso=False, mensagem=exc.mensagem
                )
                local = ler_local()
                if local:
                    logger.warning("Usando %s locais (IBGE indisponível): %s", tipo, exc.mensagem)
                    if AVISO_DADOS_LOCAIS not in self.avisos_metadados:
                        self.avisos_metadados.append(AVISO_DADOS_LOCAIS)
                    return local
                raise
            salvar(dados)
            self.repositorio.registrar_consulta(
                tipo, self.tabela, caminho, registros=len(dados) if hasattr(dados, "__len__") else 0
            )
            self.avisos_metadados.clear()
            return ler_local()

    # ------------------------------------------------------------------
    # Metadados
    # ------------------------------------------------------------------
    def _metadados_remotos(self):
        bruto = self.cliente.consultar_metadados(self.tabela)
        return parser.interpretar_produtos(bruto), parser.interpretar_indicadores(bruto)

    def _salvar_metadados(self, dados):
        produtos, indicadores = dados
        self.repositorio.salvar_produtos(self.tabela, produtos)
        self.repositorio.salvar_indicadores(self.tabela, indicadores)

    def obter_produtos(self) -> list[Produto]:
        return self._carregar_metadado(
            "metadados", caminho_metadados(self.tabela),
            self._metadados_remotos, self._salvar_metadados,
            lambda: self.repositorio.listar_produtos(self.tabela),
        )

    def obter_indicadores(self) -> list[Indicador]:
        return self._carregar_metadado(
            "metadados", caminho_metadados(self.tabela),
            self._metadados_remotos, self._salvar_metadados,
            lambda: self.repositorio.listar_indicadores(self.tabela),
        )

    def obter_periodos(self) -> list[Periodo]:
        return self._carregar_metadado(
            "periodos", caminho_periodos(self.tabela),
            lambda: parser.interpretar_periodos(self.cliente.consultar_periodos(self.tabela)),
            lambda periodos: self.repositorio.salvar_periodos(self.tabela, periodos),
            lambda: self.repositorio.listar_periodos(self.tabela),
        )

    def obter_localidades(self) -> list[Localidade]:
        return self._carregar_metadado(
            "localidades", caminho_localidades(self.tabela),
            lambda: parser.interpretar_localidades(self.cliente.consultar_localidades(self.tabela)),
            self.repositorio.salvar_localidades,
            self.repositorio.listar_localidades,
        )

    # ------------------------------------------------------------------
    # Valores
    # ------------------------------------------------------------------
    def _verificar_tamanho(self, consulta: ConsultaValores) -> None:
        localidades = self.repositorio.listar_localidades()
        por_nivel = {n: sum(1 for l in localidades if l.nivel == n) or 30 for n in NIVEIS_TERRITORIAIS}
        total_produtos = len(self.repositorio.listar_produtos(self.tabela)) or 50
        estimativa = consulta.estimar_valores(por_nivel, total_produtos)
        if estimativa > LIMITE_VALORES_POR_CONSULTA:
            formatar = lambda n: f"{n:,}".replace(",", ".")
            raise ParametroInvalidoError(
                f"A consulta retornaria cerca de {formatar(estimativa)} valores (limite: "
                f"{formatar(LIMITE_VALORES_POR_CONSULTA)}). Refine os filtros: selecione um produto, "
                "um indicador ou um mês específico."
            )

    def obter_observacoes(self, consulta: ConsultaValores) -> ResultadoConsulta:
        caminho = consulta.caminho()
        territorios = [(t.nivel, t.localidades) for t in consulta.territorios]

        def ler_local() -> list[Producao]:
            return self.repositorio.buscar_producao(
                consulta.tabela, territorios, consulta.variaveis, consulta.periodos, consulta.produtos
            )

        with self._lock_para(caminho):
            registro = self.repositorio.obter_consulta(caminho)
            if self._cache_valido(registro, self.cache_ttl):
                logger.debug("Cache válido para %s", caminho)
                return ResultadoConsulta(ler_local(), ORIGEM_CACHE, registro["executada_em"], caminho)

            self._verificar_tamanho(consulta)
            try:
                observacoes = parser.interpretar_valores(
                    self.cliente.consultar_valores(consulta), consulta.tabela
                )
            except SidraError as exc:
                self.repositorio.registrar_consulta(
                    "valores", consulta.tabela, caminho, self._parametros(consulta),
                    sucesso=False, mensagem=exc.mensagem,
                )
                if registro and registro.get("executada_em"):
                    logger.warning("IBGE indisponível; usando cache vencido de %s", caminho)
                    return ResultadoConsulta(
                        ler_local(), ORIGEM_CACHE_EXPIRADO, registro["executada_em"], caminho,
                        [AVISO_DADOS_LOCAIS],
                    )
                raise

            consulta_id = self.repositorio.registrar_consulta(
                "valores", consulta.tabela, caminho, self._parametros(consulta),
                registros=len(observacoes),
            )
            self.repositorio.salvar_producao(observacoes, consulta_id)
            atualizado = self.repositorio.obter_consulta(caminho)["executada_em"]
            for observacao in observacoes:
                observacao.atualizado_em = atualizado
            return ResultadoConsulta(observacoes, ORIGEM_API, atualizado, caminho)

    @staticmethod
    def _parametros(consulta: ConsultaValores) -> dict:
        return {
            "territorios": {t.nivel: list(t.localidades) or "all" for t in consulta.territorios},
            "variaveis": list(consulta.variaveis),
            "periodos": list(consulta.periodos),
            "produtos": list(consulta.produtos) or "all",
        }

    def status(self) -> dict:
        return self.repositorio.estatisticas()
