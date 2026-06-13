"""System diagnostics (LLM connectivity, etc.)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.errors import ValidationError
from app.services.llm_connectivity import probe_llm_connectivity
from app.services.llm_preferences import load_llm_preferences, save_llm_preferences

router = APIRouter(prefix="/api/v1/system", tags=["system"])


class LlmSettingsBody(BaseModel):
    provider: str | None = Field(
        default=None,
        description="databricks | openai",
    )
    extraction_model: str | None = Field(default=None, max_length=200)
    embedding_model: str | None = Field(default=None, max_length=200)
    embedding_dimension: int | None = Field(
        default=None,
        ge=1,
        le=8192,
        description="Vector dimension for chunk embeddings (must match the embedding model).",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="Optional; when omitted or blank, the stored key is kept.",
    )


@router.get("/llm-settings")
async def get_llm_settings() -> dict[str, Any]:
    """Return saved LLM provider/model preferences (API key is never returned)."""
    return await asyncio.to_thread(load_llm_preferences)


@router.put("/llm-settings")
async def put_llm_settings(body: LlmSettingsBody) -> dict[str, Any]:
    """Persist LLM provider/model preferences and apply them for this app process."""
    provider = (body.provider or "").strip().lower()
    if provider and provider not in ("databricks", "databricks_serving", "openai"):
        raise ValidationError("provider must be databricks or openai")
    return await asyncio.to_thread(
        save_llm_preferences,
        provider=body.provider,
        extraction_model=body.extraction_model,
        embedding_model=body.embedding_model,
        embedding_dimension=body.embedding_dimension,
        openai_api_key=body.openai_api_key,
    )


@router.get("/llm-status")
async def llm_status(
    force: bool = Query(
        default=False,
        description="When true, bypass the short-lived probe cache and re-test providers.",
    ),
) -> dict[str, Any]:
    """Live probe of embedding + extraction LLM endpoints (OpenAI / Anthropic)."""
    return await probe_llm_connectivity(force=force)
