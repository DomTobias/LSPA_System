"""Entidade Período de referência do LSPA."""
from __future__ import annotations

from dataclasses import asdict, dataclass

MESES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}
MESES_ABREV = {n: nome[:3] for n, nome in MESES.items()}


@dataclass
class Periodo:
    """Mês de referência de uma estimativa do LSPA.

    Na tabela 6588 cada período (AAAAMM) é a estimativa da safra do ano AAAA
    feita no mês MM. A estimativa de dezembro é a última do ano; estimativas
    de um mesmo ano mudam de mês para mês e podem ser revisadas pelo IBGE.

    Atributos:
        codigo: código SIDRA no formato AAAAMM.
        ano: ano da safra estimada.
        mes: mês de referência da estimativa (1–12).
        nome: rótulo publicado pelo IBGE (ex.: "setembro 2026").
        modificacao: data ISO da última modificação informada pelo IBGE.
    """

    codigo: str
    ano: int = 0
    mes: int = 0
    nome: str = ""
    modificacao: str | None = None

    def __post_init__(self):
        self.codigo = str(self.codigo)
        if not self.ano:
            self.ano = int(self.codigo[:4])
        if not self.mes:
            self.mes = int(self.codigo[4:6])
        if not self.nome:
            self.nome = f"{MESES[self.mes].lower()} {self.ano}"

    @property
    def mes_nome(self) -> str:
        return MESES[self.mes]

    @property
    def rotulo(self) -> str:
        """Rótulo curto para gráficos (ex.: "Set/2026")."""
        return f"{MESES_ABREV[self.mes]}/{self.ano}"

    def para_dict(self) -> dict:
        dados = asdict(self)
        dados["mes_nome"] = self.mes_nome
        dados["rotulo"] = self.rotulo
        return dados

    @staticmethod
    def codigo_de(ano: int, mes: int) -> str:
        return f"{int(ano):04d}{int(mes):02d}"
