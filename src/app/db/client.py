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

# Gateway client + database handles are thread-local: extraction prepare runs in
# asyncio.to_thread workers while other HTTP handlers must not close_db() them.
_tls = threading.local()
_active_arango_db = threading.local()


def _tls_gateway() -> GatewayArangoClient | None:
    return getattr(_tls, "gateway_client", None)


def _set_tls_gateway(client: GatewayArangoClient | None) -> None:
    if client is None:
        if hasattr(_tls, "gateway_client"):
            delattr(_tls, "gateway_client")
    else:
        _tls.gateway_client = client


def _tls_dbs() -> dict[str, GatewayDatabase]:
    dbs = getattr(_tls, "dbs", None)
    if dbs is None:
        dbs = {}
        _tls.dbs = dbs
    return dbs


def _tls_config_signature() -> tuple[Any, ...] | None:
    return getattr(_tls, "config_signature", None)


def _set_tls_config_signature(signature: tuple[Any, ...] | None) -> None:
    if signature is None:
        if hasattr(_tls, "config_signature"):
            delattr(_tls, "config_signature")
    else:
        _tls.config_signature = signature


def _settings_signature() -> tuple[Any, ...]:
    settings = app_config.settings
    return (
        effective_gateway_url(),
        settings.arango_db,
        settings.test_deployment_mode,
    )


def _close_tls_gateway() -> None:
    client = _tls_gateway()
    if client is not None:
        client.disconnect()
    _set_tls_gateway(None)
    if hasattr(_tls, "dbs"):
        delattr(_tls, "dbs")


def _get_settings() -> Settings:
    settings = app_config.settings
    signature = _settings_signature()
    if _tls_config_signature() != signature:
        _close_tls_gateway()
        _set_tls_config_signature(signature)
    return settings


def _connect_gateway() -> GatewayArangoClient:
    base = effective_gateway_url()
    if not base:
        raise RuntimeError(
            "Arango gateway is not configured. Set ARANGO_GATEWAY_BASE_URL or publish an active row "
            "to ARANGO_GATEWAY_REGISTRY_TABLE (and DATABRICKS_SQL_WAREHOUSE_ID for UC reads)."
        )
    _get_settings()
    client = _tls_gateway()
    if client is None or not getattr(client, "_proxy_url", ""):
        cfg = workflow_config_dict()
        client = GatewayArangoClient(
            get_gateway_settings(),
            effective_base_url=base,
            auth_config=cfg,
        )
        client.connect()
        _set_tls_gateway(client)
        log.info(
            "connected to Arango via gateway",
            extra={"gateway": base, "db": app_config.settings.arango_db},
        )
    return client


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
    return app_config.settings.arango_db


def _is_duplicate_name_error(exc: BaseException) -> bool:
    if isinstance(exc, GatewayAPIError):
        if exc.error_code in (1207, 1210, 1925):
            return True
    return "duplicate name" in str(exc).lower()


def _is_missing_database_error(exc: BaseException) -> bool:
    if not isinstance(exc, GatewayAPIError):
        msg = str(exc).lower()
        return "database not found" in msg
    if exc.error_code in (1229,):
        return True
    return "database not found" in str(exc).lower()


def _is_stale_gateway_client_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "nonetype" in msg
        and "request" in msg
    ) or "not connected" in msg


def _should_auto_create_database(db_name: str) -> bool:
    """Auto-create only for per-run extraction DBs, not the legacy ``ARANGO_DB`` default."""
    settings = _get_settings()
    if db_name == settings.arango_db:
        return False
    thread_name = getattr(_active_arango_db, "name", None)
    if not thread_name or str(thread_name) != db_name:
        return False
    return settings.can_create_databases


def _ensure_database_exists(*, db_name: str | None = None) -> None:
    """Create the target user database via ``_system`` when missing (gateway mode).

    Auto-create runs only when a per-run database is pinned on the thread (extraction
    prepare). The env default ``ARANGO_DB`` (OntoExtract) is never created silently
    on startup or incidental ``get_db()`` calls.
    """
    resolved_name = db_name or effective_arango_database_name()
    if not _should_auto_create_database(resolved_name):
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
        if _is_duplicate_name_error(exc):
            return
        raise


def get_db() -> GatewayDatabase:
    client = _connect_gateway()
    db_name = effective_arango_database_name()
    _ensure_database_exists(db_name=db_name)
    dbs = _tls_dbs()
    if db_name not in dbs:
        dbs[db_name] = GatewayDatabase(client, db_name)
    else:
        dbs[db_name]._client = client
    return dbs[db_name]


def reset_gateway_session() -> None:
    """Drop this thread's gateway client and DB handles (e.g. after a stale-client error)."""
    _close_tls_gateway()


def recover_missing_arango_database() -> None:
    """Clear cached handles and recreate the active database after it was dropped."""
    db_name = effective_arango_database_name()
    log.warning(
        "Arango database missing — recreating via gateway",
        extra={"db": db_name},
    )
    _tls_dbs().pop(db_name, None)
    _ensure_database_exists(db_name=db_name)


def get_system_db() -> GatewayDatabase:
    client = _connect_gateway()
    dbs = _tls_dbs()
    if "_system" not in dbs:
        dbs["_system"] = GatewayDatabase(client, "_system")
    else:
        dbs["_system"]._client = client
    return dbs["_system"]


def close_db() -> None:
    """Close gateway resources for the current thread only."""
    _close_tls_gateway()
    _set_tls_config_signature(None)
