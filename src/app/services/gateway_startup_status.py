"""Fetch and parse arango-gateway-app ``/api/debug/startup-status`` for UI readiness."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.workflow_platform.databricks_outbound_auth import outbound_databricks_auth_headers

log = logging.getLogger(__name__)


def fetch_gateway_startup_status(
    *,
    gateway_base_url: str,
    refresh: bool = False,
    timeout_sec: float = 20.0,
) -> dict[str, Any]:
    """GET gateway startup-status (same JSON as the gateway app debug endpoint)."""
    base = gateway_base_url.strip().rstrip("/")
    if not base:
        raise ValueError("Gateway base URL is empty")
    params = {"refresh": "true"} if refresh else {}
    headers = outbound_databricks_auth_headers() or None
    with httpx.Client(timeout=timeout_sec) as client:
        response = client.get(
            f"{base}/api/debug/startup-status",
            params=params,
            headers=headers,
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
    latency_ms = details.get("latency_ms")

    ok = probe_status == "ok" and registry_status == "ok"

    detail_parts: list[str] = []
    if version:
        detail_parts.append(f"Arango {version}")
    if cluster:
        detail_parts.append(cluster)
    if latency_ms is not None:
        detail_parts.append(f"{latency_ms}ms")

    summary = " · ".join(detail_parts)

    if ok:
        return {
            "status": "ready",
            "gateway": "Gateway startup-status ok",
            "database": detail_parts[0] if detail_parts else "Arango reachable",
            "detail": summary or "Connected",
            "gateway_url": gateway_base_url.rstrip("/"),
        }

    err_parts: list[str] = []
    if probe_status != "ok":
        err_parts.append(f"probe={probe_status or 'unknown'}")
    if registry_status != "ok":
        err_parts.append(f"registry={registry_status or 'unknown'}")
    message = ", ".join(err_parts) or "Gateway startup-status reported failure"
    return {
        "status": "not_ready",
        "gateway": message,
        "database": message,
        "detail": summary or message,
        "gateway_url": gateway_base_url.rstrip("/"),
    }
