"""Probe arango-gateway-app reachability (``GET /health``) before Arango REST via proxy."""

from __future__ import annotations

import json
import logging
import ssl
from typing import Any
from urllib import error, request

from app.db.gateway_config import get_gateway_settings
from app.workflow_platform.databricks_outbound_auth import outbound_databricks_auth_headers

logger = logging.getLogger(__name__)


def probe_gateway_health(base_url: str) -> tuple[bool, str]:
    """
    Return ``(ok, message)`` for ``GET {base_url}/health``.

    Uses the same outbound Databricks auth as :class:`GatewayArangoClient`.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return False, "Gateway URL is not configured"

    url = f"{base}/health"
    headers = {
        "Accept": "application/json",
        **outbound_databricks_auth_headers(),
    }
    settings = get_gateway_settings()
    ssl_ctx: ssl.SSLContext | None = None
    if url.lower().startswith("https:") and not settings.tls_verify:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    req = request.Request(url=url, method="GET", headers=headers)
    open_kw: dict[str, Any] = {"timeout": min(float(settings.timeout_seconds), 30.0)}
    if ssl_ctx is not None:
        open_kw["context"] = ssl_ctx

    try:
        with request.urlopen(req, **open_kw) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            if resp.status != 200:
                return False, f"Gateway health HTTP {resp.status}"
            try:
                body = json.loads(text) if text.strip() else {}
            except json.JSONDecodeError:
                body = {}
            status = str((body or {}).get("status", "")).lower()
            if status == "ok":
                return True, "Gateway reachable"
            return False, f"Gateway health unexpected body: {text[:120]}"
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        logger.warning("Gateway health probe failed %s: HTTP %s %s", url, exc.code, detail)
        return False, f"Gateway health HTTP {exc.code}"
    except Exception as exc:
        logger.warning("Gateway health probe failed %s: %s", url, exc)
        return False, str(exc)


def gateway_connectivity_status() -> dict[str, Any]:
    """
    Resolve gateway URL and probe ``/health``.

    Returns keys: ``gateway_url``, ``gateway_ok``, ``gateway_message``.
    """
    from app.db.gateway_config import effective_gateway_url

    base = effective_gateway_url()
    if not base:
        return {
            "gateway_url": "",
            "gateway_ok": False,
            "gateway_message": (
                "Arango gateway is not configured. Set ARANGO_GATEWAY_BASE_URL or publish an "
                "active row to ARANGO_GATEWAY_REGISTRY_TABLE (and DATABRICKS_SQL_WAREHOUSE_ID)."
            ),
        }

    ok, msg = probe_gateway_health(base)
    return {
        "gateway_url": base,
        "gateway_ok": ok,
        "gateway_message": msg,
    }
