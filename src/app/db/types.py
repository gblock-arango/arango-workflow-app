"""Arango DB types — gateway-backed only (no ``python-arango``)."""

from app.db.gateway_database import (
    GatewayAPIError,
    GatewayCollection,
    GatewayCursor,
    GatewayDatabase,
)

# Back-compat alias used across OntoExtract code paths during migration.
StandardDatabase = GatewayDatabase
Cursor = GatewayCursor

__all__ = [
    "Cursor",
    "GatewayAPIError",
    "GatewayCollection",
    "GatewayCursor",
    "GatewayDatabase",
    "StandardDatabase",
]
