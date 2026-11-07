"""Testes do repositório: persistência, duplicidade, revisões e SQL Injection."""
from __future__ import annotations

import pytest

from app.models import Producao
from app.repositories.producao_repository import ProducaoRepository
from database.connection import Database


@pytest.fixture
def repositorio(tmp_path):
    banco = Database(str(tmp_path / "repo.db"))
    banco.inicializar()
    return ProducaoRepository(banco)


def observacao(valor=100.0, simbolo=None, localidade="51", periodo="202609", variavel=35):
    return Producao(
        tabela=6588, periodo=periodo, nivel="N3", localidade_codigo=localidade, localidade_nome="Mato Grosso",
        produto_codigo="39443", produto_nome="Soja", variavel_codigo=variavel, variavel_nome="Produção",
        unidade="Toneladas", valor=valor, simbolo=simbolo,
    )


def test_upsert_nao_duplica_registros(repositorio):
    cid = repositorio.registrar_consulta("valores", 6588, "/values/a")
    repositorio.salvar_producao([observacao()], cid)
    repositorio.salvar_producao([observacao()], cid)
    with repositorio.banco.conexao() as con:
        assert con.execute("SELECT COUNT(*) FROM producao").fetchone()[0] == 1
        assert con.execute("SELECT versao FROM producao").fetchone()[0] == 1
    assert repositorio.listar_revisoes() == []


def test_revisao_atualiza_valor_e_guarda_historico(repositorio):
    cid = repositorio.registrar_consulta("valores", 6588, "/values/a")
    repositorio.salvar_producao([observacao(100.0)], cid)
    repositorio.salvar_producao([observacao(120.0)], cid)
    repositorio.salvar_producao([observacao(None, simbolo="...")], cid)

    (atual,) = repositorio.buscar_producao(6588, [("N3", ["51"])], [35], ["202609"])
    assert atual.valor is None and atual.simbolo == "..."
    with repositorio.banco.conexao() as con:
        assert con.execute("SELECT versao FROM producao").fetchone()[0] == 3
    revisoes = repositorio.listar_revisoes()
    assert [(r["valor_anterior"], r["valor_novo"]) for r in reversed(revisoes)] == [(100.0, 120.0), (120.0, None)]


def test_buscar_aplica_filtros(repositorio):
    repositorio.salvar_producao([
        observacao(localidade="51"), observacao(localidade="41"),
        observacao(periodo="202608"), observacao(variavel=109),
    ], None)
    assert len(repositorio.buscar_producao(6588, [("N3", ["51"])], [35], ["202609"])) == 1
    assert len(repositorio.buscar_producao(6588, [("N3", [])], [35], ["202609"])) == 2
    assert len(repositorio.buscar_producao(6588, [("N3", [])], [35, 109], ["202608", "202609"])) == 4
    assert repositorio.buscar_producao(6588, [("N1", [])], [35], ["202609"]) == []


def test_parametros_maliciosos_nao_executam_sql(repositorio):
    repositorio.salvar_producao([observacao()], None)
    malicioso = "51' OR '1'='1"
    assert repositorio.buscar_producao(6588, [("N3", [malicioso])], [35], ["202609"]) == []
    assert repositorio.buscar_producao(6588, [("N3", ["51"])], [35], ["202609"], ["1); DROP TABLE producao; --"]) == []
    assert repositorio.estatisticas()["observacoes"] == 1


def test_registro_de_consultas_sucesso_e_erro(repositorio):
    repositorio.registrar_consulta("valores", 6588, "/values/x", sucesso=False, mensagem="fora do ar")
    registro = repositorio.obter_consulta("/values/x")
    assert registro["status"] == "erro" and registro["executada_em"] is None

    repositorio.registrar_consulta("valores", 6588, "/values/x", {"a": 1}, registros=10)
    registro = repositorio.obter_consulta("/values/x")
    assert registro["status"] == "sucesso" and registro["executada_em"] and registro["execucoes"] == 2

    repositorio.registrar_consulta("valores", 6588, "/values/x", sucesso=False, mensagem="timeout")
    registro = repositorio.obter_consulta("/values/x")
    assert registro["status"] == "erro" and registro["executada_em"]  # mantém a última execução válida


def test_banco_em_memoria():
    banco = Database(":memory:")
    banco.inicializar()
    repositorio = ProducaoRepository(banco)
    repositorio.salvar_producao([observacao()], None)
    assert repositorio.estatisticas()["observacoes"] == 1
    banco.fechar()
