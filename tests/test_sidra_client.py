"""Testes da integração com o SIDRA: endpoints, cliente HTTP e parser."""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
import requests

from app.exceptions import (
    SidraConsultaInvalidaError,
    SidraIndisponivelError,
    SidraRespostaInvalidaError,
)
from app.integrations.ibge import sidra_parser as parser
from app.integrations.ibge.sidra_client import SidraClient
from app.integrations.ibge.sidra_endpoints import ConsultaValores, Territorio, caminho_localidades
from tests.conftest import LOCALIDADES, METADADOS, PERIODOS

# Amostra no formato exato retornado por apisidra.ibge.gov.br/values (estrutura real)
RESPOSTA_VALORES = [
    {"NC": "Nível Territorial (Código)", "NN": "Nível Territorial", "MC": "Unidade de Medida (Código)",
     "MN": "Unidade de Medida", "V": "Valor", "D1C": "Unidade da Federação (Código)",
     "D1N": "Unidade da Federação", "D2C": "Variável (Código)", "D2N": "Variável",
     "D3C": "Mês (Código)", "D3N": "Mês", "D4C": "Produto das lavouras (Código)",
     "D4N": "Produto das lavouras"},
    {"NC": "3", "NN": "Unidade da Federação", "MC": "1017", "MN": "Toneladas", "V": "12345",
     "D1C": "51", "D1N": "Mato Grosso", "D2C": "35", "D2N": "Produção", "D3C": "202609",
     "D3N": "setembro 2026", "D4C": "39443", "D4N": "1.17 Soja"},
    {"NC": "3", "NN": "Unidade da Federação", "MC": "1017", "MN": "Toneladas", "V": "-",
     "D1C": "12", "D1N": "Acre", "D2C": "35", "D2N": "Produção", "D3C": "202609",
     "D3N": "setembro 2026", "D4C": "39443", "D4N": "1.17 Soja"},
]


def consulta_exemplo(**kwargs):
    padrao = dict(
        territorios=(Territorio("N3", ("51",)),), variaveis=(35,), periodos=("202609",), produtos=("39443",)
    )
    padrao.update(kwargs)
    return ConsultaValores(**padrao)


def resposta_http(status=200, json_data=None, texto="", erro_json=False):
    resposta = MagicMock()
    resposta.status_code = status
    resposta.text = texto
    resposta.content = texto.encode() or b"[]"
    if erro_json:
        resposta.json.side_effect = ValueError("JSON inválido")
    else:
        resposta.json.return_value = json_data
    return resposta


def cliente_com(resposta=None, excecao=None):
    sessao = MagicMock(spec=requests.Session)
    if excecao:
        sessao.get.side_effect = excecao
    else:
        sessao.get.return_value = resposta
    return SidraClient(timeout=7, session=sessao), sessao


# ---------------------------------------------------------------- Endpoints
class TestEndpoints:
    def test_caminho_canonico_ordena_e_remove_duplicados(self):
        consulta = ConsultaValores(
            territorios=(Territorio("N3", ("51", "41", "51")), Territorio("N1")),
            variaveis=(109, 35, 35),
            periodos=("202609", "202512"),
            produtos=("39443", "39432"),
        )
        assert consulta.caminho() == (
            "/values/t/6588/n1/all/n3/41,51/v/35,109/p/202512,202609/c48/39432,39443"
        )

    def test_consultas_equivalentes_tem_mesma_chave(self):
        a = consulta_exemplo(variaveis=(35, 109))
        b = consulta_exemplo(variaveis=(109, 35))
        assert a.caminho() == b.caminho()

    def test_produtos_vazio_significa_todos(self):
        assert consulta_exemplo(produtos=()).caminho().endswith("/c48/all")

    @pytest.mark.parametrize("valor_malicioso", ["51;DROP", "../x", "http://evil", "51/v/1", "", "abc"])
    def test_rejeita_codigos_de_localidade_invalidos(self, valor_malicioso):
        with pytest.raises(ValueError):
            Territorio("N3", (valor_malicioso,))

    def test_rejeita_variavel_periodo_tabela_e_nivel_invalidos(self):
        with pytest.raises(ValueError):
            consulta_exemplo(variaveis=(999,))
        with pytest.raises(ValueError):
            consulta_exemplo(periodos=("202613",))
        with pytest.raises(ValueError):
            consulta_exemplo(tabela=1234)
        with pytest.raises(ValueError):
            Territorio("N6")
        with pytest.raises(ValueError):
            consulta_exemplo(produtos=("1 OR 1=1",))

    def test_caminho_localidades(self):
        assert caminho_localidades(6588) == "/6588/localidades/N1|N2|N3"


# ---------------------------------------------------------------- Cliente HTTP
class TestSidraClient:
    def test_rejeita_url_base_fora_do_ibge(self):
        with pytest.raises(ValueError):
            SidraClient(url_valores="https://exemplo.com")
        with pytest.raises(ValueError):
            SidraClient(url_metadados="http://servicodados.ibge.gov.br/api/v3/agregados")

    def test_consulta_valores_monta_url_e_aplica_timeout(self):
        cliente, sessao = cliente_com(resposta_http(json_data=RESPOSTA_VALORES))
        dados = cliente.consultar_valores(consulta_exemplo())
        assert dados == RESPOSTA_VALORES
        url = sessao.get.call_args.args[0]
        assert url == "https://apisidra.ibge.gov.br/values/t/6588/n3/51/v/35/p/202609/c48/39443"
        assert sessao.get.call_args.kwargs["timeout"] == 7

    def test_metadados_usam_servicodados(self):
        cliente, sessao = cliente_com(resposta_http(json_data=METADADOS))
        assert cliente.consultar_metadados(6588)["id"] == 6588
        assert sessao.get.call_args.args[0] == "https://servicodados.ibge.gov.br/api/v3/agregados/6588/metadados"

    def test_timeout_gera_indisponivel(self):
        cliente, _ = cliente_com(excecao=requests.Timeout())
        with pytest.raises(SidraIndisponivelError):
            cliente.consultar_valores(consulta_exemplo())

    def test_falha_de_conexao_gera_indisponivel(self):
        cliente, _ = cliente_com(excecao=requests.ConnectionError("sem rede"))
        with pytest.raises(SidraIndisponivelError):
            cliente.consultar_periodos(6588)

    def test_http_400_gera_consulta_invalida_com_mensagem_do_ibge(self):
        texto = "Parâmetro V (Variável) com código 999 inexistente na tabela"
        cliente, _ = cliente_com(resposta_http(status=400, texto=texto))
        with pytest.raises(SidraConsultaInvalidaError, match="inexistente"):
            cliente.consultar_valores(consulta_exemplo())

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_http_5xx_gera_indisponivel(self, status):
        cliente, _ = cliente_com(resposta_http(status=status))
        with pytest.raises(SidraIndisponivelError):
            cliente.consultar_valores(consulta_exemplo())

    def test_json_invalido_gera_resposta_invalida(self):
        cliente, _ = cliente_com(resposta_http(texto="<html>erro</html>", erro_json=True))
        with pytest.raises(SidraRespostaInvalidaError):
            cliente.consultar_valores(consulta_exemplo())

    def test_tipo_inesperado_gera_resposta_invalida(self):
        cliente, _ = cliente_com(resposta_http(json_data={"erro": "x"}))
        with pytest.raises(SidraRespostaInvalidaError):
            cliente.consultar_valores(consulta_exemplo())

    def test_sessao_padrao_reutilizavel_com_retentativas(self):
        cliente = SidraClient(tentativas=3)
        adaptador = cliente.session.get_adapter("https://apisidra.ibge.gov.br")
        assert adaptador.max_retries.total == 3
        assert 503 in adaptador.max_retries.status_forcelist
        cliente.fechar()


# ---------------------------------------------------------------- Parser
class TestParser:
    def test_interpreta_valores_e_simbolos(self):
        observacoes = parser.interpretar_valores(RESPOSTA_VALORES, 6588)
        assert len(observacoes) == 2
        mt, acre = observacoes
        assert (mt.nivel, mt.localidade_codigo, mt.localidade_nome) == ("N3", "51", "Mato Grosso")
        assert (mt.variavel_codigo, mt.periodo, mt.ano, mt.mes) == (35, "202609", 2026, 9)
        assert mt.produto_codigo == "39443" and mt.produto_nome == "Soja"
        assert mt.valor == 12345.0 and mt.simbolo is None and mt.unidade == "Toneladas"
        assert acre.valor is None and acre.simbolo == "-"

    def test_identifica_dimensoes_pelo_cabecalho_em_qualquer_ordem(self):
        cabecalho = dict(RESPOSTA_VALORES[0])
        linha = dict(RESPOSTA_VALORES[1])
        # troca D2 (variável) com D4 (produto)
        for chave in ("C", "N"):
            cabecalho[f"D2{chave}"], cabecalho[f"D4{chave}"] = cabecalho[f"D4{chave}"], cabecalho[f"D2{chave}"]
            linha[f"D2{chave}"], linha[f"D4{chave}"] = linha[f"D4{chave}"], linha[f"D2{chave}"]
        (obs,) = parser.interpretar_valores([cabecalho, linha], 6588)
        assert obs.variavel_codigo == 35 and obs.produto_codigo == "39443"

    def test_resposta_somente_cabecalho_retorna_vazio(self):
        assert parser.interpretar_valores(RESPOSTA_VALORES[:1], 6588) == []
        assert parser.interpretar_valores([], 6588) == []

    @pytest.mark.parametrize("invalida", [{"a": 1}, ["texto"], [RESPOSTA_VALORES[0], {"NC": "3"}]])
    def test_estrutura_invalida(self, invalida):
        with pytest.raises(SidraRespostaInvalidaError):
            parser.interpretar_valores(invalida, 6588)

    @pytest.mark.parametrize("texto,esperado", [
        ("123", (123.0, None)), ("-", (None, "-")), ("..", (None, "..")),
        ("...", (None, "...")), ("X", (None, "X")), (None, (None, "...")),
    ])
    def test_interpretar_valor(self, texto, esperado):
        assert parser.interpretar_valor(texto) == esperado

    @pytest.mark.parametrize("nome,esperado", [
        ("1.17 Soja", ("1.17", "Soja")),
        ("9/10 Café total", ("9/10", "Café total")),
        ("1 Cereais, leguminosas e oleaginosas", ("1", "Cereais, leguminosas e oleaginosas")),
        ("Total", ("", "Total")),
    ])
    def test_limpar_nome_produto(self, nome, esperado):
        assert parser.limpar_nome_produto(nome) == esperado

    def test_produtos_com_hierarquia_e_agregados(self):
        produtos = {p.codigo: p for p in parser.interpretar_produtos(METADADOS)}
        assert produtos["0"].agregado and produtos["0"].pai_codigo is None
        assert produtos["39428"].agregado and produtos["39428"].pai_codigo == "0"
        assert not produtos["39443"].agregado and produtos["39443"].pai_codigo == "39428"
        assert produtos["40527"].agregado and produtos["39454"].pai_codigo == "40527"
        assert not produtos["39456"].agregado

    def test_indicadores_somabilidade_vem_dos_metadados(self):
        indicadores = {i.chave: i for i in parser.interpretar_indicadores(METADADOS)}
        assert set(indicadores) == {"producao", "area_plantada", "area_colhida", "rendimento_medio"}
        assert indicadores["producao"].somavel and not indicadores["rendimento_medio"].somavel

    def test_periodos_e_localidades(self):
        periodos = parser.interpretar_periodos(PERIODOS)
        assert periodos[-1].codigo == "202609" and periodos[-1].mes == 9 and periodos[-1].modificacao == "2026-10-15"
        localidades = parser.interpretar_localidades(LOCALIDADES)
        mt = next(l for l in localidades if l.codigo == "51")
        assert mt.nivel == "N3" and mt.regiao_codigo == "5" and mt.sigla == "MT"

    def test_metadados_sem_classificacao(self):
        with pytest.raises(SidraRespostaInvalidaError):
            parser.interpretar_produtos({"classificacoes": []})


# ---------------------------------------------------------------- Integração real (opcional)
@pytest.mark.skipif(os.getenv("SIDRA_TESTE_REAL") != "1", reason="defina SIDRA_TESTE_REAL=1 para testar a API real")
def test_integracao_real_com_sidra():
    cliente = SidraClient()
    metadados = cliente.consultar_metadados(6588)
    assert {v["id"] for v in metadados["variaveis"]} >= {35, 36, 109, 216}
    periodos = parser.interpretar_periodos(cliente.consultar_periodos(6588))
    ultimo = periodos[-1].codigo
    consulta = ConsultaValores(
        territorios=(Territorio("N1"), Territorio("N3", ("51",))),
        variaveis=(35, 109), periodos=(ultimo,), produtos=("39443",),
    )
    observacoes = parser.interpretar_valores(cliente.consultar_valores(consulta), 6588)
    assert len(observacoes) == 4
    assert all(o.produto_nome == "Soja" and o.periodo == ultimo for o in observacoes)
    assert all(o.valor is not None and o.valor > 0 for o in observacoes)
    cliente.fechar()
