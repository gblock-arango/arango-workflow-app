"""Unity Catalog table listing and annotation API."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.errors import ValidationError
from app.services import uc_catalog, uc_entity_selections

router = APIRouter(prefix="/api/v1/uc", tags=["uc-catalog"])


class ColumnAnnotationInput(BaseModel):
    name: str
    comment: str = ""


class SaveAnnotationsBody(BaseModel):
    table_comment: str = ""
    columns: list[ColumnAnnotationInput] = Field(default_factory=list)


class UcEntitySelectionInput(BaseModel):
    table_full_name: str
    column_name: str = ""
    catalog: str = ""
    schema: str = ""
    table_name: str = ""
    type_text: str = ""
    comment: str = ""


class SaveEntitySelectionsBody(BaseModel):
    entities: list[UcEntitySelectionInput] = Field(default_factory=list)


@router.get("/tables")
async def list_tables(
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=10_000, ge=1, le=20_000),
) -> dict[str, Any]:
    """Searchable list of Unity Catalog tables."""
    return await asyncio.to_thread(
        uc_catalog.list_uc_tables,
        search=search,
        max_tables=limit,
    )


@router.get("/tables/{full_name:path}")
async def get_table(full_name: str) -> dict[str, Any]:
    """Table and column metadata including UC comments."""
    if not full_name.strip():
        raise ValidationError("full_name is required")
    return await asyncio.to_thread(uc_catalog.get_uc_table_detail, full_name)


@router.get("/entity-selections")
async def get_entity_selections() -> dict[str, Any]:
    """Load persisted UC table/column picks for extraction context."""
    entities = await asyncio.to_thread(uc_entity_selections.load_uc_entity_selections)
    return {"entities": entities, "count": len(entities)}


@router.put("/entity-selections")
async def put_entity_selections(body: SaveEntitySelectionsBody) -> dict[str, Any]:
    """Persist UC table/column picks (stored on UC volume as JSON)."""
    payload = [e.model_dump() for e in body.entities]
    return await asyncio.to_thread(uc_entity_selections.save_uc_entity_selections, payload)


@router.put("/tables/{full_name:path}/annotations")
async def save_annotations(full_name: str, body: SaveAnnotationsBody) -> dict[str, Any]:
    """Write table and column comments back to Unity Catalog."""
    if not full_name.strip():
        raise ValidationError("full_name is required")
    return await asyncio.to_thread(
        uc_catalog.save_uc_table_annotations,
        full_name,
        table_comment=body.table_comment,
        columns=[c.model_dump() for c in body.columns],
    )
