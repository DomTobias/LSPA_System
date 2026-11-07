"""Controller da API interna (JSON e CSV)."""
from __future__ import annotations

from datetime import datetime

from flask import Response, jsonify, request

from app.controllers import obter_servicos
from app.exceptions import ParametroInvalidoError

NIVEIS_VALIDOS = {"N1", "N2", "N3"}


def producao():
    """GET /api/producao — consulta paginada; ``formato=csv`` exporta tudo."""
    servicos = obter_servicos()
    formato = (request.args.get("formato") or "json").lower()
    if formato == "csv":
        conteudo = servicos.producao.exportar_csv(request.args)
        nome = f"lspa_producao_{datetime.now():%Y%m%d_%H%M%S}.csv"
        return Response(
            conteudo,
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{nome}"'},
        )
    if formato != "json":
        raise ParametroInvalidoError("Formato inválido. Use 'json' ou 'csv'.")
    return jsonify(servicos.producao.consultar(request.args))


def produtos():
    """GET /api/produtos — produtos agrícolas (classificação 48)."""
    servicos = obter_servicos()
    itens = [p.para_dict() for p in servicos.producao.listar_produtos()]
    if request.args.get("agregados", "1") == "0":
        itens = [p for p in itens if not p["agregado"]]
    return jsonify({"total": len(itens), "itens": itens})


def localidades():
    """GET /api/localidades — Brasil, regiões e UFs (filtro opcional ``nivel``)."""
    servicos = obter_servicos()
    nivel = (request.args.get("nivel") or "").upper()
    if nivel and nivel not in NIVEIS_VALIDOS:
        raise ParametroInvalidoError("Nível inválido. Use N1, N2 ou N3.")
    regiao = request.args.get("regiao")
    itens = [l.para_dict() for l in servicos.producao.listar_localidades()]
    if nivel:
        itens = [l for l in itens if l["nivel"] == nivel]
    if regiao:
        itens = [l for l in itens if l["regiao_codigo"] == regiao]
    return jsonify({"total": len(itens), "itens": itens})


def periodos():
    """GET /api/periodos — meses de referência disponíveis (filtro ``ano``)."""
    servicos = obter_servicos()
    itens = [p.para_dict() for p in servicos.producao.listar_periodos()]
    ano = request.args.get("ano")
    if ano:
        if not ano.isdigit():
            raise ParametroInvalidoError("O parâmetro 'ano' deve ser numérico.")
        itens = [p for p in itens if p["ano"] == int(ano)]
    return jsonify({"total": len(itens), "itens": itens})


def indicadores():
    """GET /api/indicadores — variáveis estatísticas do LSPA."""
    servicos = obter_servicos()
    itens = [i.para_dict() for i in servicos.producao.listar_indicadores()]
    return jsonify({"total": len(itens), "itens": itens})


def dashboard():
    """GET /api/dashboard — indicadores e séries dos gráficos."""
    return jsonify(obter_servicos().dashboard.obter_dashboard(request.args))


def status():
    """GET /api/status — estatísticas do cache local."""
    return jsonify(obter_servicos().sidra.status())
