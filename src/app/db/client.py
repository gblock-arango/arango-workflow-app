"""Arango access via ``arango-gateway-app`` only (no ``python-arango``)."""

from __future__ import annotations

import logging
from typing import Any

import app.config as app_config
from app.config import Settings
from app.db.gateway_arango_client import GatewayArangoClient
from app.db.gateway_config import effective_gateway_url, get_gateway_settings
from app.db.gateway_database import GatewayDatabase
from app.workflow_platform.runtime import workflow_config_dict

log = logging.getLogger(__name__)

_gateway_client: GatewayArangoClient | None = None
_dbs: dict[str, GatewayDatabase] = {}
_config_signature: tuple[Any, ...] | None = None


def _settings_signature() -> tuple[Any, ...]:
    settings = app_config.settings
    return (
        effective_gateway_url(),
        settings.arango_db,
        settings.test_deployment_mode,
    )


def _get_settings() -> Settings:
    global _config_signature
    settings = app_config.settings
    signature = _settings_signature()
    if _config_signature != signature:
        close_db()
        _config_signature = signature
    return settings


def _connect_gateway() -> GatewayArangoClient:
    global _gateway_client
    base = effective_gateway_url()
    if not base:
        raise RuntimeError(
            "Arango gateway is not configured. Set ARANGO_GATEWAY_BASE_URL or publish an active row "
            "to ARANGO_GATEWAY_REGISTRY_TABLE (and DATABRICKS_SQL_WAREHOUSE_ID for UC reads)."
        )
    if _gateway_client is None:
        cfg = workflow_config_dict()
        _gateway_client = GatewayArangoClient(
            get_gateway_settings(),
            effective_base_url=base,
            auth_config=cfg,
        )
        _gateway_client.connect()
        log.info(
            "connected to Arango via gateway",
            extra={"gateway": base, "db": _get_settings().arango_db},
        )
    return _gateway_client


def get_db() -> GatewayDatabase:
    global _dbs
    settings = _get_settings()
    client = _connect_gateway()
    if settings.arango_db not in _dbs:
        _dbs[settings.arango_db] = GatewayDatabase(client, settings.arango_db)
    return _dbs[settings.arango_db]


def get_system_db() -> GatewayDatabase:
    client = _connect_gateway()
    if "_system" not in _dbs:
        _dbs["_system"] = GatewayDatabase(client, "_system")
    return _dbs["_system"]


def close_db() -> None:
    global _gateway_client, _dbs, _config_signature
    if _gateway_client is not None:
        _gateway_client.disconnect()
    _gateway_client = None
    _dbs = {}
    _config_signature = None
