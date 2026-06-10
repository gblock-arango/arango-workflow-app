"""Arango access via ``arango-gateway-app`` only (no ``python-arango``)."""

from __future__ import annotations

import logging
import threading
from typing import Any

import app.config as app_config
from app.config import Settings
from app.db.gateway_arango_client import GatewayArangoClient
from app.db.gateway_config import effective_gateway_url, get_gateway_settings
from app.db.gateway_database import GatewayAPIError, GatewayDatabase
from app.workflow_platform.runtime import workflow_config_dict

log = logging.getLogger(__name__)

_gateway_client: GatewayArangoClient | None = None
_dbs: dict[str, GatewayDatabase] = {}
_config_signature: tuple[Any, ...] | None = None
_active_arango_db = threading.local()


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


def set_active_arango_database(name: str | None) -> None:
    """Pin the logical database for this worker thread (per extraction run)."""
    if name:
        _active_arango_db.name = name
    else:
        clear_active_arango_database()


def clear_active_arango_database() -> None:
    if hasattr(_active_arango_db, "name"):
        del _active_arango_db.name


def effective_arango_database_name() -> str:
    """Per-run override from the prepare thread, else ``ARANGO_DB`` env default."""
    thread_name = getattr(_active_arango_db, "name", None)
    if thread_name:
        return str(thread_name)
    return _get_settings().arango_db


def _is_missing_database_error(exc: BaseException) -> bool:
    if not isinstance(exc, GatewayAPIError):
        msg = str(exc).lower()
        return "database not found" in msg
    if exc.error_code in (1229,):
        return True
    return "database not found" in str(exc).lower()


def _ensure_database_exists(*, db_name: str | None = None) -> None:
    """Create the target user database via ``_system`` when missing (gateway mode).

    Always re-checks ``has_database`` so a DB dropped in the Arango UI is
    recreated on the next extraction run.

    Skipped on managed platforms where ``_system`` access is restricted.
    """
    settings = _get_settings()
    resolved_name = db_name or effective_arango_database_name()
    if not settings.can_create_databases:
        log.info(
            "skipping auto-create database on managed platform — database must be pre-provisioned",
            extra={"db": resolved_name, "mode": settings.test_deployment_mode.value},
        )
        return

    sys_db = get_system_db()
    try:
        if sys_db.has_database(resolved_name):
            return
    except GatewayAPIError:
        log.warning("could not list Arango databases via gateway", exc_info=True)

    log.info("creating Arango database via gateway", extra={"db": resolved_name})
    try:
        sys_db.create_database(resolved_name)
    except GatewayAPIError as exc:
        # 1207: duplicate database name (race with another worker)
        if exc.error_code == 1207:
            return
        raise


def get_db() -> GatewayDatabase:
    global _dbs
    client = _connect_gateway()
    db_name = effective_arango_database_name()
    _ensure_database_exists(db_name=db_name)
    if db_name not in _dbs:
        _dbs[db_name] = GatewayDatabase(client, db_name)
    return _dbs[db_name]


def recover_missing_arango_database() -> None:
    """Clear cached handles and recreate the active database after it was dropped."""
    global _dbs
    db_name = effective_arango_database_name()
    log.warning(
        "Arango database missing — recreating via gateway",
        extra={"db": db_name},
    )
    _dbs.pop(db_name, None)
    _ensure_database_exists(db_name=db_name)


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
    clear_active_arango_database()
