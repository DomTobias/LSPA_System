"""Fixtures compartilhadas dos testes.

O ``ClienteSidraFalso`` reproduz o FORMATO das respostas reais da API SIDRA
(verificado em requisições reais), mas com valores sintéticos e
determinísticos — eles servem apenas para testar a lógica da aplicação e não
representam dados do IBGE.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from app.config.settings import TestingConfig  # noqa: E402
from app.exceptions import SidraIndisponivelError  # noqa: E402

METADADOS = {
    "id": 6588,
    "nome": "Série histórica da estimativa anual da área plantada, área colhida, produção e rendimento médio dos produtos das lavouras",
    "variaveis": [
        {"id": 109, "nome": "Área plantada", "unidade": "Hectares", "sumarizacao": ["nivelTerritorial"]},
        {"id": 216, "nome": "Área colhida", "unidade": "Hectares", "sumarizacao": ["nivelTerritorial"]},
        {"id": 35, "nome": "Produção", "unidade": "Toneladas", "sumarizacao": ["nivelTerritorial"]},
        {"id": 36, "nome": "Rendimento médio", "unidade": "Quilogramas por Hectare", "sumarizacao": []},
    ],
    "classificacoes": [{
        "id": 48,
        "nome": "Produto das lavouras",
        "categorias": [
            {"id": 0, "nome": "Total", "nivel": 0},
            {"id": 39428, "nome": "1 Cereais, leguminosas e oleaginosas", "nivel": 1},
            {"id": 39432, "nome": "1.4 Arroz", "nivel": 2},
            {"id": 39443, "nome": "1.17 Soja", "nivel": 2},
            {"id": 39449, "nome": "4 Banana", "nivel": 1},
            {"id": 40527, "nome": "9/10 Café total", "nivel": 1},
            {"id": 39454, "nome": "9 Café arábica", "nivel": 2},
            {"id": 39456, "nome": "11 Cana-de-açúcar", "nivel": 1},
        ],
    }],
}

PERIODOS = [
    {"id": p, "literals": [f"{n} {p[:4]}"], "modificacao": "15/10/2026"}
    for p, n in [
        ("202410", "outubro"), ("202411", "novembro"), ("202412", "dezembro"),
        ("202508", "agosto"), ("202509", "setembro"), ("202512", "dezembro"),
        ("202608", "agosto"), ("202609", "setembro"),
    ]
]

LOCALIDADES = [
    {"id": "1", "nome": "Brasil", "nivel": {"id": "N1", "nome": "Brasil"}},
    {"id": "4", "nome": "Sul", "nivel": {"id": "N2", "nome": "Grande Região"}},
    {"id": "5", "nome": "Centro-Oeste", "nivel": {"id": "N2", "nome": "Grande Região"}},
    {"id": "41", "nome": "Paraná", "nivel": {"id": "N3", "nome": "Unidade da Federação"}},
    {"id": "43", "nome": "Rio Grande do Sul", "nivel": {"id": "N3", "nome": "Unidade da Federação"}},
    {"id": "51", "nome": "Mato Grosso", "nivel": {"id": "N3", "nome": "Unidade da Federação"}},
    {"id": "52", "nome": "Goiás", "nivel": {"id": "N3", "nome": "Unidade da Federação"}},
]

_NOMES_NIVEL = {"N1": "Brasil", "N2": "Grande Região", "N3": "Unidade da Federação"}
_VARIAVEIS = {v["id"]: v for v in METADADOS["variaveis"]}
_PRODUTOS = {str(c["id"]): c["nome"] for c in METADADOS["classificacoes"][0]["categorias"]}
_LOCAIS = {(l["nivel"]["id"], l["id"]): l["nome"] for l in LOCALIDADES}


def valor_sintetico(nivel: str, localidade: str, produto: str, variavel: int, periodo: str) -> str:
    """Valor determinístico de teste (NÃO é dado do IBGE)."""
    if produto == "0" and variavel in (35, 36):
        return ".."  # o IBGE não soma produção/rendimento entre produtos
    if produto == "39449" and localidade == "43":
        return "-"
    base = {"N1": 1000, "N2": 400, "N3": 100}[nivel] + int(localidade) + int(produto) % 97
    fator = {35: 1000, 109: 300, 216: 290, 36: 1}[variavel]
    ajuste = int(periodo[:4]) - 2020 + int(periodo[4:]) / 100
    return str(int((base + ajuste) * fator))


class ClienteSidraFalso:
    """Substituto do SidraClient para testes (mesma interface pública)."""

    def __init__(self):
        self.chamadas: list[str] = []
        self.indisponivel = False
        self.ajuste_valores = 0  # simula revisões do IBGE

    def _registrar(self, chamada: str):
        self.chamadas.append(chamada)
        if self.indisponivel:
            raise SidraIndisponivelError()

    def consultar_metadados(self, tabela):
        self._registrar(f"metadados/{tabela}")
        return METADADOS

    def consultar_periodos(self, tabela):
        self._registrar(f"periodos/{tabela}")
        return PERIODOS

    def consultar_localidades(self, tabela, niveis=("N1", "N2", "N3")):
        self._registrar(f"localidades/{tabela}")
        return LOCALIDADES

    def consultar_valores(self, consulta):
        self._registrar(consulta.caminho())
        cabecalho = {
            "NC": "Nível Territorial (Código)", "NN": "Nível Territorial",
            "MC": "Unidade de Medida (Código)", "MN": "Unidade de Medida", "V": "Valor",
            "D1C": f"{_NOMES_NIVEL[consulta.territorios[0].nivel]} (Código)",
            "D1N": _NOMES_NIVEL[consulta.territorios[0].nivel],
            "D2C": "Variável (Código)", "D2N": "Variável",
            "D3C": "Mês (Código)", "D3N": "Mês",
            "D4C": "Produto das lavouras (Código)", "D4N": "Produto das lavouras",
        }
        linhas = [cabecalho]
        produtos = consulta.produtos or tuple(_PRODUTOS)
        for territorio in consulta.territorios:
            locais = territorio.localidades or tuple(c for (n, c) in _LOCAIS if n == territorio.nivel)
            for local in locais:
                for variavel in consulta.variaveis:
                    for periodo in consulta.periodos:
                        for produto in produtos:
                            valor = valor_sintetico(territorio.nivel, local, produto, variavel, periodo)
                            if valor.isdigit() and self.ajuste_valores:
                                valor = str(int(valor) + self.ajuste_valores)
                            linhas.append({
                                "NC": territorio.nivel[1], "NN": _NOMES_NIVEL[territorio.nivel],
                                "MC": "1017", "MN": _VARIAVEIS[variavel]["unidade"], "V": valor,
                                "D1C": local, "D1N": _LOCAIS[(territorio.nivel, local)],
                                "D2C": str(variavel), "D2N": _VARIAVEIS[variavel]["nome"],
                                "D3C": periodo, "D3N": periodo,
                                "D4C": produto, "D4N": _PRODUTOS[produto],
                            })
        return linhas

    def chamadas_de_valores(self) -> list[str]:
        return [c for c in self.chamadas if c.startswith("/values")]


@pytest.fixture
def cliente_falso():
    return ClienteSidraFalso()


@pytest.fixture
def app(tmp_path, cliente_falso):
    class Config(TestingConfig):
        DATABASE_PATH = str(tmp_path / "teste.db")

    aplicacao = create_app(Config, cliente_sidra=cliente_falso)
    yield aplicacao


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def servicos(app):
    return app.extensions["lspa"]
