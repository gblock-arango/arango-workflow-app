"""Resolve arango-gateway-app base URL: env override, then Unity Catalog registry."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from app.workflow_platform.services.databricks_sql import execute_sql
from app.workflow_platform.services.registry_types import parse_fqn_table

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_uc_cache: dict[str, Any] = {"key": "", "value": "", "expires": 0.0}


def _row_get_ci(row: dict[str, Any], name: str) -> Any:
    """Unity Catalog / driver may return column names with varying case."""
    if name in row:
        return row[name]
    lower = name.lower()
    for k, v in row.items():
        if str(k).lower() == lower:
            return v
    return None


def get_active_gateway_base_url(table_name: str, warehouse_id: str) -> str | None:
    """Return the newest active ``base_url`` row, or None."""
    table = (table_name or "").strip()
    wid = (warehouse_id or "").strip()
    if not table or not wid:
        return None
    try:
        ref = parse_fqn_table(table)
    except ValueError:
        return None
    try:
        result = execute_sql(
            statement=f"""
                SELECT base_url
                FROM {ref.fqn}
                WHERE is_active IS TRUE
                ORDER BY updated_at DESC
                LIMIT 1
            """,
            warehouse_id=wid,
        )
    except Exception as exc:
        logger.warning("Gateway URL registry read failed (%s): %s", table, exc)
        return None
    rows: list[dict[str, Any]] = result.get("rows") or []
    if not rows:
        return None
    raw = _row_get_ci(rows[0], "base_url")
    u = (str(raw) if raw is not None else "").strip().rstrip("/")
    return u or None


def _cached_uc_gateway_base_url(cfg: Any) -> str:
    """Read UC with a short TTL when empty (wait for gateway publish) and longer when set."""
    table = str(cfg.get("ARANGO_GATEWAY_REGISTRY_TABLE") or "").strip()
    wid = str(cfg.get("DATABRICKS_SQL_WAREHOUSE_ID") or "").strip()
    if not table or not wid:
        return ""
    key = f"{table}\0{wid}"
    now = time.monotonic()
    with _lock:
        if key == _uc_cache["key"] and now < float(_uc_cache["expires"]):
            return str(_uc_cache["value"])
    uc = get_active_gateway_base_url(table, wid) or ""
    url = uc.strip().rstrip("/")
    ttl = 20.0 if not url else 300.0
    with _lock:
        _uc_cache["key"] = key
        _uc_cache["value"] = url
        _uc_cache["expires"] = now + ttl
    return url


def effective_gateway_base_url(cfg: Any) -> str:
    """
    Base URL for browser + server-side calls to arango-gateway-app.

    1. Non-empty ``ARANGO_GATEWAY_BASE_URL`` (env / ``app.yaml``) wins.
    2. Otherwise the active row in ``ARANGO_GATEWAY_REGISTRY_TABLE`` (cached briefly).
    """
    explicit = (cfg.get("ARANGO_GATEWAY_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    return _cached_uc_gateway_base_url(cfg)


def effective_gateway_iframe_base_url(cfg: Any) -> str:
    """
    Origin used only for the Arango Web UI ``<iframe src>``.

    Defaults to the same URL as :func:`effective_gateway_base_url` (the Apps ``*.databricksapps.com``
    origin from UC). Optional ``ARANGO_GATEWAY_IFRAME_BASE_URL`` or, when explicitly enabled,
    ``ARANGO_GATEWAY_IFRAME_USE_WORKSPACE_APPS_URL`` + ``DATABRICKS_HOST`` + ``ARANGO_GATEWAY_APP_NAME``.
    """
    override = (os.environ.get("ARANGO_GATEWAY_IFRAME_BASE_URL") or "").strip().rstrip("/")
    if override:
        return override

    # Only ``{DATABRICKS_HOST}/apps/{app}`` when explicitly enabled. Default is off: Databricks
    # Apps are primarily served at ``*.databricksapps.com``; the workspace /apps/ path often
    # does not map to the same Flask app (404 / black iframe).
    v = (os.environ.get("ARANGO_GATEWAY_IFRAME_USE_WORKSPACE_APPS_URL") or "").strip().lower()
    use_workspace = v in ("1", "true", "yes")
    if use_workspace:
        host = (os.environ.get("DATABRICKS_HOST") or "").strip().rstrip("/")
        if host:
            app_name = (os.environ.get("ARANGO_GATEWAY_APP_NAME") or "arango-gateway-app").strip()
            if app_name:
                return f"{host}/apps/{app_name}"

    return effective_gateway_base_url(cfg).rstrip("/")


def resolve_dashboard_gateway_base_url(cfg: Any) -> str:
    """Alias of :func:`effective_gateway_base_url` (kept for callers / tests)."""
    return effective_gateway_base_url(cfg)


def invalidate_gateway_url_uc_cache() -> None:
    """Force the next UC read (e.g. after tests that mutate the registry table)."""
    with _lock:
        _uc_cache["expires"] = 0.0
