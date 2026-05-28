import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter(tags=["system"])
log = logging.getLogger(__name__)

_ready_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_READY_CACHE_TTL_SEC = 120.0
_READY_STALE_SERVE_SEC = 600.0
_refresh_task: asyncio.Task[None] | None = None


def invalidate_ready_cache() -> None:
    """Clear cached ``/ready`` payload (for tests)."""
    _ready_cache["at"] = 0.0
    _ready_cache["payload"] = None


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


def _schedule_background_refresh() -> None:
    """Refresh gateway probe without blocking the current ``/ready`` response."""
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return

    async def _run() -> None:
        try:
            await _ready_async(force=True)
        except Exception as exc:
            log.warning("background /ready refresh failed: %s", exc)

    _refresh_task = asyncio.create_task(_run())


async def _ready_async(*, force: bool = False) -> dict[str, Any]:
    """
    Readiness for the home-page "Connection to Arango" widget.

    Reads ``ARANGO_REGISTRY_TABLE`` and probes Arango ``/_api/version`` directly
    (no HTTP call to arango-gateway-app — avoids Apps peer 401). Runs in a worker
    thread so the asyncio loop stays responsive.
    """
    now = time.monotonic()
    if not force:
        cached = _ready_cache.get("payload")
        cache_at = float(_ready_cache.get("at") or 0.0)
        if cached is not None:
            age = now - cache_at
            if age < _READY_CACHE_TTL_SEC:
                return dict(cached)
            if age < _READY_STALE_SERVE_SEC:
                _schedule_background_refresh()
                stale = dict(cached)
                stale["stale"] = True
                return stale

    from app.services.arango_connectivity import fetch_arango_startup_status
    from app.services.gateway_startup_status import ready_payload_from_startup_status

    try:
        startup = await asyncio.to_thread(fetch_arango_startup_status)
        payload = ready_payload_from_startup_status(startup, gateway_base_url="")
        payload["check"] = "uc_registry_direct"
    except Exception as exc:
        cached = _ready_cache.get("payload")
        cache_at = float(_ready_cache.get("at") or 0.0)
        if cached is not None and now - cache_at < _READY_STALE_SERVE_SEC:
            log.warning("arango connectivity check failed; serving stale /ready: %s", exc)
            stale = dict(cached)
            stale["stale"] = True
            stale["refresh_error"] = str(exc)
            return stale
        payload = {
            "status": "not_ready",
            "gateway": f"Arango connectivity check failed: {exc}",
            "database": str(exc),
            "detail": str(exc),
            "gateway_url": "",
            "check": "uc_registry_direct",
        }

    _ready_cache["at"] = now
    _ready_cache["payload"] = payload
    return payload


def _ready_sync(*, force: bool = False) -> dict[str, Any]:
    """Sync entry for tests; production uses :func:`_ready_async`."""
    return asyncio.run(_ready_async(force=force))


@router.get("/ready")
async def ready(
    refresh: bool = Query(
        default=False,
        description="When true, bypass cache and re-run the UC registry + Arango probe.",
    ),
) -> dict[str, Any]:
    if refresh:
        return await _ready_async(force=True)
    return await _ready_async(force=False)


@router.get("/ready/auth-diagnostics")
async def ready_auth_diagnostics() -> dict[str, Any]:
    """Why peer-app calls may 401 — for ops (gateway/agent still need User authorization)."""
    from app.workflow_platform.databricks_outbound_auth import outbound_auth_diagnostics

    return await asyncio.to_thread(outbound_auth_diagnostics)


async def warm_ready_cache() -> None:
    """Populate ``/ready`` at startup (fresh gateway probe) for fast home-page loads."""
    await _ready_async(force=True)
