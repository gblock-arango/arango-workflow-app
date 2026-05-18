"""Outbound auth for HTTPS from this Databricks App to other ``*.databricksapps.com`` APIs."""

from __future__ import annotations

import logging
from typing import Any

from app.workflow_platform.runtime import current_request

logger = logging.getLogger(__name__)


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


def outbound_databricks_auth_headers() -> dict[str, str]:
    ut = _user_access_token_from_request()
    if ut:
        return {"Authorization": f"Bearer {ut}"}
    fwd = _authorization_from_incoming_request()
    if fwd:
        return fwd
    try:
        from databricks.sdk import WorkspaceClient

        h = WorkspaceClient().config.authenticate()
        return dict(h) if h else {}
    except Exception:
        logger.exception("WorkspaceClient().config.authenticate() failed")
        return {}


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
            "User token from x-forwarded-access-token will be forwarded. If APIs still return 401, "
            "confirm this user has CAN USE on mcp-arango-agent / arango-gateway-app (app resources) "
            "and that deployed app names match app.yaml."
        )
    elif sp_ok:
        tip = (
            "Only the app service principal token is available (no x-forwarded-access-token). "
            "Many workspaces reject that token at another App's ingress (401). Enable **User "
            "authorization** on this workflow app per Databricks Apps auth docs."
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
