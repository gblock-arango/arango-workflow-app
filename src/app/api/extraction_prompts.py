"""Extraction prompt template and debug API."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.errors import NotFoundError, ValidationError
from app.extraction.prompts import list_templates
from app.services.extraction_prompt_debug import load_last_extractor_llm_call
from app.services.extraction_prompt_templates import (
    get_template_catalog_entry,
    list_templates_catalog,
    save_template_override,
)

router = APIRouter(prefix="/api/v1/system/extraction-prompts", tags=["extraction-prompts"])


class SaveTemplateBody(BaseModel):
    system_prompt: str = Field(..., min_length=1)
    user_prompt: str = Field(..., min_length=1)


@router.get("/templates")
async def list_extraction_prompt_templates() -> dict[str, Any]:
    """List registered LangGraph extractor templates (builtin + UC overrides)."""
    templates = await asyncio.to_thread(list_templates_catalog)
    return {"templates": templates, "count": len(templates)}


@router.get("/templates/{template_key}")
async def get_extraction_prompt_template(template_key: str) -> dict[str, Any]:
    key = template_key.strip()
    available = await asyncio.to_thread(list_templates)
    if key not in available:
        raise NotFoundError(f"Unknown prompt template {key!r}")
    return await asyncio.to_thread(get_template_catalog_entry, key)


@router.put("/templates/{template_key}")
async def put_extraction_prompt_template(
    template_key: str,
    body: SaveTemplateBody,
) -> dict[str, Any]:
    key = template_key.strip()
    if not key:
        raise ValidationError("template_key is required")
    saved = await asyncio.to_thread(
        save_template_override,
        key,
        system_prompt=body.system_prompt,
        user_prompt=body.user_prompt,
    )
    saved["ok"] = True
    return saved


@router.get("/last")
async def get_last_extraction_prompt(
    run_id: str | None = Query(default=None, description="Optional run id filter"),
) -> dict[str, Any]:
    """Most recent extractor LLM prompt and response."""
    last = await asyncio.to_thread(load_last_extractor_llm_call, run_id=run_id)
    if last is None and run_id:
        last = await asyncio.to_thread(load_last_extractor_llm_call, run_id=None)
        if last is not None:
            return {
                "found": True,
                "matched_run": False,
                "run_id": last.get("run_id"),
                "template_key": last.get("template_key"),
                "step": last.get("step"),
                "pass_number": last.get("pass_number"),
                "batch_idx": last.get("batch_idx"),
                "model_name": last.get("model_name"),
                "recorded_at": last.get("recorded_at"),
                "actual_prompt": last.get("actual_prompt") or "",
                "response_text": last.get("response_text") or "",
            }
    if last is None:
        return {"found": False, "actual_prompt": "", "response_text": ""}
    return {
        "found": True,
        "matched_run": True if not run_id or last.get("run_id") == run_id else False,
        "run_id": last.get("run_id"),
        "template_key": last.get("template_key"),
        "step": last.get("step"),
        "pass_number": last.get("pass_number"),
        "batch_idx": last.get("batch_idx"),
        "model_name": last.get("model_name"),
        "recorded_at": last.get("recorded_at"),
        "actual_prompt": last.get("actual_prompt") or "",
        "response_text": last.get("response_text") or "",
    }
