"""System diagnostics (LLM connectivity, etc.)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services.llm_connectivity import probe_llm_connectivity

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/llm-status")
async def llm_status(
    force: bool = Query(
        default=False,
        description="When true, bypass the short-lived probe cache and re-test providers.",
    ),
) -> dict[str, Any]:
    """Live probe of embedding + extraction LLM endpoints (OpenAI / Anthropic)."""
    return await probe_llm_connectivity(force=force)
