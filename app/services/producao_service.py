"""Regras de negócio da consulta de produção agrícola.

Responsável por validar filtros, transformá-los em consultas ao SIDRA,
aplicar pesquisa textual, ordenação e paginação, e gerar o CSV de exportação.
"""
from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import asdict, dataclass
from typing import Mapping

from app.exceptions import ParametroInvalidoError
from app.integrations.ibge.sidra_endpoints import (
    NIVEL_BRASIL,
    NIVEL_REGIAO,
    NIVEL_UF,
    ConsultaValores,
    Territorio,
)
from app.models import Indicador, Localidade, Periodo, Producao, Produto
from app.models.periodo_model import MESES
from app.services.sidra_service import SidraService

MES_TODOS = "todos"

COLUNAS_ORDENACAO = {
    "produto": lambda l: _normalizar(l["produto"]),
    "localidade": lambda l: (l["nivel"], _normalizar(l["localidade"])),
    "indicador": lambda l: _normalizar(l["indicador"]),
    "valor": lambda l: l["valor"],
    "unidade": lambda l: _normalizar(l["unidade"]),
    "ano": lambda l: (l["ano"], l["mes"]),
    "mes": lambda l: (l["ano"], l["mes"]),
}

URL_TABELA_SIDRA = "https://sidra.ibge.gov.br/tabela/{tabela}"


def _normalizar(texto: str | None) -> str:
    """Minúsculas e sem acentos, para pesquisa e ordenação."""
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).casefold()


def _texto(valor) -> str | None:
    if valor is None:
        return None
    valor = str(valor).strip()
    return valor or None


def _inteiro(valor, nome: str, minimo: int | None = None, maximo: int | None = None) -> int | None:
    valor = _texto(valor)
    if valor is None:
        return None
    try:
        numero = int(valor)
    except ValueError:
        raise ParametroInvalidoError(f"O parâmetro '{nome}' deve ser um número inteiro.") from None
    if (minimo is not None and numero < minimo) or (maximo is not None and numero > maximo):
        raise ParametroInvalidoError(f"O parâmetro '{nome}' está fora do intervalo permitido.")
    return numero


@dataclass
class FiltrosProducao:
    produto: str | None = None
    indicador: str | None = None
    regiao: str | None = None
    estado: str | None = None
    ano: int | None = None
    mes: int | str | None = None
    busca: str | None = None
    ordenar: str = "produto"
    direcao: str = "asc"
    pagina: int = 1
    por_pagina: int = 25

    def para_dict(self) -> dict:
        return asdict(self)


class ProducaoService:
    def __init__(self, sidra_service: SidraService, itens_por_pagina: int = 25, maximo_por_pagina: int = 200):
        self.sidra = sidra_service
        self.itens_por_pagina = itens_por_pagina
        self.maximo_por_pagina = maximo_por_pagina

    # ------------------------------------------------------------------
    # Catálogos (metadados dinâmicos do SIDRA)
    # ------------------------------------------------------------------
    def listar_produtos(self) -> list[Produto]:
        return self.sidra.obter_produtos()

    def listar_indicadores(self) -> list[Indicador]:
        return self.sidra.obter_indicadores()

    def listar_localidades(self) -> list[Localidade]:
        return self.sidra.obter_localidades()

    def listar_periodos(self) -> list[Periodo]:
        return self.sidra.obter_periodos()

    def opcoes_filtros(self) -> dict:
        """Opções para montar os filtros da interface."""
        periodos = self.listar_periodos()
        localidades = self.listar_localidades()
        anos = sorted({p.ano for p in periodos}, reverse=True)
        return {
            "produtos": [p.para_dict() for p in self.listar_produtos()],
            "indicadores": [i.para_dict() for i in self.listar_indicadores()],
            "regioes": [l.para_dict() for l in localidades if l.nivel == NIVEL_REGIAO],
            "estados": sorted(
                (l.para_dict() for l in localidades if l.nivel == NIVEL_UF), key=lambda l: _normalizar(l["nome"])
            ),
            "anos": anos,
            "meses_por_ano": {
                str(ano): [
                    {"mes": p.mes, "nome": p.mes_nome} for p in periodos if p.ano == ano
                ]
                for ano in anos
            },
            "periodo_mais_recente": periodos[-1].para_dict() if periodos else None,
            "avisos": list(self.sidra.avisos_metadados),
        }

    # ------------------------------------------------------------------
    # Validação
    # ------------------------------------------------------------------
    def validar_filtros(self, args: Mapping) -> FiltrosProducao:
        filtros = FiltrosProducao(por_pagina=self.itens_por_pagina)

        produto = _texto(args.get("produto"))
        if produto is not None:
            if produto not in {p.codigo for p in self.listar_produtos()}:
                raise ParametroInvalidoError(f"Produto agrícola inválido: {produto}.")
            filtros.produto = produto

        indicador = _texto(args.get("indicador"))
        if indicador is not None:
            chaves = {i.chave for i in self.listar_indicadores()} | {str(i.codigo) for i in self.listar_indicadores()}
            if indicador not in chaves:
                raise ParametroInvalidoError(f"Indicador inválido: {indicador}.")
            filtros.indicador = self._indicador(indicador).chave

        localidades = self.listar_localidades()
        regiao = _texto(args.get("regiao"))
        if regiao is not None:
            if regiao not in {l.codigo for l in localidades if l.nivel == NIVEL_REGIAO}:
                raise ParametroInvalidoError(f"Região inválida: {regiao}.")
            filtros.regiao = regiao

        estado = _texto(args.get("estado"))
        if estado is not None:
            uf = next((l for l in localidades if l.nivel == NIVEL_UF and l.codigo == estado), None)
            if uf is None:
                raise ParametroInvalidoError(f"Estado inválido: {estado}.")
            if filtros.regiao and uf.regiao_codigo != filtros.regiao:
                raise ParametroInvalidoError("O estado selecionado não pertence à região informada.")
            filtros.estado = estado

        periodos = self.listar_periodos()
        filtros.ano = _inteiro(args.get("ano"), "ano", 1900, 2100)
        if filtros.ano is not None and filtros.ano not in {p.ano for p in periodos}:
            raise ParametroInvalidoError(f"Não há estimativas do LSPA para o ano {filtros.ano}.")

        mes = _texto(args.get("mes"))
        if mes is not None and mes.lower() == MES_TODOS:
            if filtros.ano is None:
                raise ParametroInvalidoError("Para listar todos os meses, selecione um ano.")
            filtros.mes = MES_TODOS
        else:
            filtros.mes = _inteiro(mes, "mes", 1, 12)

        filtros.busca = (_texto(args.get("busca")) or None)
        if filtros.busca and len(filtros.busca) > 100:
            raise ParametroInvalidoError("O texto de pesquisa deve ter no máximo 100 caracteres.")

        ordenar = _texto(args.get("ordenar")) or "produto"
        if ordenar not in COLUNAS_ORDENACAO:
            raise ParametroInvalidoError(f"Coluna de ordenação inválida: {ordenar}.")
        filtros.ordenar = ordenar

        direcao = (_texto(args.get("direcao")) or "asc").lower()
        if direcao not in {"asc", "desc"}:
            raise ParametroInvalidoError("A direção de ordenação deve ser 'asc' ou 'desc'.")
        filtros.direcao = direcao

        filtros.pagina = _inteiro(args.get("pagina"), "pagina", 1) or 1
        filtros.por_pagina = (
            _inteiro(args.get("por_pagina"), "por_pagina", 1, self.maximo_por_pagina) or self.itens_por_pagina
        )
        return filtros

    def _indicador(self, chave_ou_codigo: str) -> Indicador:
        for indicador in self.listar_indicadores():
            if chave_ou_codigo in (indicador.chave, str(indicador.codigo)):
                return indicador
        raise ParametroInvalidoError(f"Indicador inválido: {chave_ou_codigo}.")

    # ------------------------------------------------------------------
    # Períodos
    # ------------------------------------------------------------------
    def resolver_periodos(self, ano: int | None, mes: int | str | None) -> list[Periodo]:
        """Converte (ano, mês) nos períodos AAAAMM disponíveis.

        * sem ano e sem mês → estimativa mais recente;
        * ano sem mês → última estimativa disponível do ano (dezembro, se fechado);
        * ano e "todos" → todas as estimativas mensais do ano;
        * mês sem ano → o mês informado no ano mais recente em que ele existe.
        """
        periodos = self.listar_periodos()
        if not periodos:
            raise ParametroInvalidoError("Nenhum período disponível no LSPA.")
        candidatos = [p for p in periodos if ano is None or p.ano == ano]
        if mes == MES_TODOS:
            return candidatos
        if mes is not None:
            candidatos = [p for p in candidatos if p.mes == mes]
            if not candidatos:
                rotulo = f"{MESES[mes].lower()} de {ano}" if ano else MESES[mes].lower()
                raise ParametroInvalidoError(f"Não há estimativa do LSPA para {rotulo}.")
        if not candidatos:
            raise ParametroInvalidoError("Período não disponível.")
        return [candidatos[-1]]

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------
    def montar_consulta(self, filtros: FiltrosProducao) -> tuple[ConsultaValores, list[Periodo]]:
        periodos = self.resolver_periodos(filtros.ano, filtros.mes)

        if filtros.estado:
            territorios = (Territorio(NIVEL_UF, (filtros.estado,)),)
        elif filtros.regiao:
            ufs = tuple(
                l.codigo for l in self.listar_localidades()
                if l.nivel == NIVEL_UF and l.regiao_codigo == filtros.regiao
            )
            territorios = (Territorio(NIVEL_REGIAO, (filtros.regiao,)), Territorio(NIVEL_UF, ufs))
        else:
            territorios = (Territorio(NIVEL_BRASIL), Territorio(NIVEL_REGIAO), Territorio(NIVEL_UF))

        if filtros.indicador:
            variaveis = (self._indicador(filtros.indicador).codigo,)
        else:
            variaveis = tuple(i.codigo for i in self.listar_indicadores())

        consulta = ConsultaValores(
            territorios=territorios,
            variaveis=variaveis,
            periodos=tuple(p.codigo for p in periodos),
            produtos=(filtros.produto,) if filtros.produto else (),
            tabela=self.sidra.tabela,
        )
        return consulta, periodos

    def _linha(self, observacao: Producao, indicadores: dict[int, Indicador]) -> dict:
        indicador = indicadores.get(observacao.variavel_codigo)
        return {
            "produto": observacao.produto_nome,
            "produto_codigo": observacao.produto_codigo,
            "localidade": observacao.localidade_nome,
            "localidade_codigo": observacao.localidade_codigo,
            "nivel": observacao.nivel,
            "indicador": indicador.nome if indicador else observacao.variavel_nome,
            "indicador_chave": indicador.chave if indicador else str(observacao.variavel_codigo),
            "valor": observacao.valor,
            "valor_exibicao": observacao.valor_exibicao,
            "simbolo": observacao.simbolo,
            "unidade": observacao.unidade,
            "ano": observacao.ano,
            "mes": observacao.mes,
            "mes_nome": MESES[observacao.mes],
            "periodo": observacao.periodo,
        }

    def _linhas_filtradas(self, filtros: FiltrosProducao):
        consulta, periodos = self.montar_consulta(filtros)
        resultado = self.sidra.obter_observacoes(consulta)
        indicadores = {i.codigo: i for i in self.listar_indicadores()}
        linhas = [self._linha(o, indicadores) for o in resultado.observacoes]

        if filtros.busca:
            termo = _normalizar(filtros.busca)
            linhas = [
                l for l in linhas
                if termo in _normalizar(" ".join((l["produto"], l["localidade"], l["indicador"], l["unidade"])))
            ]

        chave = COLUNAS_ORDENACAO[filtros.ordenar]
        reverso = filtros.direcao == "desc"
        if filtros.ordenar == "valor":
            # valores ausentes (símbolos) sempre ao final
            com_valor = sorted((l for l in linhas if l["valor"] is not None), key=chave, reverse=reverso)
            linhas = com_valor + [l for l in linhas if l["valor"] is None]
        else:
            linhas = sorted(linhas, key=lambda l: (chave(l), l["nivel"], _normalizar(l["localidade"])), reverse=reverso)
        return linhas, resultado, consulta, periodos

    def consultar(self, args: Mapping) -> dict:
        filtros = self.validar_filtros(args)
        linhas, resultado, consulta, periodos = self._linhas_filtradas(filtros)

        total = len(linhas)
        total_paginas = max(1, -(-total // filtros.por_pagina))
        pagina = min(filtros.pagina, total_paginas)
        inicio = (pagina - 1) * filtros.por_pagina

        return {
            "filtros": filtros.para_dict(),
            "periodos": [p.para_dict() for p in periodos],
            "total": total,
            "pagina": pagina,
            "por_pagina": filtros.por_pagina,
            "total_paginas": total_paginas,
            "linhas": linhas[inicio: inicio + filtros.por_pagina],
            "meta": self._meta(resultado, consulta),
        }

    def exportar_csv(self, args: Mapping) -> str:
        """CSV com todas as linhas filtradas (sem paginação), pronto para Excel pt-BR."""
        filtros = self.validar_filtros(args)
        linhas, resultado, consulta, _ = self._linhas_filtradas(filtros)

        saida = io.StringIO()
        escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
        escritor.writerow(["Produto", "Localidade", "Nível territorial", "Indicador", "Valor",
                           "Unidade de medida", "Ano", "Mês de referência"])
        for l in linhas:
            if l["valor"] is None:
                valor = l["simbolo"] or ""
            else:
                valor = (f"{l['valor']:.0f}" if float(l["valor"]).is_integer() else f"{l['valor']}").replace(".", ",")
            escritor.writerow([l["produto"], l["localidade"], l["nivel"], l["indicador"], valor,
                               l["unidade"], l["ano"], l["mes_nome"]])
        escritor.writerow([])
        escritor.writerow([f"Fonte: IBGE - Levantamento Sistemático da Produção Agrícola (LSPA), "
                           f"tabela {consulta.tabela}. Consulta: {consulta.caminho()}. "
                           f"Atualizado em: {resultado.atualizado_em or ''}"])
        return "﻿" + saida.getvalue()

    def _meta(self, resultado, consulta: ConsultaValores) -> dict:
        return {
            "origem": resultado.origem,
            "atualizado_em": resultado.atualizado_em,
            "avisos": resultado.avisos,
            "tabela": consulta.tabela,
            "consulta": consulta.caminho(),
            "fonte": "IBGE — Levantamento Sistemático da Produção Agrícola (LSPA)",
            "url_fonte": URL_TABELA_SIDRA.format(tabela=consulta.tabela),
        }
