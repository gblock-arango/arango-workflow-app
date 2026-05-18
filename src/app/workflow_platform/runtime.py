"""Request-scoped helpers and config access for the workflow control plane."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict
from typing import Any

from starlette.requests import Request

from app.workflow_platform.config import AppConfig

_request_ctx: ContextVar[Request | None] = ContextVar("workflow_http_request", default=None)


def bind_request(request: Request) -> None:
    _request_ctx.set(request)


def current_request() -> Request | None:
    return _request_ctx.get()


def workflow_config_dict() -> dict[str, Any]:
    return asdict(AppConfig())
