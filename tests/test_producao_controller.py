"""Testes dos controllers e rotas (páginas e API interna)."""
from __future__ import annotations

import pytest


class TestPaginas:
    @pytest.mark.parametrize("url", ["/", "/dashboard", "/producao"])
    def test_paginas_renderizam(self, client, url):
        resposta = client.get(url)
        assert resposta.status_code == 200
        html = resposta.get_data(as_text=True)
        assert 'lang="pt-BR"' in html and "LSPA Analytics" in html
        assert "Consulta de produção" in html  # menu lateral

    def test_dashboard_preenche_filtros_dinamicos(self, client):
        html = client.get("/dashboard").get_data(as_text=True)
        assert 'value="39443"' in html and "Soja" in html       # produtos vindos dos metadados
        assert '<option value="2026"' in html                    # anos vindos dos períodos
        assert 'value="39428" selected' in html                   # produto inicial

    def test_producao_preseleciona_filtros_da_url(self, client):
        html = client.get("/producao?produto=39443&regiao=5").get_data(as_text=True)
        assert 'value="39443" selected' in html and 'value="5" selected' in html

    def test_pagina_inexistente(self, client):
        resposta = client.get("/nao-existe")
        assert resposta.status_code == 404 and "não foi encontrado" in resposta.get_data(as_text=True)

    def test_pagina_com_ibge_indisponivel_mostra_mensagem(self, client, cliente_falso):
        cliente_falso.indisponivel = True
        resposta = client.get("/dashboard")
        assert resposta.status_code == 503
        assert "indisponível" in resposta.get_data(as_text=True)

    def test_cabecalhos_de_seguranca(self, client):
        resposta = client.get("/dashboard")
        assert resposta.headers["X-Content-Type-Options"] == "nosniff"
        assert resposta.headers["X-Frame-Options"] == "DENY"
        assert "default-src 'self'" in resposta.headers["Content-Security-Policy"]


class TestApi:
    @pytest.mark.parametrize("url,minimo", [
        ("/api/produtos", 8), ("/api/localidades", 7), ("/api/periodos", 8), ("/api/indicadores", 4),
    ])
    def test_catalogos(self, client, url, minimo):
        resposta = client.get(url)
        assert resposta.status_code == 200 and resposta.is_json
        assert resposta.json["total"] == len(resposta.json["itens"]) >= minimo

    def test_filtros_dos_catalogos(self, client):
        assert all(not p["agregado"] for p in client.get("/api/produtos?agregados=0").json["itens"])
        ufs = client.get("/api/localidades?nivel=N3&regiao=4").json["itens"]
        assert {u["sigla"] for u in ufs} == {"PR", "RS"}
        assert client.get("/api/periodos?ano=2024").json["total"] == 3

    def test_catalogos_parametros_invalidos(self, client):
        assert client.get("/api/localidades?nivel=N9").status_code == 400
        assert client.get("/api/periodos?ano=x").status_code == 400

    def test_producao_json(self, client):
        resposta = client.get("/api/producao?produto=39443&estado=51")
        assert resposta.status_code == 200
        corpo = resposta.json
        assert corpo["total"] == 4 and corpo["linhas"][0]["localidade"] == "Mato Grosso"
        assert resposta.headers["Cache-Control"] == "no-store"

    def test_producao_parametro_invalido_retorna_400_json(self, client):
        resposta = client.get("/api/producao?estado=XX")
        assert resposta.status_code == 400
        assert resposta.json["erro"] == "ParametroInvalidoError" and "Estado" in resposta.json["mensagem"]

    def test_producao_formato_invalido(self, client):
        assert client.get("/api/producao?formato=xml").status_code == 400

    def test_producao_csv(self, client):
        resposta = client.get("/api/producao?produto=39443&estado=51&formato=csv")
        assert resposta.status_code == 200
        assert resposta.mimetype == "text/csv"
        assert "attachment" in resposta.headers["Content-Disposition"]
        assert resposta.get_data(as_text=True).lstrip("﻿").startswith("Produto;Localidade")

    def test_dashboard_json(self, client):
        resposta = client.get("/api/dashboard?produto=39443&ano=2025&mes=9")
        assert resposta.status_code == 200
        corpo = resposta.json
        assert corpo["periodo"]["codigo"] == "202509" and corpo["periodo_ano_anterior"] is None
        assert {"kpis", "evolucao", "estados", "ranking", "produtos", "regioes", "meta"} <= set(corpo)

    def test_dashboard_parametro_invalido(self, client):
        assert client.get("/api/dashboard?mes=15").status_code == 400

    def test_api_indisponivel_retorna_503(self, client, cliente_falso):
        cliente_falso.indisponivel = True
        resposta = client.get("/api/produtos")
        assert resposta.status_code == 503 and "indisponível" in resposta.json["mensagem"]

    def test_rota_api_inexistente_retorna_json_404(self, client):
        resposta = client.get("/api/nada")
        assert resposta.status_code == 404 and resposta.is_json

    def test_metodo_nao_permitido(self, client):
        assert client.post("/api/producao").status_code == 405

    def test_status(self, client):
        client.get("/api/producao?produto=39443&estado=51")
        status = client.get("/api/status").json
        assert status["observacoes"] == 4 and status["consultas"] == 1
