"""User-facing hints for errors returned through arango-gateway-app."""

from __future__ import annotations


def gateway_error_hint(message: str) -> str:
    """Extra context when the failure is likely Arango coordinates in UC, not the gateway Apps URL."""
    m = (message or "").lower()
    if "name or service not known" in m or "errno -2" in m or "nodename nor servname" in m:
        return (
            " The gateway app was contacted, but it could not resolve the Arango cluster "
            "host from the active row in ARANGO_REGISTRY_TABLE (e.g. "
            "workspace.default.arango_connection_registry). Update ip_address / protocol / port "
            "so arango-gateway-app can reach the cluster, then check "
            "arango-gateway-app /api/debug/startup-status?refresh=true."
        )
    return ""


def format_gateway_error(exc: BaseException) -> str:
    msg = str(exc).strip() or type(exc).__name__
    return msg + gateway_error_hint(msg)
