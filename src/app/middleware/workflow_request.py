"""Bind the current Starlette request for workflow platform outbound auth."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.workflow_platform.runtime import bind_request


class WorkflowRequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        bind_request(request)
        return await call_next(request)
