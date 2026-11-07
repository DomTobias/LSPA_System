"""Testes das regras de negócio: filtros, períodos, cache, indicadores e CSV."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.exceptions import ParametroInvalidoError, SidraIndisponivelError
from app.services.dashboard_service import DashboardService, participacao_percentual, variacao_percentual
from app.services.sidra_service import ORIGEM_API, ORIGEM_CACHE, ORIGEM_CACHE_EXPIRADO


# ---------------------------------------------------------------- Validação de filtros
class TestValidacaoFiltros:
    def test_filtros_validos(self, servicos):
        f = servicos.producao.validar_filtros({
            "produto": "39443", "indicador": "producao", "regiao": "5", "estado": "51",
            "ano": "2026", "mes": "9", "ordenar": "valor", "direcao": "DESC", "pagina": "2", "por_pagina": "50",
        })
        assert (f.produto, f.indicador, f.regiao, f.estado, f.ano, f.mes) == ("39443", "producao", "5", "51", 2026, 9)
        assert (f.ordenar, f.direcao, f.pagina, f.por_pagina) == ("valor", "desc", 2, 50)

    def test_indicador_aceita_codigo_numerico(self, servicos):
        assert servicos.producao.validar_filtros({"indicador": "36"}).indicador == "rendimento_medio"

    def test_valores_vazios_sao_ignorados(self, servicos):
        f = servicos.producao.validar_filtros({"produto": "", "estado": "  ", "ano": ""})
        assert f.produto is None and f.estado is None and f.ano is None and f.pagina == 1

    @pytest.mark.parametrize("args,trecho", [
        ({"produto": "99999"}, "Produto"),
        ({"produto": "1;DROP TABLE producao"}, "Produto"),
        ({"indicador": "lucro"}, "Indicador"),
        ({"regiao": "9"}, "Região"),
        ({"estado": "99"}, "Estado"),
        ({"regiao": "4", "estado": "51"}, "não pertence"),
        ({"ano": "1990"}, "ano 1990"),
        ({"ano": "abc"}, "inteiro"),
        ({"mes": "13"}, "intervalo"),
        ({"mes": "todos"}, "selecione um ano"),
        ({"ordenar": "senha"}, "ordenação"),
        ({"direcao": "lado"}, "direção"),
        ({"pagina": "0"}, "intervalo"),
        ({"por_pagina": "10000"}, "intervalo"),
        ({"busca": "x" * 101}, "100 caracteres"),
    ])
    def test_filtros_invalidos(self, servicos, args, trecho):
        with pytest.raises(ParametroInvalidoError, match=trecho):
            servicos.producao.validar_filtros(args)


# ---------------------------------------------------------------- Períodos
class TestPeriodos:
    def test_resolucao_de_periodos(self, servicos):
        resolver = lambda ano, mes: [p.codigo for p in servicos.producao.resolver_periodos(ano, mes)]
        assert resolver(None, None) == ["202609"]
        assert resolver(2025, None) == ["202512"]          # última estimativa do ano fechado
        assert resolver(2025, 8) == ["202508"]
        assert resolver(None, 12) == ["202512"]            # mês no ano mais recente disponível
        assert resolver(2024, "todos") == ["202410", "202411", "202412"]

    def test_mes_inexistente(self, servicos):
        with pytest.raises(ParametroInvalidoError, match="março de 2026"):
            servicos.producao.resolver_periodos(2026, 3)

    def test_evolucao_anual_usa_dezembro_e_periodo_selecionado(self, servicos):
        periodos = servicos.producao.listar_periodos()
        selecionado = next(p for p in periodos if p.codigo == "202608")
        anual = DashboardService.periodos_evolucao_anual(periodos, selecionado)
        assert [p.codigo for p in anual] == ["202412", "202512", "202608"]
        mensal = DashboardService.periodos_evolucao_mensal(periodos, selecionado, meses=3)
        assert [p.codigo for p in mensal] == ["202509", "202512", "202608"]


# ---------------------------------------------------------------- Montagem das consultas
class TestMontagemConsulta:
    def montar(self, servicos, **args):
        filtros = servicos.producao.validar_filtros(args)
        return servicos.producao.montar_consulta(filtros)[0].caminho()

    def test_estado(self, servicos):
        assert self.montar(servicos, estado="51", produto="39443", indicador="producao") == \
            "/values/t/6588/n3/51/v/35/p/202609/c48/39443"

    def test_regiao_inclui_regiao_e_seus_estados(self, servicos):
        assert self.montar(servicos, regiao="4", indicador="producao") == \
            "/values/t/6588/n2/4/n3/41,43/v/35/p/202609/c48/all"

    def test_sem_localidade_traz_brasil_regioes_e_estados(self, servicos):
        assert self.montar(servicos) == "/values/t/6588/n1/all/n2/all/n3/all/v/35,36,109,216/p/202609/c48/all"


# ---------------------------------------------------------------- Consulta, busca, ordenação, paginação
class TestConsulta:
    def test_paginacao(self, servicos):
        r = servicos.producao.consultar({"produto": "39443", "por_pagina": "5", "pagina": "2"})
        assert r["total"] == 7 * 4  # 7 localidades x 4 indicadores
        assert r["pagina"] == 2 and r["total_paginas"] == 6 and len(r["linhas"]) == 5
        assert r["meta"]["tabela"] == 6588 and r["meta"]["origem"] == ORIGEM_API

    def test_pagina_alem_do_fim_volta_para_ultima(self, servicos):
        r = servicos.producao.consultar({"produto": "39443", "por_pagina": "10", "pagina": "99"})
        assert r["pagina"] == r["total_paginas"] == 3

    def test_ordenacao_por_valor_com_simbolos_no_final(self, servicos):
        r = servicos.producao.consultar({"produto": "39449", "indicador": "producao", "ordenar": "valor",
                                         "direcao": "desc", "por_pagina": "100"})
        valores = [l["valor"] for l in r["linhas"]]
        numericos = [v for v in valores if v is not None]
        assert numericos == sorted(numericos, reverse=True)
        assert valores[-1] is None and r["linhas"][-1]["simbolo"] == "-"

    def test_busca_ignora_acentos_e_maiusculas(self, servicos):
        r = servicos.producao.consultar({"produto": "39443", "busca": "PARANA", "por_pagina": "100"})
        assert r["total"] == 4 and {l["localidade"] for l in r["linhas"]} == {"Paraná"}

    def test_linha_contem_campos_da_tabela(self, servicos):
        linha = servicos.producao.consultar({"estado": "51", "produto": "39443", "indicador": "producao"})["linhas"][0]
        assert linha["produto"] == "Soja" and linha["localidade"] == "Mato Grosso"
        assert linha["indicador"] == "Produção" and linha["unidade"] == "Toneladas"
        assert (linha["ano"], linha["mes"], linha["mes_nome"]) == (2026, 9, "Setembro")

    def test_limite_de_tamanho_da_consulta(self, servicos, monkeypatch):
        monkeypatch.setattr("app.services.sidra_service.LIMITE_VALORES_POR_CONSULTA", 10)
        with pytest.raises(ParametroInvalidoError, match="Refine os filtros"):
            servicos.producao.consultar({})

    def test_exportar_csv(self, servicos):
        csv = servicos.producao.exportar_csv({"estado": "43", "indicador": "producao", "ordenar": "produto"})
        assert csv.startswith("﻿Produto;Localidade;")
        linhas = csv.strip().splitlines()
        assert any(l.startswith("Banana;Rio Grande do Sul;N3;Produção;-;Toneladas;2026;Setembro") for l in linhas)
        assert "tabela 6588" in linhas[-1]


# ---------------------------------------------------------------- Cache e revisões
class TestCache:
    def test_segunda_consulta_usa_cache(self, servicos, cliente_falso):
        servicos.producao.consultar({"produto": "39443"})
        r = servicos.producao.consultar({"produto": "39443", "pagina": "2"})
        assert len(cliente_falso.chamadas_de_valores()) == 1
        assert r["meta"]["origem"] == ORIGEM_CACHE

    def test_metadados_carregados_uma_vez(self, servicos, cliente_falso):
        for _ in range(3):
            servicos.producao.opcoes_filtros()
        assert cliente_falso.chamadas.count("metadados/6588") == 1
        assert cliente_falso.chamadas.count("periodos/6588") == 1

    def test_cache_vencido_reconsulta_e_registra_revisao(self, servicos, cliente_falso):
        sidra = servicos.sidra
        args = {"estado": "51", "produto": "39443", "indicador": "producao"}
        antes = servicos.producao.consultar(args)["linhas"][0]["valor"]

        cliente_falso.ajuste_valores = 500  # IBGE revisa a estimativa
        sidra._agora = lambda: datetime.now(timezone.utc) + timedelta(hours=7)
        r = servicos.producao.consultar(args)

        assert r["meta"]["origem"] == ORIGEM_API
        assert r["linhas"][0]["valor"] == antes + 500
        assert len(cliente_falso.chamadas_de_valores()) == 2
        revisoes = servicos.repositorio.listar_revisoes()
        assert len(revisoes) == 1 and revisoes[0]["valor_anterior"] == antes

    def test_api_indisponivel_com_cache_vencido_devolve_dados_locais(self, servicos, cliente_falso):
        args = {"estado": "51", "produto": "39443"}
        servicos.producao.consultar(args)
        servicos.sidra._agora = lambda: datetime.now(timezone.utc) + timedelta(days=30)
        cliente_falso.indisponivel = True
        r = servicos.producao.consultar(args)
        assert r["meta"]["origem"] == ORIGEM_CACHE_EXPIRADO and r["meta"]["avisos"]
        assert r["total"] == 4

    def test_api_indisponivel_sem_cache_propaga_erro(self, servicos, cliente_falso):
        servicos.producao.opcoes_filtros()
        cliente_falso.indisponivel = True
        with pytest.raises(SidraIndisponivelError):
            servicos.producao.consultar({"produto": "39443"})
        (consulta,) = [c for c in servicos.repositorio.listar_consultas() if c["tipo"] == "valores"]
        assert consulta["status"] == "erro" and consulta["executada_em"] is None


# ---------------------------------------------------------------- Indicadores do dashboard
class TestDashboard:
    def test_calculos_percentuais(self):
        assert variacao_percentual(110, 100) == 10.0
        assert variacao_percentual(90, 100) == -10.0
        assert variacao_percentual(None, 100) is None
        assert variacao_percentual(5, 0) is None
        assert participacao_percentual(25, 200) == 12.5
        assert participacao_percentual(25, None) is None

    def test_produto_inicial_e_agregado_de_nivel_1(self, servicos):
        produto = servicos.dashboard.produto_inicial(servicos.producao.listar_produtos())
        assert produto.codigo == "39428"

    def test_dashboard_completo(self, servicos, cliente_falso):
        d = servicos.dashboard.obter_dashboard({"produto": "39443"})
        assert d["produto"]["nome"] == "Soja" and d["periodo"]["codigo"] == "202609"
        assert d["periodo_ano_anterior"]["codigo"] == "202509"
        assert d["periodo_mes_anterior"]["codigo"] == "202608"
        assert len(cliente_falso.chamadas_de_valores()) == 3

        kpis = {k["chave"]: k for k in d["kpis"]}
        assert set(kpis) == {"producao", "area_plantada", "area_colhida", "rendimento_medio"}
        producao = kpis["producao"]
        assert producao["valor"] > 0 and producao["unidade"] == "Toneladas"
        assert producao["variacao_anual"] is not None and producao["variacao_mensal"] is not None

        ranking = d["ranking"]
        assert [r["posicao"] for r in ranking] == list(range(1, len(ranking) + 1))
        assert [r["valor"] for r in ranking] == sorted((r["valor"] for r in ranking), reverse=True)
        assert all(0 < r["participacao"] < 100 for r in ranking)

        assert [i["nome"] for i in d["regioes"]["itens"]] == ["Sul", "Centro-Oeste"]
        assert all(not i["nome"].startswith(("Total", "Cereais", "Café total")) for i in d["produtos"]["itens"])
        assert d["evolucao"]["anual"]["periodos"] == ["202412", "202512", "202609"]

        # segunda chamada não acessa a API
        servicos.dashboard.obter_dashboard({"produto": "39443"})
        assert len(cliente_falso.chamadas_de_valores()) == 3

    def test_kpi_sem_valor_publicado_mantem_simbolo(self, servicos):
        d = servicos.dashboard.obter_dashboard({"produto": "0"})
        producao = next(k for k in d["kpis"] if k["chave"] == "producao")
        assert producao["valor"] is None and producao["simbolo"] == ".."

    def test_dashboard_parametros_invalidos(self, servicos):
        with pytest.raises(ParametroInvalidoError):
            servicos.dashboard.obter_dashboard({"produto": "abc"})
        with pytest.raises(ParametroInvalidoError):
            servicos.dashboard.obter_dashboard({"ano": "1800"})
