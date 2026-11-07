"""Controllers: recebem as requisições e delegam aos services.

Os controllers não fazem chamadas HTTP ao SIDRA, não executam SQL e não
contêm regras de negócio — apenas leem parâmetros, chamam o service
apropriado e escolhem o formato da resposta (template, JSON ou CSV).
"""
from flask import current_app


def obter_servicos():
    """Retorna o contêiner de services criado em ``create_app``."""
    return current_app.extensions["lspa"]
