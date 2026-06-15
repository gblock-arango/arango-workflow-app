"""Arango connectivity for the home-page widget — UC registry + direct probe (no gateway HTTP)."""

from __future__ import annotations

import base64
import json
import logging
import os
import ssl
import time
from datetime import datetime, timezone
from typing import Any
from urllib import error, request

from app.workflow_platform.runtime import workflow_config_dict
from app.workflow_platform.services.databricks_sql import execute_sql
from app.workflow_platform.services.registry_types import parse_fqn_table

log = logging.getLogger(__name__)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_get_ci(row: dict[str, Any], name: str) -> Any:
    if name in row:
        return row[name]
    lower = name.lower()
    for k, v in row.items():
        if str(k).lower() == lower:
            return v
    return None


def _preview_json_or_text(raw_text: str) -> str:
    text = raw_text.strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, separators=(",", ":"), sort_keys=True)[:512]
    except Exception:
        return text[:512]


def ping_arango_endpoint(
    *,
    protocol: str,
    ip_address: str,
    port: int,
    path: str = "/_api/version",
    timeout_seconds: float = 5.0,
    basic_auth_user: str | None = None,
    basic_auth_password: str | None = None,
    verify_tls: bool = True,
) -> dict[str, Any]:
    """Probe Arango ``/_api/version`` (same contract as arango-gateway-app)."""
    normalized_path = path if path.startswith("/") else f"/{path}"
    url = f"{protocol}://{ip_address}:{port}{normalized_path}"

    started = time.perf_counter()
    req = request.Request(url=url, method="GET")
    req.add_header("Accept", "application/json")
    if basic_auth_user:
        password = basic_auth_password if basic_auth_password is not None else ""
        token = base64.b64encode(f"{basic_auth_user}:{password}".encode("utf-8")).decode("ascii")
        req.add_header("Authorization", f"Basic {token}")

    ssl_ctx: ssl.SSLContext | None = None
    if protocol == "https" and not verify_tls:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        open_kw: dict[str, Any] = {"timeout": timeout_seconds}
        if ssl_ctx is not None:
            open_kw["context"] = ssl_ctx
        with request.urlopen(req, **open_kw) as resp:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            body_text = resp.read(2048).decode("utf-8", errors="replace")
            return {
                "reachable": True,
                "url": url,
                "status_code": resp.getcode(),
                "latency_ms": elapsed_ms,
                "response_preview": _preview_json_or_text(body_text),
            }
    except error.HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        body_text = exc.read(2048).decode("utf-8", errors="replace")
        return {
            "reachable": False,
            "url": url,
            "status_code": exc.code,
            "latency_ms": elapsed_ms,
            "error": f"HTTP error: {exc.reason}",
            "response_preview": _preview_json_or_text(body_text),
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "reachable": False,
            "url": url,
            "latency_ms": elapsed_ms,
            "error": str(exc),
        }


def _get_active_registry_row(table_name: str, warehouse_id: str) -> dict[str, Any] | None:
    ref = parse_fqn_table(table_name)
    result = execute_sql(
        statement=f"""
            SELECT cluster_name, ip_address, port, protocol, is_active, updated_at
            FROM {ref.fqn}
            WHERE is_active IS TRUE
            ORDER BY updated_at DESC
            LIMIT 1
        """,
        warehouse_id=warehouse_id,
    )
    rows = result.get("rows") or []
    return rows[0] if rows else None


def fetch_arango_startup_status() -> dict[str, Any]:
    """
    Build gateway-compatible startup-status JSON for the home-page widget.

    In ``local_dev``, reads gateway ``/api/debug/startup-status`` so /ready matches
    the same registry + auth path as extraction (AWS / GCS / Minikube).

    In cloud, reads UC ``ARANGO_REGISTRY_TABLE`` and probes Arango directly (no
    gateway HTTP — avoids Apps peer 401).
    """
    from app.workflow_platform.deployment_profile import is_local_dev, local_gateway_base_url

    if is_local_dev():
        return _fetch_gateway_startup_status(local_gateway_base_url())

    return _fetch_uc_registry_startup_status()


def _fetch_gateway_startup_status(gateway_base_url: str) -> dict[str, Any]:
    import httpx

    from app.services.arango_connection_profiles import get_connection_ui_context

    base = gateway_base_url.strip().rstrip("/")
    connection_ctx: dict[str, Any] = {}
    try:
        connection_ctx = get_connection_ui_context()
    except Exception as exc:
        log.debug("connection ui context unavailable: %s", exc)

    try:
        with httpx.Client(timeout=25.0) as client:
            response = client.get(f"{base}/api/debug/startup-status", params={"refresh": "true"})
        response.raise_for_status()
        payload = response.json() if response.content else {}
    except Exception as exc:
        log.warning("gateway startup-status failed: %s", exc)
        return {
            "checked_at": _now_utc(),
            "registry": {"status": "error", "error": str(exc)},
            "probe": {"status": "error", "error": str(exc)},
            "connection": connection_ctx,
            "source": "gateway_startup_status",
            "gateway_url": base,
        }

    if not isinstance(payload, dict):
        payload = {}
    payload["connection"] = connection_ctx
    payload["source"] = "gateway_startup_status"
    payload["gateway_url"] = base
    return payload


def _fetch_uc_registry_startup_status() -> dict[str, Any]:
    """Direct UC registry probe (cloud default)."""
    cfg = workflow_config_dict()
    table_name = (cfg.get("ARANGO_REGISTRY_TABLE") or "").strip()
    warehouse_id = (cfg.get("DATABRICKS_SQL_WAREHOUSE_ID") or "").strip()
    timeout_seconds = float(os.environ.get("ARANGO_PING_TIMEOUT_SECONDS", "5"))
    auth_user, auth_password = None, None
    connection_ctx: dict[str, Any] = {}
    try:
        from app.services.arango_connection_profiles import get_active_profile_auth, get_connection_ui_context

        auth_user, auth_password = get_active_profile_auth()
        connection_ctx = get_connection_ui_context()
    except Exception as exc:
        log.debug("active profile auth unavailable: %s", exc)
    verify_tls = (os.environ.get("ARANGO_PING_TLS_VERIFY", "true").strip().lower() != "false")

    status: dict[str, Any] = {
        "checked_at": _now_utc(),
        "registry_table": table_name,
        "warehouse_id_present": bool(warehouse_id),
        "secrets": {
            "source": "uc_connection_profile" if auth_user else "missing",
            "auth_user_present": bool(auth_user),
            "auth_password_present": bool(auth_password),
            "active_profile": connection_ctx.get("active_profile") or "",
        },
        "connection": connection_ctx,
        "registry": {"status": "unknown"},
        "probe": {"status": "skipped"},
        "source": "uc_registry_direct",
    }

    if not table_name or not warehouse_id:
        status["registry"] = {
            "status": "error",
            "error": "ARANGO_REGISTRY_TABLE and DATABRICKS_SQL_WAREHOUSE_ID are required",
        }
        return status

    try:
        row = _get_active_registry_row(table_name, warehouse_id)
        if not row:
            status["registry"] = {"status": "empty", "message": "No active row found"}
            return status

        protocol = str(_row_get_ci(row, "protocol") or "https").lower()
        ip_address = str(_row_get_ci(row, "ip_address") or "")
        port = int(_row_get_ci(row, "port") or 443)
        cluster_name = str(_row_get_ci(row, "cluster_name") or "")

        status["registry"] = {
            "status": "ok",
            "cluster_name": cluster_name,
            "ip_address": ip_address,
            "port": str(port),
            "protocol": protocol,
        }

        if not ip_address:
            status["probe"] = {"status": "error", "error": "registry row missing ip_address"}
            return status

        probe = ping_arango_endpoint(
            protocol=protocol,
            ip_address=ip_address,
            port=port,
            timeout_seconds=timeout_seconds,
            basic_auth_user=auth_user or None,
            basic_auth_password=auth_password if auth_user else None,
            verify_tls=verify_tls,
        )
        status["probe"] = {
            "status": "ok" if probe.get("reachable") else "unreachable",
            "details": probe,
        }
    except Exception as exc:
        log.warning("arango connectivity check failed: %s", exc)
        status["registry"] = {"status": "error", "error": str(exc)}
        status["probe"] = {"status": "error", "error": str(exc)}

    return status
