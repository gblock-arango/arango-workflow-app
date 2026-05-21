"""In-process dispatch from public ``/api/workflow/ontoextract/v1/*`` BFF to ``/api/v1/*``."""

from __future__ import annotations

from contextvars import ContextVar

_bff_internal: ContextVar[bool] = ContextVar("workflow_bff_internal", default=False)


def bff_internal_dispatch_active() -> bool:
    return bool(_bff_internal.get())


def set_bff_internal_dispatch(active: bool) -> object:
    return _bff_internal.set(active)


def reset_bff_internal_dispatch(token: object) -> None:
    _bff_internal.reset(token)
