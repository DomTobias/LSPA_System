"""Entidade Produto agrícola (categoria da classificação 48 do SIDRA)."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Produto:
    """Produto das lavouras pesquisado pelo LSPA.

    Atributos:
        codigo: código oficial da categoria na classificação 48.
        nome: nome sem a numeração hierárquica (ex.: "Soja").
        nome_original: nome como publicado pelo IBGE (ex.: "1.17 Soja").
        hierarquia: numeração hierárquica publicada (ex.: "1.17").
        nivel: nível hierárquico na classificação (0 = Total).
        agregado: True quando a categoria soma outras (ex.: "Total",
            "Cereais, leguminosas e oleaginosas", "Café total").
        pai_codigo: código da categoria agregadora imediata, se houver.
    """

    codigo: str
    nome: str
    nome_original: str = ""
    hierarquia: str = ""
    nivel: int = 1
    agregado: bool = False
    pai_codigo: str | None = None

    def para_dict(self) -> dict:
        return asdict(self)
