"""Probe arango-gateway-app reachability (``GET /health``) before Arango REST via proxy."""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
from collections.abc import Callable
from typing import Any
from urllib import error, request

from app.db.gateway_config import get_gateway_settings
from app.workflow_platform.databricks_outbound_auth import outbound_databricks_auth_headers

logger = logging.getLogger(__name__)


def _health_probe_timeout_seconds() -> float:
    settings = get_gateway_settings()
    health_timeout = float(os.environ.get("ARANGO_GATEWAY_HEALTH_TIMEOUT_SECONDS", "30"))
    return min(float(settings.timeout_seconds), max(2.0, health_timeout))


def _health_probe_retries() -> int:
    return max(1, int(os.environ.get("ARANGO_GATEWAY_HEALTH_PROBE_RETRIES", "2")))


def _health_probe_retry_delay_seconds() -> float:
    return max(0.0, float(os.environ.get("ARANGO_GATEWAY_HEALTH_RETRY_DELAY_SECONDS", "2")))


def _is_transient_health_failure(message: str) -> bool:
    lower = message.lower()
    return (
        "timed out" in lower
        or "timeout" in lower
        or "temporarily unavailable" in lower
        or "connection reset" in lower
    )


def _probe_gateway_health_once(base_url: str) -> tuple[bool, str]:
    """Single ``GET /health`` attempt using outbound Databricks auth (M2M or user)."""
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
    open_kw: dict[str, Any] = {"timeout": _health_probe_timeout_seconds()}
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


def probe_gateway_health(
    base_url: str,
    *,
    on_attempt: Callable[[int, int, str], None] | None = None,
) -> tuple[bool, str]:
    """
    Return ``(ok, message)`` for ``GET {base_url}/health``.

    Retries transient timeouts — gateway workers can queue ``/health`` behind long
    Arango proxy calls (especially right after a gateway or workflow redeploy).
    """
    attempts = _health_probe_retries()
    delay = _health_probe_retry_delay_seconds()
    last_msg = "unknown"
    for attempt in range(1, attempts + 1):
        if on_attempt is not None:
            on_attempt(attempt, attempts, "probing")
        ok, msg = _probe_gateway_health_once(base_url)
        if ok:
            if attempt > 1:
                return True, f"Gateway reachable (attempt {attempt}/{attempts})"
            return True, msg
        last_msg = msg
        if attempt < attempts and _is_transient_health_failure(msg):
            logger.info(
                "Gateway /health attempt %s/%s failed (%s); retrying in %.1fs",
                attempt,
                attempts,
                msg,
                delay,
            )
            if delay > 0:
                time.sleep(delay)
            continue
        break
    return False, last_msg


def gateway_connectivity_status(
    *,
    on_health_attempt: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
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

    ok, msg = probe_gateway_health(base, on_attempt=on_health_attempt)
    return {
        "gateway_url": base,
        "gateway_ok": ok,
        "gateway_message": msg,
    }
