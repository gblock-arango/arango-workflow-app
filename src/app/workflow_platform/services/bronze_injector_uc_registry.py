"""Resolve bronze simulated injector base URL and UC registry row (for dashboard + jobs)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.workflow_platform.services.databricks_sql import execute_sql
from app.workflow_platform.services.registry_types import parse_fqn_table

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_uc_cache: dict[str, Any] = {"key": "", "value": None, "expires": 0.0}


def _row_get_ci(row: dict[str, Any], name: str) -> Any:
    if name in row:
        return row[name]
    lower = name.lower()
    for k, v in row.items():
        if str(k).lower() == lower:
            return v
    return None


def get_active_injector_registry_row(
    table_name: str, warehouse_id: str
) -> dict[str, Any] | None:
    """Single active row from ``arango_bronze_simulated_injector_registry`` (is_active = true)."""
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
                SELECT
                    base_url,
                    app_name,
                    is_active,
                    status,
                    playback_status,
                    dataset_key,
                    status_detail,
                    updated_at
                FROM {ref.fqn}
                WHERE is_active IS TRUE
                ORDER BY updated_at DESC
                LIMIT 1
            """,
            warehouse_id=wid,
        )
    except Exception as exc:
        logger.warning("Bronze injector registry read failed (%s): %s", table, exc)
        return None
    rows: list[dict[str, Any]] = result.get("rows") or []
    return rows[0] if rows else None


def _cached_injector_row(cfg: Any) -> dict[str, Any] | None:
    table = str(cfg.get("ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE") or "").strip()
    wid = str(cfg.get("DATABRICKS_SQL_WAREHOUSE_ID") or "").strip()
    if not table or not wid:
        return None
    key = f"{table}\0{wid}"
    now = time.monotonic()
    with _lock:
        if key == _uc_cache["key"] and now < float(_uc_cache["expires"]):
            return _uc_cache["value"]
    row = get_active_injector_registry_row(table, wid)
    ttl = 20.0 if not row else 300.0
    with _lock:
        _uc_cache["key"] = key
        _uc_cache["value"] = row
        _uc_cache["expires"] = now + ttl
    return row


def effective_bronze_injector_base_url(cfg: Any) -> str:
    """
    Injector HTTPS base URL (no trailing slash).

    1. ``BRONZE_INJECTOR_BASE_URL`` wins when set.
    2. Otherwise ``base_url`` from the active UC registry row (cached briefly).
    """
    explicit = (cfg.get("BRONZE_INJECTOR_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    row = _cached_injector_row(cfg)
    if not row:
        return ""
    raw = _row_get_ci(row, "base_url")
    return (str(raw) if raw is not None else "").strip().rstrip("/")


def invalidate_bronze_injector_uc_cache() -> None:
    with _lock:
        _uc_cache["expires"] = 0.0


def effective_injector_uc_snapshot(cfg: Any) -> dict[str, Any]:
    """Handy JSON for dashboards: resolved URL + UC status fields."""
    url = effective_bronze_injector_base_url(cfg)
    from_env = bool((cfg.get("BRONZE_INJECTOR_BASE_URL") or "").strip())
    row = _cached_injector_row(cfg)
    return {
        "bronze_injector_base_url_effective": url or None,
        "bronze_injector_base_url_from_env_override": from_env,
        "bronze_injector_uc_registry_active_row": row,
        "bronze_injector_uc_registry_table": (
            (cfg.get("ARANGO_BRONZE_SIMULATED_INJECTOR_REGISTRY_TABLE") or "").strip()
        ),
    }
