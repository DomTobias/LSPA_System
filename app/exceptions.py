"""Exceções de domínio da aplicação.

Centralizar as exceções permite que o tratamento de erros (em app/__init__.py)
converta cada uma no código HTTP adequado, sem que controllers ou services
precisem conhecer detalhes de transporte.
"""
from __future__ import annotations


class LSPAError(Exception):
    """Erro base da aplicação."""

    status_http = 500
    mensagem_padrao = "Erro interno da aplicação."

    def __init__(self, mensagem: str | None = None, *, detalhes: dict | None = None):
        super().__init__(mensagem or self.mensagem_padrao)
        self.mensagem = mensagem or self.mensagem_padrao
        self.detalhes = detalhes or {}


class ParametroInvalidoError(LSPAError):
    """Parâmetro de filtro inválido informado pelo usuário."""

    status_http = 400
    mensagem_padrao = "Parâmetro inválido."


class RecursoNaoEncontradoError(LSPAError):
    status_http = 404
    mensagem_padrao = "Recurso não encontrado."


class SidraError(LSPAError):
    """Erro genérico de integração com o SIDRA/IBGE."""

    status_http = 502
    mensagem_padrao = "Falha na comunicação com o SIDRA/IBGE."


class SidraIndisponivelError(SidraError):
    """API do IBGE fora do ar, lenta (timeout) ou inacessível."""

    status_http = 503
    mensagem_padrao = (
        "A API SIDRA do IBGE está indisponível no momento. "
        "Tente novamente em alguns minutos."
    )


class SidraRespostaInvalidaError(SidraError):
    """A API respondeu, mas com um conteúdo que não pôde ser interpretado."""

    status_http = 502
    mensagem_padrao = "O SIDRA/IBGE retornou uma resposta inválida."


class SidraConsultaInvalidaError(SidraError):
    """A API recusou a consulta (HTTP 400), por exemplo código inexistente."""

    status_http = 400
    mensagem_padrao = "A consulta foi recusada pelo SIDRA/IBGE."
