"""Entidade Localidade (Brasil, Grande Região ou Unidade da Federação)."""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Siglas oficiais das UFs, indexadas pelo código IBGE da UF.
SIGLAS_UF = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}


@dataclass
class Localidade:
    """Localidade territorial do SIDRA.

    Atributos:
        codigo: código IBGE (1 = Brasil; 1–5 = regiões; 11–53 = UFs).
        nome: nome oficial.
        nivel: nível territorial (N1, N2 ou N3).
        nivel_nome: descrição do nível.
        regiao_codigo: para UFs, código da Grande Região. Pela codificação
            oficial do IBGE, o primeiro dígito do código da UF é o código
            da sua região (ex.: 51 Mato Grosso → 5 Centro-Oeste).
        sigla: sigla da UF, quando aplicável.
    """

    codigo: str
    nome: str
    nivel: str
    nivel_nome: str = ""
    regiao_codigo: str | None = None
    sigla: str | None = None

    def __post_init__(self):
        self.codigo = str(self.codigo)
        if self.nivel == "N3":
            if not self.regiao_codigo:
                self.regiao_codigo = self.codigo[0]
            if not self.sigla:
                self.sigla = SIGLAS_UF.get(self.codigo)

    @property
    def chave(self) -> str:
        """Identificador único entre níveis (ex.: "N3-51")."""
        return f"{self.nivel}-{self.codigo}"

    @property
    def rotulo_curto(self) -> str:
        return self.sigla or self.nome

    def para_dict(self) -> dict:
        dados = asdict(self)
        dados["chave"] = self.chave
        return dados
