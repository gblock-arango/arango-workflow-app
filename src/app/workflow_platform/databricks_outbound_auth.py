"""Outbound auth for HTTPS from this Databricks App to other ``*.databricksapps.com`` APIs."""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Any

from app.workflow_platform.runtime import current_request

logger = logging.getLogger(__name__)

_outbound_bearer_override: ContextVar[str | None] = ContextVar(
    "outbound_bearer_override",
    default=None,
)
_outbound_force_service_principal: ContextVar[bool] = ContextVar(
    "outbound_force_service_principal",
    default=False,
)


def _user_access_token_from_request() -> str | None:
    req = current_request()
    if req is None:
        return None
    for key, value in req.headers.items():
        if key.lower() == "x-forwarded-access-token" and (value or "").strip():
            return value.strip()
    return None


def _authorization_from_incoming_request() -> dict[str, str] | None:
    req = current_request()
    if req is None:
        return None
    auth = (req.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer ") and len(auth) > 7:
        return {"Authorization": auth}
    return None


def capture_outbound_bearer_from_request() -> str | None:
    """Snapshot user/OBO bearer from the inbound HTTP request for background workers."""
    ut = _user_access_token_from_request()
    if ut:
        return ut
    fwd = _authorization_from_incoming_request()
    if fwd:
        auth = fwd.get("Authorization", "")
        if auth.lower().startswith("bearer ") and len(auth) > 7:
            return auth[7:].strip()
    return None


def set_outbound_bearer_override(token: str | None) -> Token[str | None]:
    return _outbound_bearer_override.set((token or "").strip() or None)


def reset_outbound_bearer_override(token: Token[str | None]) -> None:
    _outbound_bearer_override.reset(token)


def set_outbound_service_principal_mode(enabled: bool = True) -> Token[bool]:
    """Force outbound peer calls to use this app's service principal (app.yaml CAN_USE)."""
    return _outbound_force_service_principal.set(enabled)


def reset_outbound_service_principal_mode(token: Token[bool]) -> None:
    _outbound_force_service_principal.reset(token)


def _service_principal_auth_headers() -> dict[str, str]:
    try:
        from databricks.sdk import WorkspaceClient

        h = WorkspaceClient().config.authenticate()
        return dict(h) if h else {}
    except Exception:
        logger.exception("WorkspaceClient().config.authenticate() failed")
        return {}


def outbound_databricks_auth_headers() -> dict[str, str]:
    if _outbound_force_service_principal.get():
        return _service_principal_auth_headers()
    override = (_outbound_bearer_override.get() or "").strip()
    if override:
        return {"Authorization": f"Bearer {override}"}
    ut = _user_access_token_from_request()
    if ut:
        return {"Authorization": f"Bearer {ut}"}
    fwd = _authorization_from_incoming_request()
    if fwd:
        return fwd
    return _service_principal_auth_headers()


def outbound_auth_diagnostics() -> dict[str, Any]:
    has_user = bool(_user_access_token_from_request())
    has_incoming = bool(_authorization_from_incoming_request())
    sp_ok = False
    if not has_user and not has_incoming:
        try:
            from databricks.sdk import WorkspaceClient

            sp_ok = bool(WorkspaceClient().config.authenticate())
        except Exception:
            sp_ok = False
    if has_user:
        tip = (
            "User token from x-forwarded-access-token will be forwarded on request-bound calls. "
            "Background workers use the app service principal via app.yaml app-resource CAN_USE."
        )
    elif sp_ok:
        tip = (
            "App service principal token is available for peer app calls (arango-gateway-app-invoke "
            "in app.yaml). Request-bound calls may still forward the user token when present."
        )
    else:
        tip = (
            "No user token and WorkspaceClient().config.authenticate() failed or returned nothing. "
            "Fix app identity / env, enable User authorization on this app, or check Databricks Apps logs."
        )
    return {
        "x_forwarded_access_token_present": has_user,
        "incoming_authorization_bearer_present": has_incoming,
        "workspace_client_authenticate_succeeds": sp_ok,
        "note": tip,
    }
