"""Unity Catalog registry for arango-workflow-app public base URL (same pattern as gateway/agent)."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from databricks.sdk import WorkspaceClient

from app.workflow_platform.services.databricks_sql import execute_sql
from app.workflow_platform.services.registry_types import parse_fqn_table

logger = logging.getLogger(__name__)

_publish_lock = threading.Lock()
_uc_read_lock = threading.Lock()
_uc_read_cache: dict[str, Any] = {"key": "", "value": "", "expires": 0.0}

_DELTA_CONCURRENT_MARKERS = (
    "concurrent",
    "concurrentappend",
    "concurrentmodification",
    "concurrent_append",
    "concurrent_modification",
    "concurrent_delete_read",
    "concurrent_delete_delete",
    "concurrent_transaction",
    "concurrent_write",
)


def _looks_like_delta_concurrent_conflict(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _DELTA_CONCURRENT_MARKERS)


def _row_get_ci(row: dict[str, Any], name: str) -> Any:
    if name in row:
        return row[name]
    lower = name.lower()
    for k, v in row.items():
        if str(k).lower() == lower:
            return v
    return None


def ensure_workflow_registry_table(table_name: str, warehouse_id: str) -> None:
    ref = parse_fqn_table(table_name)
    execute_sql(
        statement=f"CREATE SCHEMA IF NOT EXISTS `{ref.catalog}`.`{ref.schema}`",
        warehouse_id=warehouse_id,
    )
    execute_sql(
        statement=f"""
            CREATE TABLE IF NOT EXISTS {ref.fqn} (
                base_url STRING NOT NULL,
                app_name STRING NOT NULL,
                is_active BOOLEAN NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            USING DELTA
        """,
        warehouse_id=warehouse_id,
    )
    try_grant_account_users_workflow_registry_dml(ref, warehouse_id)


def try_grant_account_users_workflow_registry_dml(ref: Any, warehouse_id: str) -> None:
    try:
        execute_sql(
            statement=f"GRANT SELECT, MODIFY ON TABLE {ref.fqn} TO `account users`",
            warehouse_id=warehouse_id,
        )
    except Exception as exc:
        logger.info(
            "Could not GRANT workflow URL registry to `account users` (may be disabled or not owner): %s",
            exc,
        )


def publish_workflow_base_url(
    *,
    table_name: str,
    warehouse_id: str,
    base_url: str,
    app_name: str,
    max_merge_retries: int = 8,
) -> None:
    ref = parse_fqn_table(table_name)
    url = (base_url or "").strip().rstrip("/")
    name = (app_name or "").strip()
    if not url or not name:
        return

    try_grant_account_users_workflow_registry_dml(ref, warehouse_id)
    safe_url = url.replace("'", "''")
    safe_name = name.replace("'", "''")

    merge_sql = f"""
        MERGE INTO {ref.fqn} t
        USING (
            SELECT
                '{safe_url}' AS base_url,
                '{safe_name}' AS app_name,
                current_timestamp() AS updated_at
        ) s
        ON t.base_url = s.base_url
        WHEN MATCHED THEN UPDATE SET
            app_name = s.app_name,
            is_active = TRUE,
            updated_at = s.updated_at
        WHEN NOT MATCHED THEN INSERT
            (base_url, app_name, is_active, updated_at)
            VALUES (s.base_url, s.app_name, TRUE, s.updated_at)
        WHEN NOT MATCHED BY SOURCE AND t.is_active = TRUE THEN UPDATE SET
            is_active = FALSE,
            updated_at = current_timestamp()
    """

    last_exc: Exception | None = None
    for attempt in range(1, max(1, max_merge_retries) + 1):
        try:
            execute_sql(statement=merge_sql, warehouse_id=warehouse_id)
            try_grant_account_users_workflow_registry_dml(ref, warehouse_id)
            return
        except Exception as exc:
            last_exc = exc
            if attempt >= max_merge_retries or not _looks_like_delta_concurrent_conflict(exc):
                raise
            time.sleep(0.25 * attempt)
    if last_exc is not None:
        raise last_exc


def resolve_self_app_base_url() -> str | None:
    name = (os.environ.get("DATABRICKS_APP_NAME") or "").strip()
    if not name:
        return None
    try:
        app = WorkspaceClient().apps.get(name)
        u = (getattr(app, "url", None) or "").strip().rstrip("/")
        return u or None
    except Exception as exc:
        logger.warning("Could not resolve Databricks App URL for %r: %s", name, exc)
        return None


def publish_self_workflow_url_to_uc_if_configured(cfg: dict[str, Any]) -> None:
    """On workflow startup, upsert our public URL into UC for consumers (e.g. mcp-arango-agent)."""
    auto = str(cfg.get("ARANGO_WORKFLOW_REGISTRY_AUTO_CREATE", "true")).strip().lower()
    if auto in ("0", "false", "no", "off"):
        return
    table = str(cfg.get("ARANGO_WORKFLOW_REGISTRY_TABLE") or "").strip()
    warehouse = str(cfg.get("DATABRICKS_SQL_WAREHOUSE_ID") or "").strip()
    if not table or not warehouse:
        return
    url = resolve_self_app_base_url()
    if not url:
        return
    app_name = (os.environ.get("DATABRICKS_APP_NAME") or "").strip() or "arango-workflow-app"
    try:
        with _publish_lock:
            ensure_workflow_registry_table(table_name=table, warehouse_id=warehouse)
            publish_workflow_base_url(
                table_name=table,
                warehouse_id=warehouse,
                base_url=url,
                app_name=app_name,
            )
        logger.info("Published arango-workflow-app base URL to UC table %s", table)
    except Exception as exc:
        logger.warning("Could not publish workflow URL to UC (%s): %s", table, exc)


def get_active_workflow_base_url(table_name: str, warehouse_id: str) -> str | None:
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
        logger.warning("Workflow URL registry read failed (%s): %s", table, exc)
        return None
    rows: list[dict[str, Any]] = result.get("rows") or []
    if not rows:
        return None
    raw = _row_get_ci(rows[0], "base_url")
    u = (str(raw) if raw is not None else "").strip().rstrip("/")
    return u or None


def _cached_uc_workflow_base_url(cfg: Any) -> str:
    table = str(cfg.get("ARANGO_WORKFLOW_REGISTRY_TABLE") or "").strip()
    wid = str(cfg.get("DATABRICKS_SQL_WAREHOUSE_ID") or "").strip()
    if not table or not wid:
        return ""
    key = f"{table}\0{wid}"
    now = time.monotonic()
    with _uc_read_lock:
        if key == _uc_read_cache["key"] and now < float(_uc_read_cache["expires"]):
            return str(_uc_read_cache["value"])
    uc = get_active_workflow_base_url(table, wid) or ""
    url = uc.strip().rstrip("/")
    ttl = 20.0 if not url else 300.0
    with _uc_read_lock:
        _uc_read_cache["key"] = key
        _uc_read_cache["value"] = url
        _uc_read_cache["expires"] = now + ttl
    return url


def effective_workflow_base_url(cfg: Any) -> str:
    """
    Base URL for HTTP calls to arango-workflow-app.

    1. Non-empty ``ARANGO_WORKFLOW_APP_BASE_URL`` wins.
    2. Otherwise the active row in ``ARANGO_WORKFLOW_REGISTRY_TABLE`` (cached briefly).
    """
    explicit = (cfg.get("ARANGO_WORKFLOW_APP_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    return _cached_uc_workflow_base_url(cfg)


def invalidate_workflow_url_uc_cache() -> None:
    with _uc_read_lock:
        _uc_read_cache["expires"] = 0.0
