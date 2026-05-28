import asyncio
import time
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter(tags=["system"])

_ready_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_READY_CACHE_TTL_SEC = 45.0


def invalidate_ready_cache() -> None:
    """Clear cached ``/ready`` payload (for tests)."""
    _ready_cache["at"] = 0.0
    _ready_cache["payload"] = None


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


def _ready_sync(*, force: bool = False) -> dict[str, Any]:
    """
    Readiness for the home-page "Connection to Arango" widget.

    Calls ``{gateway}/api/debug/startup-status`` (with ``refresh=true`` when
    ``force``) and treats the gateway as healthy when ``probe.status`` and
    ``registry.status`` are both ``ok``.
    """
    now = time.monotonic()
    if not force:
        cached = _ready_cache.get("payload")
        if (
            cached is not None
            and now - float(_ready_cache.get("at") or 0.0) < _READY_CACHE_TTL_SEC
        ):
            return dict(cached)

    from app.db.gateway_config import effective_gateway_url
    from app.services.gateway_startup_status import (
        fetch_gateway_startup_status,
        ready_payload_from_startup_status,
    )

    base = effective_gateway_url()
    if not base:
        payload = {
            "status": "not_ready",
            "gateway": (
                "Arango gateway is not configured. Set ARANGO_GATEWAY_BASE_URL or publish an "
                "active row to ARANGO_GATEWAY_REGISTRY_TABLE."
            ),
            "database": "Gateway URL not configured",
            "detail": "Gateway URL not configured",
            "gateway_url": "",
        }
        _ready_cache["at"] = now
        _ready_cache["payload"] = payload
        return payload

    try:
        startup = fetch_gateway_startup_status(gateway_base_url=base, refresh=force)
        payload = ready_payload_from_startup_status(startup, gateway_base_url=base)
    except Exception as exc:
        payload = {
            "status": "not_ready",
            "gateway": f"Gateway startup-status failed: {exc}",
            "database": str(exc),
            "detail": str(exc),
            "gateway_url": base,
        }

    _ready_cache["at"] = now
    _ready_cache["payload"] = payload
    return payload


@router.get("/ready")
async def ready(
    refresh: bool = Query(
        default=False,
        description="When true, bypass cache and call gateway startup-status?refresh=true.",
    ),
) -> dict[str, Any]:
    if refresh:
        invalidate_ready_cache()
    return await asyncio.to_thread(_ready_sync, force=refresh)


async def warm_ready_cache() -> None:
    """Populate ``/ready`` cache at startup so the home page avoids a cold probe."""
    await asyncio.to_thread(_ready_sync)
