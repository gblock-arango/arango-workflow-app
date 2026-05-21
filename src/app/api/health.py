from typing import Any

from fastapi import APIRouter

from app.db.client import get_db
from app.db.gateway_connectivity import gateway_connectivity_status

router = APIRouter(tags=["system"])


def _arango_version_label(version_body: Any) -> str:
    if isinstance(version_body, dict):
        ver = version_body.get("version")
        if ver:
            return f"Arango {ver}"
    return "Arango cluster reachable"


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, Any]:
    """
    Readiness for the home-page "Connection to Arango" widget.

    1. Resolve gateway Apps URL (env or UC registry) and probe ``GET /health``.
    2. Verify Arango via gateway proxy (``GET /_api/version`` on the app database).
    """
    gw = gateway_connectivity_status()
    if not gw["gateway_ok"]:
        return {
            "status": "not_ready",
            "gateway": gw["gateway_message"],
            "database": gw["gateway_message"],
            "gateway_url": gw.get("gateway_url") or "",
        }

    try:
        db = get_db()
        version_body = db.version()
        return {
            "status": "ready",
            "gateway": gw["gateway_message"],
            "database": _arango_version_label(version_body),
            "gateway_url": gw.get("gateway_url") or "",
        }
    except Exception as e:
        return {
            "status": "not_ready",
            "gateway": gw["gateway_message"],
            "database": str(e),
            "gateway_url": gw.get("gateway_url") or "",
        }
