"""Interpretação e normalização das respostas da API SIDRA.

Formatos tratados (verificados em requisições reais):

* ``/values`` (apisidra.ibge.gov.br): lista JSON cuja primeira linha é o
  cabeçalho (rótulos das colunas) e as demais são observações. As colunas
  ``D1C/D1N ... DnC/DnN`` têm a ordem definida pela consulta, por isso as
  dimensões são identificadas pelos rótulos do cabeçalho. Valores especiais
  ("-", "..", "...", "X") são preservados como símbolo.
* ``/metadados``, ``/periodos`` e ``/localidades`` (servicodados.ibge.gov.br).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from app.exceptions import SidraRespostaInvalidaError
from app.integrations.ibge.sidra_endpoints import (
    CLASSIFICACAO_PRODUTO,
    NIVEIS_TERRITORIAIS,
    VARIAVEIS_LSPA,
)
from app.models import Indicador, Localidade, Periodo, Producao, Produto
from app.models.producao_model import SIMBOLOS_SIDRA

logger = logging.getLogger(__name__)

_RE_HIERARQUIA = re.compile(r"^\s*([\d]+(?:[./]\d+)*)\s+(.+)$")


# --------------------------------------------------------------------------
# Valores
# --------------------------------------------------------------------------
def interpretar_valor(texto) -> tuple[float | None, str | None]:
    """Converte o campo ``V`` em (valor numérico, símbolo)."""
    if texto is None:
        return None, "..."
    bruto = str(texto).strip()
    if bruto in SIMBOLOS_SIDRA:
        return None, bruto
    try:
        return float(bruto), None
    except ValueError:
        logger.warning("Valor não numérico desconhecido no SIDRA: %r", bruto)
        return None, bruto


def _mapear_dimensoes(cabecalho: dict) -> dict[str, str]:
    """Identifica qual coluna Dn corresponde a cada dimensão da consulta."""
    mapa: dict[str, str] = {}
    for chave, rotulo in cabecalho.items():
        if not (chave.startswith("D") and chave.endswith("C")):
            continue
        prefixo = chave[:-1]  # "D1"
        rotulo = str(rotulo)
        if rotulo.startswith("Variável"):
            mapa["variavel"] = prefixo
        elif rotulo.startswith(("Mês", "Ano", "Trimestre")):
            mapa["periodo"] = prefixo
        elif rotulo.startswith("Produto"):
            mapa["produto"] = prefixo
        else:
            mapa.setdefault("localidade", prefixo)
    return mapa


_MAPA_PADRAO = {"localidade": "D1", "variavel": "D2", "periodo": "D3", "produto": "D4"}


def interpretar_valores(dados, tabela: int) -> list[Producao]:
    """Converte a resposta ``/values`` em uma lista de :class:`Producao`."""
    if not isinstance(dados, list):
        raise SidraRespostaInvalidaError("Resposta de valores não é uma lista JSON.")
    if not dados:
        return []

    primeira = dados[0]
    if not isinstance(primeira, dict):
        raise SidraRespostaInvalidaError("Formato de linha inesperado na resposta do SIDRA.")

    if primeira.get("V") == "Valor":  # linha de cabeçalho
        mapa = _mapear_dimensoes(primeira)
        linhas = dados[1:]
    else:
        mapa = dict(_MAPA_PADRAO)
        linhas = dados

    faltando = {"localidade", "variavel", "periodo", "produto"} - mapa.keys()
    if faltando:
        raise SidraRespostaInvalidaError(
            f"Dimensões ausentes na resposta do SIDRA: {', '.join(sorted(faltando))}."
        )

    observacoes: list[Producao] = []
    for linha in linhas:
        try:
            nivel = f"N{linha['NC']}"
            if nivel not in NIVEIS_TERRITORIAIS:
                continue
            valor, simbolo = interpretar_valor(linha.get("V"))
            loc, var, per, prod = (mapa[k] for k in ("localidade", "variavel", "periodo", "produto"))
            observacoes.append(
                Producao(
                    tabela=int(tabela),
                    periodo=str(linha[f"{per}C"]),
                    nivel=nivel,
                    localidade_codigo=str(linha[f"{loc}C"]),
                    localidade_nome=linha.get(f"{loc}N", ""),
                    produto_codigo=str(linha[f"{prod}C"]),
                    produto_nome=limpar_nome_produto(linha.get(f"{prod}N", ""))[1],
                    variavel_codigo=int(linha[f"{var}C"]),
                    variavel_nome=linha.get(f"{var}N", ""),
                    unidade=linha.get("MN", ""),
                    valor=valor,
                    simbolo=simbolo,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SidraRespostaInvalidaError(
                f"Linha inválida na resposta do SIDRA: {exc}"
            ) from exc
    return observacoes


# --------------------------------------------------------------------------
# Metadados
# --------------------------------------------------------------------------
def limpar_nome_produto(nome: str) -> tuple[str, str]:
    """Separa a numeração hierárquica do nome: "1.17 Soja" → ("1.17", "Soja")."""
    correspondencia = _RE_HIERARQUIA.match(nome or "")
    if correspondencia:
        return correspondencia.group(1), correspondencia.group(2).strip()
    return "", (nome or "").strip()


def interpretar_indicadores(metadados: dict) -> list[Indicador]:
    if not isinstance(metadados, dict) or "variaveis" not in metadados:
        raise SidraRespostaInvalidaError("Metadados sem a lista de variáveis.")
    indicadores = []
    for variavel in metadados["variaveis"]:
        codigo = int(variavel["id"])
        if codigo not in VARIAVEIS_LSPA:
            continue
        indicadores.append(
            Indicador(
                codigo=codigo,
                chave=VARIAVEIS_LSPA[codigo],
                nome=variavel.get("nome", ""),
                unidade=variavel.get("unidade", ""),
                somavel="nivelTerritorial" in (variavel.get("sumarizacao") or []),
            )
        )
    return indicadores


def interpretar_produtos(metadados: dict) -> list[Produto]:
    """Extrai as categorias da classificação 48 e calcula a hierarquia."""
    if not isinstance(metadados, dict):
        raise SidraRespostaInvalidaError("Metadados em formato inesperado.")
    classificacao = next(
        (c for c in metadados.get("classificacoes", []) if int(c.get("id", -1)) == CLASSIFICACAO_PRODUTO),
        None,
    )
    if classificacao is None:
        raise SidraRespostaInvalidaError("Classificação de produtos não encontrada nos metadados.")

    categorias = classificacao.get("categorias") or []
    produtos: list[Produto] = []
    pilha: list[Produto] = []  # ancestrais por nível
    for indice, categoria in enumerate(categorias):
        nivel = int(categoria.get("nivel", 1))
        hierarquia, nome = limpar_nome_produto(categoria.get("nome", ""))
        while pilha and pilha[-1].nivel >= nivel:
            pilha.pop()
        proximo_nivel = int(categorias[indice + 1].get("nivel", 1)) if indice + 1 < len(categorias) else -1
        produto = Produto(
            codigo=str(categoria["id"]),
            nome=nome,
            nome_original=categoria.get("nome", ""),
            hierarquia=hierarquia,
            nivel=nivel,
            agregado=nivel == 0 or proximo_nivel > nivel,
            pai_codigo=pilha[-1].codigo if pilha else None,
        )
        produtos.append(produto)
        pilha.append(produto)
    return produtos


def interpretar_periodos(dados) -> list[Periodo]:
    if not isinstance(dados, list):
        raise SidraRespostaInvalidaError("Lista de períodos inválida.")
    periodos = []
    for item in dados:
        try:
            codigo = str(item["id"])
            literais = item.get("literals") or []
            periodos.append(
                Periodo(
                    codigo=codigo,
                    nome=literais[0] if literais else "",
                    modificacao=_data_iso(item.get("modificacao")),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise SidraRespostaInvalidaError(f"Período inválido: {item!r}") from exc
    return sorted(periodos, key=lambda p: p.codigo)


def interpretar_localidades(dados) -> list[Localidade]:
    if not isinstance(dados, list):
        raise SidraRespostaInvalidaError("Lista de localidades inválida.")
    localidades = []
    for item in dados:
        try:
            nivel = item["nivel"]["id"]
            if nivel not in NIVEIS_TERRITORIAIS:
                continue
            localidades.append(
                Localidade(
                    codigo=str(item["id"]),
                    nome=item["nome"],
                    nivel=nivel,
                    nivel_nome=item["nivel"].get("nome", NIVEIS_TERRITORIAIS[nivel]),
                )
            )
        except (KeyError, TypeError) as exc:
            raise SidraRespostaInvalidaError(f"Localidade inválida: {item!r}") from exc
    return localidades


def _data_iso(texto: str | None) -> str | None:
    if not texto:
        return None
    try:
        return datetime.strptime(texto, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None
