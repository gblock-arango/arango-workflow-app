import asyncio
import time
from typing import Any

from fastapi import APIRouter

from app.db.client import get_db
from app.db.gateway_connectivity import gateway_connectivity_status

router = APIRouter(tags=["system"])

_ready_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_READY_CACHE_TTL_SEC = 12.0


def invalidate_ready_cache() -> None:
    """Clear cached ``/ready`` payload (for tests)."""
    _ready_cache["at"] = 0.0
    _ready_cache["payload"] = None


def _arango_version_label(version_body: Any) -> str:
    if isinstance(version_body, dict):
        ver = version_body.get("version")
        if ver:
            return f"Arango {ver}"
    return "Arango cluster reachable"


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


def _ready_sync() -> dict[str, Any]:
    """
    Readiness for the home-page "Connection to Arango" widget.

    Runs in a worker thread so sync gateway HTTP + Arango proxy calls do not
    block other FastAPI routes on the same process.
    """
    now = time.monotonic()
    cached = _ready_cache.get("payload")
    if (
        cached is not None
        and now - float(_ready_cache.get("at") or 0.0) < _READY_CACHE_TTL_SEC
    ):
        return dict(cached)

    gw = gateway_connectivity_status()
    if not gw["gateway_ok"]:
        payload = {
            "status": "not_ready",
            "gateway": gw["gateway_message"],
            "database": gw["gateway_message"],
            "gateway_url": gw.get("gateway_url") or "",
        }
        _ready_cache["at"] = now
        _ready_cache["payload"] = payload
        return payload

    try:
        db = get_db()
        version_body = db.version()
        payload = {
            "status": "ready",
            "gateway": gw["gateway_message"],
            "database": _arango_version_label(version_body),
            "gateway_url": gw.get("gateway_url") or "",
        }
    except Exception as e:
        payload = {
            "status": "not_ready",
            "gateway": gw["gateway_message"],
            "database": str(e),
            "gateway_url": gw.get("gateway_url") or "",
        }

    _ready_cache["at"] = now
    _ready_cache["payload"] = payload
    return payload


@router.get("/ready")
async def ready() -> dict[str, Any]:
    return await asyncio.to_thread(_ready_sync)
