"""Endpoints e parâmetros oficiais da API SIDRA para o LSPA.

Códigos verificados em requisições reais aos metadados do IBGE
(``https://servicodados.ibge.gov.br/api/v3/agregados/6588/metadados``):

* Pesquisa ``LA`` — Levantamento Sistemático da Produção Agrícola.
* Tabela 6588 — "Série histórica da estimativa anual da área plantada, área
  colhida, produção e rendimento médio dos produtos das lavouras".
  Periodicidade mensal (código AAAAMM = mês de referência da estimativa
  anual do ano AAAA). Níveis territoriais N1, N2 e N3.
* Variáveis: 109 Área plantada (ha), 216 Área colhida (ha),
  35 Produção (t), 36 Rendimento médio (kg/ha).
* Classificação 48 — Produto das lavouras (categorias obtidas dinamicamente
  dos metadados; nada é fixado aqui).

Este módulo apenas descreve e valida consultas: ele não faz requisições.
Todo caminho gerado é composto exclusivamente de tokens validados, o que
impede que entradas do usuário alterem o destino das requisições.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --- Tabelas do LSPA ------------------------------------------------------
TABELA_LSPA_SERIE_HISTORICA = 6588
TABELA_LSPA_PROGNOSTICO = 7878  # prognóstico da safra seguinte (referência)
TABELAS_LSPA_SUPORTADAS = frozenset({TABELA_LSPA_SERIE_HISTORICA, TABELA_LSPA_PROGNOSTICO})

# --- Variáveis da tabela 6588 ----------------------------------------------
VARIAVEL_AREA_PLANTADA = 109
VARIAVEL_AREA_COLHIDA = 216
VARIAVEL_PRODUCAO = 35
VARIAVEL_RENDIMENTO_MEDIO = 36

VARIAVEIS_LSPA = {
    VARIAVEL_PRODUCAO: "producao",
    VARIAVEL_AREA_PLANTADA: "area_plantada",
    VARIAVEL_AREA_COLHIDA: "area_colhida",
    VARIAVEL_RENDIMENTO_MEDIO: "rendimento_medio",
}

# --- Classificação de produtos --------------------------------------------
CLASSIFICACAO_PRODUTO = 48
CATEGORIA_TOTAL = 0

# --- Níveis territoriais ---------------------------------------------------
NIVEL_BRASIL = "N1"
NIVEL_REGIAO = "N2"
NIVEL_UF = "N3"
NIVEIS_TERRITORIAIS = {
    NIVEL_BRASIL: "Brasil",
    NIVEL_REGIAO: "Grande Região",
    NIVEL_UF: "Unidade da Federação",
}

# Limite de segurança de valores por consulta (a API SIDRA recusa consultas
# muito grandes; mantemos uma margem bem abaixo do limite do serviço).
LIMITE_VALORES_POR_CONSULTA = 50_000

# Hosts permitidos (proteção contra requisições a URLs arbitrárias)
HOSTS_PERMITIDOS = frozenset({"apisidra.ibge.gov.br", "servicodados.ibge.gov.br"})

_RE_CODIGO = re.compile(r"^\d{1,7}$")
_RE_PERIODO = re.compile(r"^\d{4}(0[1-9]|1[0-2])$")


def _validar_codigos(valores, rotulo: str) -> tuple[str, ...]:
    resultado = []
    for valor in valores:
        texto = str(valor).strip()
        if not _RE_CODIGO.match(texto):
            raise ValueError(f"Código de {rotulo} inválido: {valor!r}")
        resultado.append(texto)
    # remove duplicados preservando a ordem
    return tuple(dict.fromkeys(resultado))


@dataclass(frozen=True)
class Territorio:
    """Um nível territorial e suas localidades (vazio = todas)."""

    nivel: str
    localidades: tuple[str, ...] = ()

    def __post_init__(self):
        if self.nivel not in NIVEIS_TERRITORIAIS:
            raise ValueError(f"Nível territorial inválido: {self.nivel!r}")
        object.__setattr__(self, "localidades", _validar_codigos(self.localidades, "localidade"))

    def segmento(self) -> str:
        codigos = ",".join(self.localidades) if self.localidades else "all"
        return f"{self.nivel.lower()}/{codigos}"


@dataclass(frozen=True)
class ConsultaValores:
    """Descrição imutável e validada de uma consulta ``/values`` ao SIDRA.

    ``produtos`` vazio significa todas as categorias da classificação 48.
    Os períodos são sempre explícitos (AAAAMM), o que torna a consulta
    determinística e permite usá-la como chave de cache.
    """

    territorios: tuple[Territorio, ...]
    variaveis: tuple[int, ...]
    periodos: tuple[str, ...]
    produtos: tuple[str, ...] = ()
    tabela: int = TABELA_LSPA_SERIE_HISTORICA

    def __post_init__(self):
        if self.tabela not in TABELAS_LSPA_SUPORTADAS:
            raise ValueError(f"Tabela não suportada: {self.tabela!r}")
        if not self.territorios:
            raise ValueError("Informe ao menos um nível territorial.")
        niveis = [t.nivel for t in self.territorios]
        if len(set(niveis)) != len(niveis):
            raise ValueError("Nível territorial repetido na consulta.")

        variaveis = tuple(dict.fromkeys(int(v) for v in self.variaveis))
        if not variaveis or any(v not in VARIAVEIS_LSPA for v in variaveis):
            raise ValueError(f"Variáveis inválidas: {self.variaveis!r}")

        periodos = tuple(dict.fromkeys(str(p).strip() for p in self.periodos))
        if not periodos or any(not _RE_PERIODO.match(p) for p in periodos):
            raise ValueError(f"Períodos inválidos: {self.periodos!r}")

        object.__setattr__(self, "variaveis", tuple(sorted(variaveis)))
        object.__setattr__(self, "periodos", tuple(sorted(periodos)))
        object.__setattr__(self, "produtos", tuple(sorted(_validar_codigos(self.produtos, "produto"), key=int)))
        object.__setattr__(
            self,
            "territorios",
            tuple(
                Territorio(t.nivel, tuple(sorted(t.localidades, key=int)))
                for t in sorted(self.territorios, key=lambda t: t.nivel)
            ),
        )

    def caminho(self) -> str:
        """Caminho canônico da consulta (também usado como chave de cache)."""
        territorios = "/".join(t.segmento() for t in self.territorios)
        variaveis = ",".join(str(v) for v in self.variaveis)
        periodos = ",".join(self.periodos)
        produtos = ",".join(self.produtos) if self.produtos else "all"
        return (
            f"/values/t/{self.tabela}/{territorios}/v/{variaveis}"
            f"/p/{periodos}/c{CLASSIFICACAO_PRODUTO}/{produtos}"
        )

    def estimar_valores(self, total_localidades: dict[str, int], total_produtos: int) -> int:
        """Estimativa de quantos valores a consulta retornará."""
        locais = sum(
            len(t.localidades) or total_localidades.get(t.nivel, 30) for t in self.territorios
        )
        produtos = len(self.produtos) or total_produtos
        return locais * len(self.variaveis) * len(self.periodos) * produtos


# --- Endpoints de metadados ------------------------------------------------
def caminho_metadados(tabela: int) -> str:
    _validar_tabela(tabela)
    return f"/{tabela}/metadados"


def caminho_periodos(tabela: int) -> str:
    _validar_tabela(tabela)
    return f"/{tabela}/periodos"


def caminho_localidades(tabela: int, niveis: tuple[str, ...] = tuple(NIVEIS_TERRITORIAIS)) -> str:
    _validar_tabela(tabela)
    for nivel in niveis:
        if nivel not in NIVEIS_TERRITORIAIS:
            raise ValueError(f"Nível territorial inválido: {nivel!r}")
    return f"/{tabela}/localidades/{'|'.join(niveis)}"


def _validar_tabela(tabela: int) -> None:
    if tabela not in TABELAS_LSPA_SUPORTADAS:
        raise ValueError(f"Tabela não suportada: {tabela!r}")
