"""Controller da página de consulta de produção."""
from __future__ import annotations

from flask import render_template, request

from app.controllers import obter_servicos

FILTROS_PAGINA = ("produto", "indicador", "regiao", "estado", "ano", "mes", "busca")


def index():
    """Página de consulta com filtros, tabela, paginação e exportação CSV.

    Os valores dos filtros vindos da URL são devolvidos ao template apenas
    para pré-seleção; a validação acontece no service ao chamar a API.
    """
    servicos = obter_servicos()
    return render_template(
        "producao/index.html",
        pagina_ativa="producao",
        opcoes=servicos.producao.opcoes_filtros(),
        selecionado={chave: request.args.get(chave, "") for chave in FILTROS_PAGINA},
    )
