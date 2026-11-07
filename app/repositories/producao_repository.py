"""Repositório de persistência local dos dados do LSPA.

Responsável apenas por gravar e recuperar dados no banco. Não contém regras
de negócio (validação de filtros, validade do cache, cálculos) — isso fica
nos services. Todas as consultas usam parâmetros (``?``), nunca concatenação
de valores, o que impede SQL Injection.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Iterable, Sequence

from app.models import Indicador, Localidade, Periodo, Producao, Produto
from database.connection import Database


def _agora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _marcadores(quantidade: int) -> str:
    return ",".join("?" * quantidade)


class ProducaoRepository:
    def __init__(self, banco: Database, relogio: Callable[[], str] = _agora_utc):
        self.banco = banco
        self._agora = relogio

    # ------------------------------------------------------------------
    # Consultas realizadas (log + controle de cache)
    # ------------------------------------------------------------------
    def registrar_consulta(
        self,
        tipo: str,
        tabela: int,
        caminho: str,
        parametros: dict | None = None,
        registros: int = 0,
        sucesso: bool = True,
        mensagem: str | None = None,
    ) -> int:
        """Insere ou atualiza o registro da consulta e retorna o seu id."""
        agora = self._agora()
        parametros_json = json.dumps(parametros or {}, ensure_ascii=False, sort_keys=True)
        with self.banco.conexao() as con:
            if sucesso:
                con.execute(
                    """
                    INSERT INTO consultas
                        (tipo, tabela, caminho, parametros, registros, status, mensagem,
                         execucoes, criada_em, executada_em)
                    VALUES (?, ?, ?, ?, ?, 'sucesso', ?, 1, ?, ?)
                    ON CONFLICT(caminho) DO UPDATE SET
                        registros = excluded.registros,
                        status = 'sucesso',
                        mensagem = excluded.mensagem,
                        execucoes = consultas.execucoes + 1,
                        executada_em = excluded.executada_em
                    """,
                    (tipo, tabela, caminho, parametros_json, registros, mensagem, agora, agora),
                )
            else:
                con.execute(
                    """
                    INSERT INTO consultas
                        (tipo, tabela, caminho, parametros, registros, status, mensagem,
                         execucoes, criada_em, executada_em)
                    VALUES (?, ?, ?, ?, 0, 'erro', ?, 1, ?, NULL)
                    ON CONFLICT(caminho) DO UPDATE SET
                        status = 'erro',
                        mensagem = excluded.mensagem,
                        execucoes = consultas.execucoes + 1
                    """,
                    (tipo, tabela, caminho, parametros_json, mensagem, agora),
                )
            linha = con.execute("SELECT id FROM consultas WHERE caminho = ?", (caminho,)).fetchone()
        return int(linha["id"])

    def obter_consulta(self, caminho: str) -> dict | None:
        with self.banco.conexao() as con:
            linha = con.execute("SELECT * FROM consultas WHERE caminho = ?", (caminho,)).fetchone()
        return dict(linha) if linha else None

    def listar_consultas(self, limite: int = 50) -> list[dict]:
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT * FROM consultas ORDER BY COALESCE(executada_em, criada_em) DESC LIMIT ?",
                (int(limite),),
            ).fetchall()
        return [dict(l) for l in linhas]

    # ------------------------------------------------------------------
    # Metadados
    # ------------------------------------------------------------------
    def salvar_produtos(self, tabela: int, produtos: Sequence[Produto]) -> None:
        agora = self._agora()
        with self.banco.conexao() as con:
            con.executemany(
                """
                INSERT INTO produtos
                    (tabela, codigo, nome, nome_original, hierarquia, nivel, agregado,
                     pai_codigo, ordem, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tabela, codigo) DO UPDATE SET
                    nome = excluded.nome, nome_original = excluded.nome_original,
                    hierarquia = excluded.hierarquia, nivel = excluded.nivel,
                    agregado = excluded.agregado, pai_codigo = excluded.pai_codigo,
                    ordem = excluded.ordem, atualizado_em = excluded.atualizado_em
                """,
                [
                    (tabela, p.codigo, p.nome, p.nome_original, p.hierarquia, p.nivel,
                     int(p.agregado), p.pai_codigo, ordem, agora)
                    for ordem, p in enumerate(produtos)
                ],
            )

    def listar_produtos(self, tabela: int) -> list[Produto]:
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT * FROM produtos WHERE tabela = ? ORDER BY ordem", (tabela,)
            ).fetchall()
        return [
            Produto(
                codigo=l["codigo"], nome=l["nome"], nome_original=l["nome_original"] or "",
                hierarquia=l["hierarquia"] or "", nivel=l["nivel"], agregado=bool(l["agregado"]),
                pai_codigo=l["pai_codigo"],
            )
            for l in linhas
        ]

    def salvar_indicadores(self, tabela: int, indicadores: Sequence[Indicador]) -> None:
        agora = self._agora()
        with self.banco.conexao() as con:
            con.executemany(
                """
                INSERT INTO indicadores (tabela, codigo, chave, nome, unidade, somavel, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tabela, codigo) DO UPDATE SET
                    chave = excluded.chave, nome = excluded.nome, unidade = excluded.unidade,
                    somavel = excluded.somavel, atualizado_em = excluded.atualizado_em
                """,
                [(tabela, i.codigo, i.chave, i.nome, i.unidade, int(i.somavel), agora) for i in indicadores],
            )

    def listar_indicadores(self, tabela: int) -> list[Indicador]:
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT * FROM indicadores WHERE tabela = ? ORDER BY rowid", (tabela,)
            ).fetchall()
        return [
            Indicador(codigo=l["codigo"], chave=l["chave"], nome=l["nome"],
                      unidade=l["unidade"] or "", somavel=bool(l["somavel"]))
            for l in linhas
        ]

    def salvar_localidades(self, localidades: Sequence[Localidade]) -> None:
        agora = self._agora()
        with self.banco.conexao() as con:
            con.executemany(
                """
                INSERT INTO localidades (nivel, codigo, nome, nivel_nome, regiao_codigo, sigla, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(nivel, codigo) DO UPDATE SET
                    nome = excluded.nome, nivel_nome = excluded.nivel_nome,
                    regiao_codigo = excluded.regiao_codigo, sigla = excluded.sigla,
                    atualizado_em = excluded.atualizado_em
                """,
                [(l.nivel, l.codigo, l.nome, l.nivel_nome, l.regiao_codigo, l.sigla, agora) for l in localidades],
            )

    def listar_localidades(self) -> list[Localidade]:
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT * FROM localidades ORDER BY nivel, CAST(codigo AS INTEGER)"
            ).fetchall()
        return [
            Localidade(codigo=l["codigo"], nome=l["nome"], nivel=l["nivel"],
                       nivel_nome=l["nivel_nome"] or "", regiao_codigo=l["regiao_codigo"], sigla=l["sigla"])
            for l in linhas
        ]

    def salvar_periodos(self, tabela: int, periodos: Sequence[Periodo]) -> None:
        agora = self._agora()
        with self.banco.conexao() as con:
            con.executemany(
                """
                INSERT INTO periodos (tabela, codigo, ano, mes, nome, modificacao, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tabela, codigo) DO UPDATE SET
                    nome = excluded.nome, modificacao = excluded.modificacao,
                    atualizado_em = excluded.atualizado_em
                """,
                [(tabela, p.codigo, p.ano, p.mes, p.nome, p.modificacao, agora) for p in periodos],
            )

    def listar_periodos(self, tabela: int) -> list[Periodo]:
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT * FROM periodos WHERE tabela = ? ORDER BY codigo", (tabela,)
            ).fetchall()
        return [
            Periodo(codigo=l["codigo"], ano=l["ano"], mes=l["mes"], nome=l["nome"] or "",
                    modificacao=l["modificacao"])
            for l in linhas
        ]

    # ------------------------------------------------------------------
    # Observações de produção
    # ------------------------------------------------------------------
    def salvar_producao(self, observacoes: Iterable[Producao], consulta_id: int | None) -> int:
        """Grava as observações com *upsert*.

        Registros já existentes (mesma chave natural) são atualizados; quando
        o valor muda (revisão do IBGE) a versão é incrementada e o valor
        anterior fica registrado em ``producao_revisoes`` (via trigger).
        """
        agora = self._agora()
        parametros = [
            (o.tabela, o.periodo, o.ano, o.mes, o.nivel, o.localidade_codigo, o.localidade_nome,
             o.produto_codigo, o.produto_nome, o.variavel_codigo, o.variavel_nome, o.unidade,
             o.valor, o.simbolo, consulta_id, agora, agora)
            for o in observacoes
        ]
        if not parametros:
            return 0
        with self.banco.conexao() as con:
            con.executemany(
                """
                INSERT INTO producao
                    (tabela, periodo, ano, mes, nivel, localidade_codigo, localidade_nome,
                     produto_codigo, produto_nome, variavel_codigo, variavel_nome, unidade,
                     valor, simbolo, consulta_id, criado_em, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tabela, periodo, nivel, localidade_codigo, produto_codigo, variavel_codigo)
                DO UPDATE SET
                    versao = CASE
                        WHEN producao.valor IS NOT excluded.valor
                          OR producao.simbolo IS NOT excluded.simbolo
                        THEN producao.versao + 1 ELSE producao.versao END,
                    valor = excluded.valor,
                    simbolo = excluded.simbolo,
                    localidade_nome = excluded.localidade_nome,
                    produto_nome = excluded.produto_nome,
                    variavel_nome = excluded.variavel_nome,
                    unidade = excluded.unidade,
                    consulta_id = excluded.consulta_id,
                    atualizado_em = excluded.atualizado_em
                """,
                parametros,
            )
        return len(parametros)

    def buscar_producao(
        self,
        tabela: int,
        territorios: Sequence[tuple[str, Sequence[str]]],
        variaveis: Sequence[int],
        periodos: Sequence[str],
        produtos: Sequence[str] = (),
    ) -> list[Producao]:
        """Recupera observações. Listas vazias de localidades/produtos = todas."""
        if not territorios or not variaveis or not periodos:
            return []

        condicoes = [
            "tabela = ?",
            f"variavel_codigo IN ({_marcadores(len(variaveis))})",
            f"periodo IN ({_marcadores(len(periodos))})",
        ]
        valores: list = [tabela, *variaveis, *periodos]
        if produtos:
            condicoes.append(f"produto_codigo IN ({_marcadores(len(produtos))})")
            valores.extend(produtos)

        filtros_territorio = []
        for nivel, codigos in territorios:
            if codigos:
                filtros_territorio.append(f"(nivel = ? AND localidade_codigo IN ({_marcadores(len(codigos))}))")
                valores.extend([nivel, *codigos])
            else:
                filtros_territorio.append("(nivel = ?)")
                valores.append(nivel)
        condicoes.append("(" + " OR ".join(filtros_territorio) + ")")

        sql = (
            "SELECT * FROM producao WHERE " + " AND ".join(condicoes)
            + " ORDER BY periodo, nivel, CAST(localidade_codigo AS INTEGER), produto_codigo, variavel_codigo"
        )
        with self.banco.conexao() as con:
            linhas = con.execute(sql, valores).fetchall()
        return [self._linha_para_producao(l) for l in linhas]

    def listar_revisoes(self, limite: int = 100) -> list[dict]:
        with self.banco.conexao() as con:
            linhas = con.execute(
                """
                SELECT r.*, p.periodo, p.localidade_nome, p.produto_nome, p.variavel_nome
                FROM producao_revisoes r JOIN producao p ON p.id = r.producao_id
                ORDER BY r.id DESC LIMIT ?
                """,
                (int(limite),),
            ).fetchall()
        return [dict(l) for l in linhas]

    def estatisticas(self) -> dict:
        with self.banco.conexao() as con:
            linha = con.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM producao) AS observacoes,
                    (SELECT COUNT(*) FROM consultas WHERE tipo = 'valores') AS consultas,
                    (SELECT COUNT(*) FROM producao_revisoes) AS revisoes,
                    (SELECT MAX(executada_em) FROM consultas) AS ultima_atualizacao
                """
            ).fetchone()
        return dict(linha)

    @staticmethod
    def _linha_para_producao(linha) -> Producao:
        return Producao(
            tabela=linha["tabela"], periodo=linha["periodo"], nivel=linha["nivel"],
            localidade_codigo=linha["localidade_codigo"], localidade_nome=linha["localidade_nome"] or "",
            produto_codigo=linha["produto_codigo"], produto_nome=linha["produto_nome"] or "",
            variavel_codigo=linha["variavel_codigo"], variavel_nome=linha["variavel_nome"] or "",
            unidade=linha["unidade"] or "", valor=linha["valor"], simbolo=linha["simbolo"],
            atualizado_em=linha["atualizado_em"],
        )
