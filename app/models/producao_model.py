"""Entidades de produção agrícola: Indicador e Producao (observação)."""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Símbolos especiais publicados pelo IBGE no lugar de valores numéricos.
SIMBOLOS_SIDRA = {
    "-": "Zero absoluto, não resultante de arredondamento",
    "..": "Não se aplica dado numérico",
    "...": "Dado numérico não disponível",
    "X": "Valor inibido para não identificar o informante",
}


@dataclass
class Indicador:
    """Variável estatística do LSPA (produção, áreas, rendimento)."""

    codigo: int
    chave: str
    nome: str
    unidade: str
    somavel: bool = True  # rendimento médio não pode ser somado

    def para_dict(self) -> dict:
        return asdict(self)


@dataclass
class Producao:
    """Uma observação da tabela LSPA: um valor de um indicador para um
    produto, numa localidade, num mês de referência.

    A chave natural é (tabela, periodo, nivel, localidade_codigo,
    produto_codigo, variavel_codigo). O valor pode mudar quando o IBGE
    revisa estimativas, por isso a persistência faz *upsert*.
    """

    tabela: int
    periodo: str
    nivel: str
    localidade_codigo: str
    localidade_nome: str
    produto_codigo: str
    produto_nome: str
    variavel_codigo: int
    variavel_nome: str
    unidade: str
    valor: float | None
    simbolo: str | None = None
    atualizado_em: str | None = None

    @property
    def ano(self) -> int:
        return int(self.periodo[:4])

    @property
    def mes(self) -> int:
        return int(self.periodo[4:6])

    @property
    def chave_natural(self) -> tuple:
        return (
            self.tabela, self.periodo, self.nivel, self.localidade_codigo,
            self.produto_codigo, self.variavel_codigo,
        )

    @property
    def valor_exibicao(self) -> str:
        """Valor formatado para exibição ou o símbolo publicado pelo IBGE."""
        if self.valor is None:
            return self.simbolo or "..."
        if float(self.valor).is_integer():
            return f"{int(self.valor):,}".replace(",", ".")
        return f"{self.valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def para_dict(self) -> dict:
        dados = asdict(self)
        dados["ano"] = self.ano
        dados["mes"] = self.mes
        return dados
