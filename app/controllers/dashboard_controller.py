"""Controller das páginas do dashboard."""
from __future__ import annotations

from flask import render_template, request

from app.controllers import obter_servicos


def index():
    """Página principal com indicadores e gráficos.

    Os filtros (produtos e períodos) são renderizados pelo Jinja2; os dados
    dos gráficos são carregados de forma assíncrona por ``/api/dashboard``.
    """
    servicos = obter_servicos()
    opcoes = servicos.producao.opcoes_filtros()
    produto_inicial = servicos.dashboard.produto_inicial(servicos.producao.listar_produtos())
    return render_template(
        "dashboard/index.html",
        pagina_ativa="dashboard",
        opcoes=opcoes,
        selecionado={
            "produto": request.args.get("produto") or produto_inicial.codigo,
            "ano": request.args.get("ano", ""),
            "mes": request.args.get("mes", ""),
        },
    )
