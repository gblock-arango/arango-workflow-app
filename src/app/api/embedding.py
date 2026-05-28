"""Embedding pipeline API — UC ``embedding_status`` table + volume artifacts only."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.dependencies import get_or_404
from app.api.errors import ConflictError, ValidationError
from app.services import embedding_pipeline
from app.services import embedding_status as status_svc

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/embedding", tags=["embedding"])

_background_tasks: set[asyncio.Task[None]] = set()


class PipelineBatchBody(BaseModel):
    doc_ids: list[str] = Field(..., min_length=1, max_length=100)
    stage: Literal["parse", "chunk", "embed"]


class PipelineCancelBody(BaseModel):
    doc_ids: list[str] = Field(default_factory=list)


def _track_background_task(task: asyncio.Task[None]) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.get("/status")
async def list_status(
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    """List embedding pipeline rows from the UC Delta table."""
    rows = await asyncio.to_thread(status_svc.list_embedding_status, limit=limit)
    return {"data": rows, "total_count": len(rows)}


@router.get("/status/{doc_id}")
async def get_status(doc_id: str) -> dict[str, Any]:
    row = await asyncio.to_thread(status_svc.get_embedding_status, doc_id)
    return get_or_404(row, "Embedding document", doc_id)


@router.post("/pipeline/batch")
async def pipeline_batch(body: PipelineBatchBody) -> dict[str, Any]:
    """Queue parse, chunk, or embed for documents (background tasks)."""
    queued: list[str] = []
    for doc_id in body.doc_ids:
        row = await asyncio.to_thread(status_svc.get_embedding_status, doc_id)
        if not row:
            continue
        try:
            status_svc.assert_stage_allowed(row, body.stage)
        except (ValidationError, ConflictError):
            continue
        task = asyncio.create_task(embedding_pipeline.run_pipeline_stage(doc_id, body.stage))
        _track_background_task(task)
        queued.append(doc_id)
    return {"stage": body.stage, "queued": queued, "count": len(queued)}


@router.post("/pipeline/cancel")
async def pipeline_cancel(body: PipelineCancelBody) -> dict[str, Any]:
    for doc_id in body.doc_ids:
        embedding_pipeline.request_pipeline_cancel(doc_id)
    return {"cancelled": body.doc_ids, "count": len(body.doc_ids)}
