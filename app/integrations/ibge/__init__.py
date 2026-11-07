"""Integração com o SIDRA (IBGE): cliente HTTP, endpoints e parser."""
from app.integrations.ibge.sidra_client import SidraClient
from app.integrations.ibge.sidra_endpoints import ConsultaValores, Territorio

__all__ = ["ConsultaValores", "SidraClient", "Territorio"]
