"""Workflow control-plane BFF: dashboard layout config and peer-app proxies."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from httpx import ASGITransport

from app.workflow_platform.databricks_outbound_auth import (
    outbound_auth_diagnostics,
    outbound_databricks_auth_headers,
)
from app.workflow_platform.peer_dispatch import (
    reset_bff_internal_dispatch,
    set_bff_internal_dispatch,
)
from app.workflow_platform.runtime import workflow_config_dict
from app.workflow_platform.services.agent_url_registry import (
    effective_arango_agent_base_url,
    invalidate_arango_agent_url_uc_cache,
)
from app.workflow_platform.services.bronze_injector_uc_registry import (
    effective_injector_uc_snapshot,
    invalidate_bronze_injector_uc_cache,
)
from app.workflow_platform.services.gateway_url_registry import (
    effective_gateway_base_url,
    effective_gateway_iframe_base_url,
    invalidate_gateway_url_uc_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


def _response_looks_like_html(text: str) -> bool:
    head = (text or "").lstrip()[:64].lower()
    return head.startswith("<!doctype") or head.startswith("<html")


def _json_error_from_html_upstream(
    *,
    label: str,
    status_code: int,
    content_type: str | None,
    body: str,
) -> JSONResponse:
    preview = (body or "")[:800].replace("\n", " ")
    return JSONResponse(
        status_code=502,
        content={
            "ok": False,
            "error": (
                f"{label} returned HTTP {status_code} with HTML instead of JSON. "
                "This usually means Databricks Apps rejected the server-side call "
                "(login/error page). Open /api/workflow/debug/startup-status while signed in."
            ),
            "upstream_http_status": status_code,
            "upstream_content_type": content_type,
            "upstream_body_preview": preview,
        },
    )


async def _proxy_json(
    *,
    base: str,
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float,
    label: str,
) -> Response | JSONResponse:
    url = f"{base.rstrip('/')}{path}"
    headers = outbound_databricks_auth_headers() or None
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if method.upper() == "POST":
                r = await client.post(url, json=json_body or {}, headers=headers)
            else:
                r = await client.get(url, params=params or {}, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("%s proxy %s %s failed: %s", label, method, path, exc)
            return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})

    text = r.text or ""
    if _response_looks_like_html(text):
        return _json_error_from_html_upstream(
            label=f"{label} {method} {path}",
            status_code=r.status_code,
            content_type=r.headers.get("Content-Type"),
            body=text,
        )
    ct = r.headers.get("Content-Type") or "application/json"
    return Response(content=r.content, status_code=r.status_code, media_type=ct)


def _cfg() -> dict[str, Any]:
    return workflow_config_dict()


@router.get("/config")
async def workflow_config() -> dict[str, Any]:
    """Shell layout: gateway iframe URL, registry metadata, UC snapshot base."""
    cfg = _cfg()
    iframe_base = effective_gateway_iframe_base_url(cfg)
    embed_src = ""
    if iframe_base:
        embed_src = (
            f"{iframe_base}/embedded-arango/_db/_system/_admin/aardvark/index.html#login"
        )
    return {
        "dashboard_title": "Arango on Databricks: Context Changes Everything",
        "arango_ui_embed_iframe_src": embed_src,
        "arango_gateway_registry_table": cfg.get("ARANGO_GATEWAY_REGISTRY_TABLE") or "",
        "uc_graph_snapshot_base": cfg.get("UC_GRAPH_SNAPSHOT_BASE") or "",
        "gateway_base_url": effective_gateway_base_url(cfg) or "",
    }


@router.get("/health")
async def workflow_health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/arango/chat", response_model=None)
async def arango_chat_proxy(request: Request) -> Response:
    cfg = _cfg()
    base = effective_gateway_base_url(cfg).strip().rstrip("/")
    if not base:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": (
                    "Gateway base URL is not configured. Set ARANGO_GATEWAY_BASE_URL or publish "
                    "to ARANGO_GATEWAY_REGISTRY_TABLE."
                ),
            },
        )
    body = await request.json()
    return await _proxy_json(
        base=base,
        method="POST",
        path="/api/arango/chat",
        json_body=body if isinstance(body, dict) else {},
        timeout=660.0,
        label="gateway",
    )


@router.post("/genie-mcp/chat", response_model=None)
async def genie_mcp_chat_proxy(request: Request) -> Response:
    cfg = _cfg()
    base = effective_arango_agent_base_url(cfg).strip().rstrip("/")
    if not base:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": (
                    "ARANGO_AGENT_BASE_URL is not set. Deploy arango-mcp-app, then set this app "
                    "config to the agent app URL (https://….databricksapps.com)."
                ),
            },
        )
    body = await request.json()
    return await _proxy_json(
        base=base,
        method="POST",
        path="/api/genie-mcp/chat",
        json_body=body if isinstance(body, dict) else {},
        timeout=660.0,
        label="arango-mcp-app",
    )


@router.post("/genie/chat", response_model=None)
async def genie_chat_proxy(request: Request) -> Response:
    cfg = _cfg()
    base = effective_arango_agent_base_url(cfg).strip().rstrip("/")
    if not base:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": (
                    "ARANGO_AGENT_BASE_URL is not set. Deploy arango-mcp-app with Genie env."
                ),
            },
        )
    body = await request.json()
    return await _proxy_json(
        base=base,
        method="POST",
        path="/api/genie/chat",
        json_body=body if isinstance(body, dict) else {},
        timeout=660.0,
        label="arango-mcp-app",
    )


_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)


@router.api_route(
    "/ontoextract/v1/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    response_model=None,
)
async def ontoextract_v1_peer_bff(request: Request, path: str) -> Response:
    """
    Peer-app OntoExtract API (mcp-arango-agent ``/mcp/aoe``).

    Same auth model as ``/api/workflow/genie/chat``: public BFF prefix; in-process
    dispatch to ``/api/v1/*`` with a service user (Databricks app OAuth at ingress).
    """
    inner_path = f"/api/v1/{path.lstrip('/')}"
    if request.url.query:
        inner_path = f"{inner_path}?{request.url.query}"

    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    token = set_bff_internal_dispatch(True)
    try:
        transport = ASGITransport(app=request.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://workflow-internal",
        ) as client:
            r = await client.request(
                request.method,
                inner_path,
                content=body if body else None,
                headers=headers,
            )
    finally:
        reset_bff_internal_dispatch(token)

    ct = r.headers.get("Content-Type") or "application/json"
    return Response(content=r.content, status_code=r.status_code, media_type=ct)


@router.get("/debug/startup-status")
async def startup_status(refresh: bool = False) -> dict[str, Any]:
    if refresh:
        invalidate_gateway_url_uc_cache()
        invalidate_arango_agent_url_uc_cache()
        invalidate_bronze_injector_uc_cache()

    cfg = _cfg()
    base = effective_gateway_base_url(cfg)
    gw_payload: dict[str, Any] = {}
    if base:
        try:
            params = {"refresh": "true"} if refresh else {}
            headers = outbound_databricks_auth_headers() or None
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(
                    f"{base}/api/debug/startup-status",
                    params=params,
                    headers=headers,
                )
            if r.is_success:
                gw_payload = r.json() if r.content else {}
            else:
                gw_payload = {
                    "gateway_http_status": r.status_code,
                    "gateway_body_preview": (r.text or "")[:800],
                }
        except Exception as exc:
            logger.warning("Gateway startup-status fetch failed: %s", exc)
            gw_payload = {"gateway_unreachable": str(exc)}
    else:
        gw_payload = {
            "gateway": "not_configured",
            "hint": (
                "Set ARANGO_GATEWAY_BASE_URL or ensure arango-gateway-app has published to "
                "ARANGO_GATEWAY_REGISTRY_TABLE."
            ),
        }

    agent_base = effective_arango_agent_base_url(cfg).strip().rstrip("/")
    genie_fragment: dict[str, Any] = {}
    if agent_base:
        try:
            params = {"refresh": "true"} if refresh else {}
            headers = outbound_databricks_auth_headers() or None
            async with httpx.AsyncClient(timeout=30.0) as client:
                ar = await client.get(
                    f"{agent_base}/api/debug/startup-status",
                    params=params,
                    headers=headers,
                )
            if ar.is_success:
                agent_json = ar.json() if ar.content else {}
                genie_fragment = {"genie": agent_json.get("genie")}
            else:
                genie_fragment = {
                    "genie": None,
                    "arango_agent_http_status": ar.status_code,
                    "arango_agent_body_preview": (ar.text or "")[:800],
                }
        except Exception as exc:
            logger.warning("arango-mcp-app startup-status fetch failed: %s", exc)
            genie_fragment = {"genie": None, "arango_agent_unreachable": str(exc)}
    else:
        genie_fragment = {
            "genie": None,
            "arango_agent": "not_configured",
            "hint": (
                "Set ARANGO_AGENT_BASE_URL or deploy arango-mcp-app and ensure "
                "ARANGO_AGENT_REGISTRY_TABLE has an active row."
            ),
        }

    return {
        **gw_payload,
        **genie_fragment,
        **effective_injector_uc_snapshot(cfg),
        "gateway_base_url_effective": base or None,
        "arango_agent_base_url_effective": agent_base or None,
        "dashboard_proxy_auth": outbound_auth_diagnostics(),
    }
