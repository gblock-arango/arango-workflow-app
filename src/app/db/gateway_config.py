"""Gateway settings for ``arango-gateway-app`` (workflow-app copy; not shared with mcp-app)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.workflow_platform.runtime import workflow_config_dict
from app.workflow_platform.services.gateway_url_registry import effective_gateway_base_url


@dataclass(frozen=True)
class GatewaySettings:
    base_url: str = ""
    timeout_seconds: float = 120.0
    tls_verify: bool = True


def get_gateway_settings() -> GatewaySettings:
    return GatewaySettings(
        base_url=(os.environ.get("ARANGO_GATEWAY_BASE_URL") or "").strip().rstrip("/"),
        timeout_seconds=float(os.environ.get("ARANGO_GATEWAY_TIMEOUT_SECONDS", "120")),
        tls_verify=(os.environ.get("ARANGO_GATEWAY_TLS_VERIFY", "true").strip().lower() != "false"),
    )


def effective_gateway_url() -> str:
    """Resolve gateway Apps URL (env override, then UC ``ARANGO_GATEWAY_REGISTRY_TABLE``)."""
    return effective_gateway_base_url(workflow_config_dict()).strip().rstrip("/")
