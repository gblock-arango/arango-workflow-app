import asyncio
import time
from typing import Any

from fastapi import APIRouter

from app.db.gateway_connectivity import gateway_connectivity_status

router = APIRouter(tags=["system"])

_ready_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_READY_CACHE_TTL_SEC = 45.0


def invalidate_ready_cache() -> None:
    """Clear cached ``/ready`` payload (for tests)."""
    _ready_cache["at"] = 0.0
    _ready_cache["payload"] = None


def _arango_version_label(version: str | None) -> str:
    if version:
        return f"Arango {version}"
    return "Arango cluster reachable"


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


def _ready_sync() -> dict[str, Any]:
    """
    Readiness for the home-page "Connection to Arango" widget.

    Uses a single gateway connect (``GET /_api/version`` via the proxy) instead of
    a separate ``GET /health`` plus ``get_db().version()`` plus database ensure —
    that stacked 3–4 round trips and could take 30–45s on cold start.

    Runs in a worker thread so sync gateway HTTP does not block other routes.
    """
    now = time.monotonic()
    cached = _ready_cache.get("payload")
    if (
        cached is not None
        and now - float(_ready_cache.get("at") or 0.0) < _READY_CACHE_TTL_SEC
    ):
        return dict(cached)

    from app.db.client import _connect_gateway
    from app.db.gateway_config import effective_gateway_url

    base = effective_gateway_url()
    if not base:
        payload = {
            "status": "not_ready",
            "gateway": (
                "Arango gateway is not configured. Set ARANGO_GATEWAY_BASE_URL or publish an "
                "active row to ARANGO_GATEWAY_REGISTRY_TABLE."
            ),
            "database": "Gateway URL not configured",
            "gateway_url": "",
        }
        _ready_cache["at"] = now
        _ready_cache["payload"] = payload
        return payload

    try:
        client = _connect_gateway()
        payload = {
            "status": "ready",
            "gateway": "Gateway reachable",
            "database": _arango_version_label(client.server_version),
            "gateway_url": base,
        }
    except Exception as exc:
        gw = gateway_connectivity_status()
        gateway_msg = gw["gateway_message"] if not gw["gateway_ok"] else str(exc)
        payload = {
            "status": "not_ready",
            "gateway": gateway_msg,
            "database": gateway_msg,
            "gateway_url": gw.get("gateway_url") or base,
        }

    _ready_cache["at"] = now
    _ready_cache["payload"] = payload
    return payload


@router.get("/ready")
async def ready() -> dict[str, Any]:
    return await asyncio.to_thread(_ready_sync)


async def warm_ready_cache() -> None:
    """Populate ``/ready`` cache at startup so the home page avoids a cold probe."""
    await asyncio.to_thread(_ready_sync)
