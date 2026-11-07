"""Processamento dos indicadores e séries do dashboard.

O dashboard é montado com apenas três consultas ao SIDRA (todas em cache):

1. Brasil, todas as variáveis, produto selecionado, vários períodos
   → cards de indicadores, variações e evolução (anual e mensal);
2. Regiões + UFs, produção, produto selecionado, período e mesmo mês do
   ano anterior → produção por estado, ranking e comparação entre períodos;
3. Brasil, produção, todos os produtos, período e ano anterior
   → comparação entre produtos agrícolas.
"""
from __future__ import annotations

from typing import Mapping

from app.exceptions import ParametroInvalidoError
from app.integrations.ibge.sidra_endpoints import (
    NIVEL_BRASIL,
    NIVEL_REGIAO,
    NIVEL_UF,
    VARIAVEL_PRODUCAO,
    ConsultaValores,
    Territorio,
)
from app.models import Localidade, Periodo, Producao, Produto
from app.services.producao_service import ProducaoService, _inteiro, _texto
from app.services.sidra_service import ORIGEM_API, ORIGEM_CACHE, ResultadoConsulta, SidraService

ANOS_EVOLUCAO = 10
MESES_EVOLUCAO = 24
TOP_PRODUTOS = 12
TOP_RANKING = 10


def variacao_percentual(atual: float | None, anterior: float | None) -> float | None:
    """Variação percentual entre dois valores; None quando não calculável."""
    if atual is None or anterior is None or anterior == 0:
        return None
    return round((atual - anterior) / abs(anterior) * 100, 2)


def participacao_percentual(parte: float | None, total: float | None) -> float | None:
    if parte is None or not total:
        return None
    return round(parte / total * 100, 2)


class DashboardService:
    def __init__(self, sidra_service: SidraService, producao_service: ProducaoService, produto_padrao: str | None = None):
        self.sidra = sidra_service
        self.producao = producao_service
        self.produto_padrao = produto_padrao

    # ------------------------------------------------------------------
    # Seleção de produto e período
    # ------------------------------------------------------------------
    def produto_inicial(self, produtos: list[Produto]) -> Produto:
        """Produto exibido quando nenhum é escolhido.

        Usa ``DASHBOARD_PRODUTO_PADRAO`` se configurado; senão, a primeira
        categoria agregada de nível 1 da classificação de produtos — no LSPA,
        "Cereais, leguminosas e oleaginosas", o principal indicador da safra
        divulgado pelo IBGE. Não há produto fixo no código.
        """
        if self.produto_padrao:
            for produto in produtos:
                if produto.codigo == self.produto_padrao:
                    return produto
        for produto in produtos:
            if produto.agregado and produto.nivel == 1:
                return produto
        candidatos = [p for p in produtos if p.nivel > 0]
        if not candidatos:
            raise ParametroInvalidoError("Nenhum produto disponível no LSPA.")
        return candidatos[0]

    def _selecionar(self, args: Mapping) -> tuple[Produto, Periodo, list[Periodo]]:
        produtos = self.producao.listar_produtos()
        codigo = _texto(args.get("produto"))
        if codigo is None:
            produto = self.produto_inicial(produtos)
        else:
            produto = next((p for p in produtos if p.codigo == codigo), None)
            if produto is None:
                raise ParametroInvalidoError(f"Produto agrícola inválido: {codigo}.")

        periodos = self.producao.listar_periodos()
        ano = _inteiro(args.get("ano"), "ano", 1900, 2100)
        mes = _inteiro(args.get("mes"), "mes", 1, 12)
        if ano is not None and ano not in {p.ano for p in periodos}:
            raise ParametroInvalidoError(f"Não há estimativas do LSPA para o ano {ano}.")
        periodo = self.producao.resolver_periodos(ano, mes)[0]
        return produto, periodo, periodos

    @staticmethod
    def _buscar_periodo(periodos: list[Periodo], ano: int, mes: int) -> Periodo | None:
        codigo = Periodo.codigo_de(ano, mes)
        return next((p for p in periodos if p.codigo == codigo), None)

    @staticmethod
    def periodos_evolucao_anual(periodos: list[Periodo], selecionado: Periodo, anos: int = ANOS_EVOLUCAO) -> list[Periodo]:
        """Uma estimativa por ano: a última de cada ano anterior (dezembro,
        estimativa final) e a selecionada para o ano corrente."""
        ultimos: dict[int, Periodo] = {}
        for periodo in periodos:
            if periodo.codigo <= selecionado.codigo:
                ultimos[periodo.ano] = periodo
        ultimos[selecionado.ano] = selecionado
        return [ultimos[a] for a in sorted(ultimos)][-anos:]

    @staticmethod
    def periodos_evolucao_mensal(periodos: list[Periodo], selecionado: Periodo, meses: int = MESES_EVOLUCAO) -> list[Periodo]:
        return [p for p in periodos if p.codigo <= selecionado.codigo][-meses:]

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------
    def obter_dashboard(self, args: Mapping) -> dict:
        produto, periodo, periodos = self._selecionar(args)
        anterior_ano = self._buscar_periodo(periodos, periodo.ano - 1, periodo.mes)
        mes_anterior = next((p for p in reversed(periodos) if p.codigo < periodo.codigo), None)
        evolucao_anual = self.periodos_evolucao_anual(periodos, periodo)
        evolucao_mensal = self.periodos_evolucao_mensal(periodos, periodo)
        comparacao = [p for p in (anterior_ano, periodo) if p]
        indicadores = self.producao.listar_indicadores()
        localidades = self.producao.listar_localidades()

        # Consulta 1 — Brasil, todas as variáveis
        periodos_brasil = {p.codigo for p in evolucao_anual + evolucao_mensal + comparacao}
        if mes_anterior:
            periodos_brasil.add(mes_anterior.codigo)
        r_brasil = self.sidra.obter_observacoes(ConsultaValores(
            territorios=(Territorio(NIVEL_BRASIL),),
            variaveis=tuple(i.codigo for i in indicadores),
            periodos=tuple(periodos_brasil),
            produtos=(produto.codigo,),
            tabela=self.sidra.tabela,
        ))
        # Consulta 2 — regiões e UFs, produção
        r_territorios = self.sidra.obter_observacoes(ConsultaValores(
            territorios=(Territorio(NIVEL_REGIAO), Territorio(NIVEL_UF)),
            variaveis=(VARIAVEL_PRODUCAO,),
            periodos=tuple(p.codigo for p in comparacao),
            produtos=(produto.codigo,),
            tabela=self.sidra.tabela,
        ))
        # Consulta 3 — todos os produtos, Brasil, produção
        r_produtos = self.sidra.obter_observacoes(ConsultaValores(
            territorios=(Territorio(NIVEL_BRASIL),),
            variaveis=(VARIAVEL_PRODUCAO,),
            periodos=tuple(p.codigo for p in comparacao),
            tabela=self.sidra.tabela,
        ))

        brasil = self._indexar(r_brasil.observacoes)
        territorio = self._indexar(r_territorios.observacoes)
        produtos_obs = self._indexar(r_produtos.observacoes)
        valor_brasil = lambda var, per: self._valor(brasil, per, NIVEL_BRASIL, "1", produto.codigo, var)

        kpis = []
        for indicador in indicadores:
            atual = brasil.get((periodo.codigo, NIVEL_BRASIL, "1", produto.codigo, indicador.codigo))
            valor = atual.valor if atual else None
            kpis.append({
                **indicador.para_dict(),
                "valor": valor,
                "simbolo": atual.simbolo if atual else None,
                "unidade": (atual.unidade if atual and atual.unidade else indicador.unidade),
                "variacao_anual": variacao_percentual(valor, valor_brasil(indicador.codigo, anterior_ano.codigo) if anterior_ano else None),
                "variacao_mensal": variacao_percentual(valor, valor_brasil(indicador.codigo, mes_anterior.codigo) if mes_anterior else None),
            })

        unidade_producao = next((k["unidade"] for k in kpis if k["codigo"] == VARIAVEL_PRODUCAO), "Toneladas")
        total_brasil = valor_brasil(VARIAVEL_PRODUCAO, periodo.codigo)

        def serie(lista: list[Periodo]) -> dict:
            return {
                "rotulos": [p.rotulo if lista is evolucao_mensal else str(p.ano) for p in lista],
                "periodos": [p.codigo for p in lista],
                "descricoes": [p.nome for p in lista],
                "producao": [valor_brasil(VARIAVEL_PRODUCAO, p.codigo) for p in lista],
                "area_plantada": [valor_brasil(self._codigo(indicadores, "area_plantada"), p.codigo) for p in lista],
                "area_colhida": [valor_brasil(self._codigo(indicadores, "area_colhida"), p.codigo) for p in lista],
                "rendimento_medio": [valor_brasil(self._codigo(indicadores, "rendimento_medio"), p.codigo) for p in lista],
            }

        ufs = [l for l in localidades if l.nivel == NIVEL_UF]
        regioes = [l for l in localidades if l.nivel == NIVEL_REGIAO]

        return {
            "produto": produto.para_dict(),
            "periodo": periodo.para_dict(),
            "periodo_ano_anterior": anterior_ano.para_dict() if anterior_ano else None,
            "periodo_mes_anterior": mes_anterior.para_dict() if mes_anterior else None,
            "kpis": kpis,
            "evolucao": {"anual": serie(evolucao_anual), "mensal": serie(evolucao_mensal)},
            "estados": self._por_estado(territorio, ufs, produto, periodo, unidade_producao),
            "ranking": self._ranking(territorio, ufs, produto, periodo, anterior_ano, total_brasil),
            "produtos": self._comparacao_produtos(produtos_obs, periodo, anterior_ano, produto, unidade_producao),
            "regioes": self._comparacao_regioes(territorio, regioes, produto, periodo, anterior_ano, unidade_producao),
            "meta": self._meta([r_brasil, r_territorios, r_produtos]),
        }

    # ------------------------------------------------------------------
    # Blocos
    # ------------------------------------------------------------------
    def _por_estado(self, idx, ufs: list[Localidade], produto: Produto, periodo: Periodo, unidade: str) -> dict:
        itens = []
        for uf in sorted(ufs, key=lambda u: int(u.codigo)):
            valor = self._valor(idx, periodo.codigo, NIVEL_UF, uf.codigo, produto.codigo, VARIAVEL_PRODUCAO)
            itens.append({"codigo": uf.codigo, "sigla": uf.rotulo_curto, "nome": uf.nome,
                          "regiao": uf.regiao_codigo, "valor": valor})
        return {"itens": itens, "unidade": unidade}

    def _ranking(self, idx, ufs, produto, periodo, anterior_ano, total_brasil) -> list[dict]:
        itens = []
        for uf in ufs:
            valor = self._valor(idx, periodo.codigo, NIVEL_UF, uf.codigo, produto.codigo, VARIAVEL_PRODUCAO)
            if not valor:
                continue
            anterior = (
                self._valor(idx, anterior_ano.codigo, NIVEL_UF, uf.codigo, produto.codigo, VARIAVEL_PRODUCAO)
                if anterior_ano else None
            )
            itens.append({
                "codigo": uf.codigo, "nome": uf.nome, "sigla": uf.rotulo_curto, "valor": valor,
                "participacao": participacao_percentual(valor, total_brasil),
                "variacao_anual": variacao_percentual(valor, anterior),
            })
        itens.sort(key=lambda i: i["valor"], reverse=True)
        for posicao, item in enumerate(itens, start=1):
            item["posicao"] = posicao
        return itens[:TOP_RANKING]

    def _comparacao_produtos(self, idx, periodo, anterior_ano, selecionado: Produto, unidade: str) -> dict:
        produtos = [p for p in self.producao.listar_produtos() if not p.agregado]
        itens = []
        for produto in produtos:
            valor = self._valor(idx, periodo.codigo, NIVEL_BRASIL, "1", produto.codigo, VARIAVEL_PRODUCAO)
            if not valor:
                continue
            anterior = (
                self._valor(idx, anterior_ano.codigo, NIVEL_BRASIL, "1", produto.codigo, VARIAVEL_PRODUCAO)
                if anterior_ano else None
            )
            itens.append({"codigo": produto.codigo, "nome": produto.nome, "valor": valor, "anterior": anterior,
                          "variacao_anual": variacao_percentual(valor, anterior),
                          "selecionado": produto.codigo == selecionado.codigo})
        itens.sort(key=lambda i: i["valor"], reverse=True)
        return {"itens": itens[:TOP_PRODUTOS], "total_produtos": len(itens), "unidade": unidade}

    def _comparacao_regioes(self, idx, regioes, produto, periodo, anterior_ano, unidade: str) -> dict:
        itens = []
        for regiao in sorted(regioes, key=lambda r: int(r.codigo)):
            atual = self._valor(idx, periodo.codigo, NIVEL_REGIAO, regiao.codigo, produto.codigo, VARIAVEL_PRODUCAO)
            anterior = (
                self._valor(idx, anterior_ano.codigo, NIVEL_REGIAO, regiao.codigo, produto.codigo, VARIAVEL_PRODUCAO)
                if anterior_ano else None
            )
            itens.append({"codigo": regiao.codigo, "nome": regiao.nome, "atual": atual, "anterior": anterior,
                          "variacao_anual": variacao_percentual(atual, anterior)})
        return {
            "itens": itens,
            "rotulo_atual": periodo.rotulo,
            "rotulo_anterior": anterior_ano.rotulo if anterior_ano else None,
            "unidade": unidade,
        }

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------
    @staticmethod
    def _indexar(observacoes: list[Producao]) -> dict:
        return {
            (o.periodo, o.nivel, o.localidade_codigo, o.produto_codigo, o.variavel_codigo): o
            for o in observacoes
        }

    @staticmethod
    def _valor(idx: dict, periodo: str, nivel: str, localidade: str, produto: str, variavel: int | None) -> float | None:
        observacao = idx.get((periodo, nivel, localidade, produto, variavel))
        return observacao.valor if observacao else None

    @staticmethod
    def _codigo(indicadores, chave: str) -> int | None:
        return next((i.codigo for i in indicadores if i.chave == chave), None)

    def _meta(self, resultados: list[ResultadoConsulta]) -> dict:
        origens = {r.origem for r in resultados}
        if origens == {ORIGEM_CACHE}:
            origem = ORIGEM_CACHE
        elif origens <= {ORIGEM_API, ORIGEM_CACHE}:
            origem = ORIGEM_API
        else:
            origem = "cache_expirado"
        avisos = list(dict.fromkeys(a for r in resultados for a in r.avisos))
        datas = [r.atualizado_em for r in resultados if r.atualizado_em]
        return {
            "origem": origem,
            "atualizado_em": min(datas) if datas else None,
            "avisos": avisos,
            "tabela": self.sidra.tabela,
            "consultas": [r.caminho for r in resultados],
            "fonte": "IBGE — Levantamento Sistemático da Produção Agrícola (LSPA)",
            "url_fonte": f"https://sidra.ibge.gov.br/tabela/{self.sidra.tabela}",
        }
