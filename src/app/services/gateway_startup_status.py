"""Fetch and parse arango-gateway-app ``/api/debug/startup-status`` for UI readiness."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.workflow_platform.databricks_outbound_auth import outbound_databricks_auth_headers

log = logging.getLogger(__name__)


async def fetch_gateway_startup_status_async(
    *,
    gateway_base_url: str,
    refresh: bool = False,
    timeout_sec: float = 25.0,
    auth_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """GET gateway startup-status (async; pass auth from the request handler thread)."""
    base = gateway_base_url.strip().rstrip("/")
    if not base:
        raise ValueError("Gateway base URL is empty")
    params = {"refresh": "true"} if refresh else {}
    headers = (
        auth_headers
        if auth_headers is not None
        else outbound_databricks_auth_headers(peer_url=base)
    )
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        response = await client.get(
            f"{base}/api/debug/startup-status",
            params=params,
            headers=headers or None,
        )
    if not response.is_success:
        preview = (response.text or "")[:800]
        raise RuntimeError(
            f"Gateway startup-status HTTP {response.status_code}: {preview or response.reason_phrase}"
        )
    return response.json() if response.content else {}


def fetch_gateway_startup_status(
    *,
    gateway_base_url: str,
    refresh: bool = False,
    timeout_sec: float = 25.0,
    auth_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Sync wrapper for tests and scripts."""
    base = gateway_base_url.strip().rstrip("/")
    if not base:
        raise ValueError("Gateway base URL is empty")
    params = {"refresh": "true"} if refresh else {}
    headers = (
        auth_headers
        if auth_headers is not None
        else outbound_databricks_auth_headers(peer_url=base)
    )
    with httpx.Client(timeout=timeout_sec) as client:
        response = client.get(
            f"{base}/api/debug/startup-status",
            params=params,
            headers=headers or None,
        )
    if not response.is_success:
        preview = (response.text or "")[:800]
        raise RuntimeError(
            f"Gateway startup-status HTTP {response.status_code}: {preview or response.reason_phrase}"
        )
    return response.json() if response.content else {}


def ready_payload_from_startup_status(
    payload: dict[str, Any],
    *,
    gateway_base_url: str,
) -> dict[str, Any]:
    """
    Map gateway startup-status JSON to the ``/ready`` widget shape.

    Connected when ``probe.status`` and ``registry.status`` are both ``ok``.
    """
    from app.services.arango_connection_profiles import connection_ui_for_ready

    probe = payload.get("probe") if isinstance(payload.get("probe"), dict) else {}
    registry = payload.get("registry") if isinstance(payload.get("registry"), dict) else {}
    probe_status = str(probe.get("status") or "")
    registry_status = str(registry.get("status") or "")

    details = probe.get("details") if isinstance(probe.get("details"), dict) else {}

    version: str | None = None
    preview = details.get("response_preview")
    if isinstance(preview, str) and preview.strip():
        try:
            parsed = json.loads(preview)
            if isinstance(parsed, dict):
                version = str(parsed.get("version") or "") or None
        except json.JSONDecodeError:
            log.debug("Could not parse probe response_preview as JSON")

    cluster = str(registry.get("cluster_name") or "")

    ok = probe_status == "ok" and registry_status == "ok"
    connection = connection_ui_for_ready(probe_ok=ok, registry_ok=ok)

    detail_parts: list[str] = []
    if ok and connection.get("active_profile_display_name"):
        detail_parts.append(str(connection["active_profile_display_name"]))
    if version:
        detail_parts.append(f"Arango {version}")
    elif cluster and cluster not in detail_parts:
        detail_parts.append(cluster)

    summary = " · ".join(detail_parts)

    base_payload = {
        "connection": connection,
        "gateway_url": gateway_base_url.rstrip("/"),
    }

    if ok:
        return {
            **base_payload,
            "status": "ready",
            "gateway": "Gateway startup-status ok",
            "database": detail_parts[0] if detail_parts else "Arango reachable",
            "detail": summary or str(connection.get("ui_message") or "Connected"),
        }

    ui_message = str(connection.get("ui_message") or "Connection Failed")
    return {
        **base_payload,
        "status": "not_ready",
        "gateway": ui_message,
        "database": ui_message,
        "detail": ui_message,
    }
