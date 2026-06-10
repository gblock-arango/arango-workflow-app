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


def _bearer_from_workspace_auth(auth: dict[str, Any]) -> str:
    """Normalize ``WorkspaceClient().config.authenticate()`` to a bare bearer token."""
    if not auth:
        return ""
    lower = {str(k).lower(): str(v or "").strip() for k, v in auth.items()}
    authorization = lower.get("authorization") or ""
    if authorization.lower().startswith("bearer ") and len(authorization) > 7:
        return authorization[7:].strip()
    if authorization:
        return authorization
    return lower.get("token") or ""


def _service_principal_auth_headers() -> dict[str, str]:
    try:
        from databricks.sdk import WorkspaceClient

        raw = WorkspaceClient().config.authenticate() or {}
        bearer = _bearer_from_workspace_auth(dict(raw))
        if bearer:
            return {"Authorization": f"Bearer {bearer}"}
        if raw:
            return {str(k): str(v) for k, v in raw.items() if v}
        logger.warning("WorkspaceClient().config.authenticate() returned no bearer token")
        return {}
    except Exception:
        logger.exception("WorkspaceClient().config.authenticate() failed")
        return {}


def service_principal_bearer_token() -> str:
    """Bare M2M bearer for this app's service principal (empty when auth fails)."""
    return _bearer_from_workspace_auth(_service_principal_auth_headers())


def pin_outbound_service_principal_bearer() -> tuple[Token[str | None], Token[bool]]:
    """Pin app SP bearer for a background thread (M2M; ``app.yaml`` ``CAN_USE`` on peer apps)."""
    bearer = service_principal_bearer_token()
    bearer_tok = set_outbound_bearer_override(bearer or None)
    sp_tok = set_outbound_service_principal_mode(True)
    return bearer_tok, sp_tok


def release_outbound_service_principal_bearer(
    tokens: tuple[Token[str | None], Token[bool]],
) -> None:
    bearer_tok, sp_tok = tokens
    reset_outbound_bearer_override(bearer_tok)
    reset_outbound_service_principal_mode(sp_tok)


def outbound_databricks_auth_headers() -> dict[str, str]:
    override = (_outbound_bearer_override.get() or "").strip()
    if override:
        return {"Authorization": f"Bearer {override}"}
    if _outbound_force_service_principal.get():
        return _service_principal_auth_headers()
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
            "User token from x-forwarded-access-token is forwarded on request-bound browser calls. "
            "Background workers (extraction prepare thread) use this app's service principal (M2M) "
            "via app.yaml arango-gateway-app-invoke CAN_USE."
        )
    elif sp_ok:
        tip = (
            "App service principal token is available for peer app calls (arango-gateway-app-invoke "
            "CAN_USE in app.yaml). If peer calls return 401, redeploy after adding the app resource "
            "or check the gateway app grants CAN_USE to arango-workflow-app's SP."
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
