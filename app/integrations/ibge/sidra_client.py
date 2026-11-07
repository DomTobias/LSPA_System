"""Cliente HTTP da API SIDRA/IBGE.

Centraliza todas as requisições externas da aplicação:

* reutiliza conexões com :class:`requests.Session` (keep-alive);
* aplica timeout em todas as chamadas;
* faz novas tentativas com *backoff* em falhas transitórias (429/5xx);
* converte falhas de rede/HTTP/JSON em exceções de domínio;
* registra logs de cada requisição (URL, status, duração, tamanho);
* só acessa hosts oficiais do IBGE (as URLs nunca vêm do usuário).
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.exceptions import (
    SidraConsultaInvalidaError,
    SidraError,
    SidraIndisponivelError,
    SidraRespostaInvalidaError,
)
from app.integrations.ibge import sidra_endpoints as endpoints
from app.integrations.ibge.sidra_endpoints import ConsultaValores

logger = logging.getLogger(__name__)

URL_VALORES_PADRAO = "https://apisidra.ibge.gov.br"
URL_METADADOS_PADRAO = "https://servicodados.ibge.gov.br/api/v3/agregados"


class SidraClient:
    """Cliente de baixo nível para a API SIDRA."""

    def __init__(
        self,
        url_valores: str = URL_VALORES_PADRAO,
        url_metadados: str = URL_METADADOS_PADRAO,
        timeout: float = 30.0,
        tentativas: int = 2,
        session: requests.Session | None = None,
    ):
        self.url_valores = self._validar_base(url_valores)
        self.url_metadados = self._validar_base(url_metadados)
        self.timeout = timeout
        self.session = session or self._criar_sessao(tentativas)

    # ------------------------------------------------------------------
    # Configuração
    # ------------------------------------------------------------------
    @staticmethod
    def _validar_base(url: str) -> str:
        partes = urlsplit(url)
        if partes.scheme != "https" or partes.hostname not in endpoints.HOSTS_PERMITIDOS:
            raise ValueError(f"URL base não permitida para o SIDRA: {url!r}")
        return url.rstrip("/")

    @staticmethod
    def _criar_sessao(tentativas: int) -> requests.Session:
        sessao = requests.Session()
        retry = Retry(
            total=max(int(tentativas), 0),
            connect=max(int(tentativas), 0),
            read=max(int(tentativas), 0),
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adaptador = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        sessao.mount("https://", adaptador)
        sessao.headers.update(
            {"Accept": "application/json", "User-Agent": "LSPA-System/1.0 (+python-requests)"}
        )
        return sessao

    def fechar(self) -> None:
        self.session.close()

    # ------------------------------------------------------------------
    # Operações públicas
    # ------------------------------------------------------------------
    def consultar_valores(self, consulta: ConsultaValores) -> list:
        """Executa uma consulta ``/values`` e retorna o JSON bruto (lista)."""
        dados = self._get_json(self.url_valores + consulta.caminho())
        if not isinstance(dados, list):
            raise SidraRespostaInvalidaError("A consulta de valores não retornou uma lista.")
        return dados

    def consultar_metadados(self, tabela: int) -> dict:
        dados = self._get_json(self.url_metadados + endpoints.caminho_metadados(tabela))
        if not isinstance(dados, dict):
            raise SidraRespostaInvalidaError("Os metadados não retornaram um objeto JSON.")
        return dados

    def consultar_periodos(self, tabela: int) -> list:
        dados = self._get_json(self.url_metadados + endpoints.caminho_periodos(tabela))
        if not isinstance(dados, list):
            raise SidraRespostaInvalidaError("A lista de períodos não é uma lista JSON.")
        return dados

    def consultar_localidades(self, tabela: int, niveis=tuple(endpoints.NIVEIS_TERRITORIAIS)) -> list:
        dados = self._get_json(self.url_metadados + endpoints.caminho_localidades(tabela, tuple(niveis)))
        if not isinstance(dados, list):
            raise SidraRespostaInvalidaError("A lista de localidades não é uma lista JSON.")
        return dados

    # ------------------------------------------------------------------
    # Núcleo HTTP
    # ------------------------------------------------------------------
    def _get_json(self, url: str):
        host = urlsplit(url).hostname
        if host not in endpoints.HOSTS_PERMITIDOS:  # defesa em profundidade
            raise SidraError(f"Host não permitido: {host}")

        inicio = time.perf_counter()
        try:
            resposta = self.session.get(url, timeout=self.timeout)
        except requests.Timeout as exc:
            logger.error("Timeout (%.0fs) ao consultar SIDRA: %s", self.timeout, url)
            raise SidraIndisponivelError(
                "O SIDRA/IBGE demorou demais para responder. Tente novamente."
            ) from exc
        except requests.ConnectionError as exc:
            logger.error("Falha de conexão com o SIDRA: %s (%s)", url, exc)
            raise SidraIndisponivelError() from exc
        except requests.RequestException as exc:
            logger.error("Erro na requisição ao SIDRA: %s (%s)", url, exc)
            raise SidraError() from exc

        duracao = time.perf_counter() - inicio
        logger.info(
            "SIDRA GET %s -> %s (%.2fs, %d bytes)",
            url, resposta.status_code, duracao, len(resposta.content or b""),
        )

        if resposta.status_code == 400:
            mensagem = (resposta.text or "").strip()[:300]
            raise SidraConsultaInvalidaError(
                f"Consulta recusada pelo SIDRA: {mensagem}" if mensagem else None
            )
        if resposta.status_code == 404:
            raise SidraConsultaInvalidaError("Recurso não encontrado no SIDRA.")
        if resposta.status_code == 429 or resposta.status_code >= 500:
            raise SidraIndisponivelError()
        if resposta.status_code != 200:
            raise SidraError(f"Resposta HTTP inesperada do SIDRA: {resposta.status_code}.")

        try:
            return resposta.json()
        except ValueError as exc:
            logger.error("JSON inválido do SIDRA em %s: %r", url, resposta.text[:200])
            raise SidraRespostaInvalidaError() from exc
