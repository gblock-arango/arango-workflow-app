"""Extraction API endpoints per PRD Section 7.2."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.errors import ConflictError, NotFoundError
from app.db.async_gateway import run_sync
from app.db.arango_database_names import (
    suggest_auto_graph_database_name,
    validate_arango_database_name,
)
from app.db.client import get_db
from app.db.utils import doc_get, run_aql
from app.services import extraction as extraction_service
from app.services.extraction_materialize import validate_embedding_documents_ready

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/extraction", tags=["extraction"])


class StartRunRequest(BaseModel):
    document_id: str | None = Field(
        default=None,
        description="ID of a single document to extract from (backward compat)",
    )
    document_ids: list[str] | None = Field(
        default=None,
        description="IDs of documents to extract from (multi-doc mode)",
    )
    config: dict[str, Any] | None = Field(
        default=None,
        description="Optional config overrides (num_passes, consistency_threshold, etc.)",
    )
    target_ontology_id: str | None = Field(
        default=None,
        description="Existing ontology to merge results into (incremental extraction)",
    )
    arango_database: str | None = Field(
        default=None,
        description=(
            "ArangoDB database for this run (created automatically if missing). "
            "Defaults to the next AutoGraph_<n> name when omitted."
        ),
    )
    base_ontology_ids: list[str] | None = Field(
        default=None,
        description="Multiple base ontologies for Tier 2 context-aware extraction",
    )


class StartRunResponse(BaseModel):
    run_id: str
    doc_id: str | None = None
    doc_ids: list[str] = []
    status: str


class RetryResponse(BaseModel):
    run_id: str
    new_run_id: str
    status: str


class CancelRunResponse(BaseModel):
    run_id: str
    status: str
    already_cancelled: bool = False


@router.get("/default-database-name")
async def default_database_name() -> dict[str, str]:
    """Suggest the next ``AutoGraph_<n>`` database name for a new extraction run."""
    name = await run_sync(suggest_auto_graph_database_name)
    return {"name": name}


@router.post("/run")
async def start_extraction(body: StartRunRequest) -> StartRunResponse:
    """Trigger ontology extraction on one or more documents.

    Creates the run record immediately (status ``preparing``) and returns
    ``run_id`` without waiting for UC→Arango materialization or schema
    migrations. Progress is written to ``extraction_runs.stats`` and polled
    via ``GET /runs/{run_id}``.
    """
    doc_ids = await _resolve_doc_ids(body)

    ontology_ids: list[str] = []
    if body.target_ontology_id:
        ontology_ids.append(body.target_ontology_id)
    if body.base_ontology_ids:
        ontology_ids.extend(oid for oid in body.base_ontology_ids if oid not in ontology_ids)

    try:
        if body.arango_database:
            validate_arango_database_name(body.arango_database)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_record = extraction_service.begin_extraction_run(
        document_ids=doc_ids,
        config_overrides=body.config,
        domain_ontology_ids=ontology_ids or None,
        target_ontology_id=body.target_ontology_id,
        arango_database=body.arango_database,
    )
    return StartRunResponse(
        run_id=run_record["_key"],
        doc_id=doc_ids[0] if len(doc_ids) == 1 else None,
        doc_ids=doc_ids,
        status=run_record["status"],
    )


def _create_preparing_run(
    doc_ids: list[str],
    config: dict[str, Any] | None,
    domain_ontology_ids: list[str] | None,
    target_ontology_id: str | None,
) -> dict[str, Any]:
    """Legacy sync create path (retry/tests). Prefer :func:`begin_extraction_run`."""
    db = get_db()
    return extraction_service.create_run_record(
        db,
        document_ids=doc_ids,
        config_overrides=config,
        domain_ontology_ids=domain_ontology_ids,
        target_ontology_id=target_ontology_id,
        initial_status="preparing",
    )


async def _resolve_doc_ids(body: StartRunRequest) -> list[str]:
    """Normalize document_id / document_ids and verify UC embedding_status is ready."""
    ids: list[str] = []
    if body.document_ids:
        ids.extend(body.document_ids)
    if body.document_id and body.document_id not in ids:
        ids.insert(0, body.document_id)
    if not ids:
        raise HTTPException(
            status_code=422,
            detail="At least one of document_id or document_ids is required",
        )

    try:
        await asyncio.to_thread(validate_embedding_documents_ready, ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ids


@router.get("/runs")
async def list_runs(
    cursor: str | None = Query(None, description="Pagination cursor"),
    limit: int = Query(25, ge=1, le=100, description="Page size"),
    status: str | None = Query(None, description="Filter by status"),
) -> dict[str, Any]:
    """List extraction runs with enriched metadata."""
    return await run_sync(_list_runs_enriched, cursor, limit, status)


def _list_runs_enriched(
    cursor: str | None,
    limit: int,
    status: str | None,
) -> dict[str, Any]:
    result = extraction_service.list_runs(
        cursor=cursor,
        limit=limit,
        status=status,
    )
    payload = result.model_dump()

    for run in payload.get("data", []):
        run_doc_ids = run.get("doc_ids") or []
        legacy_id = run.get("doc_id")
        if legacy_id and legacy_id not in run_doc_ids:
            run_doc_ids = [legacy_id, *run_doc_ids]
        run_db_name = run.get("arango_database")
        if run_db_name:
            from app.db.client import clear_active_arango_database, set_active_arango_database

            set_active_arango_database(str(run_db_name))
        try:
            db = get_db()
            if run_doc_ids and db.has_collection("documents"):
                names: list[str] = []
                total_chunks = 0
                for did in run_doc_ids:
                    try:
                        doc = doc_get(db.collection("documents"), did)
                        if doc:
                            names.append(doc.get("filename", did))
                            total_chunks += doc.get("chunk_count", 0)
                    except Exception:
                        log.debug("Could not fetch document %s for run enrichment", did)
                if names:
                    run["document_name"] = ", ".join(names)
                    run["chunk_count"] = total_chunks
            run.setdefault("document_name", legacy_id or "Unknown")
            run.setdefault("chunk_count", 0)

            stats = run.get("stats", {})
            run["classes_extracted"] = stats.get("classes_extracted", 0)
            run["properties_extracted"] = stats.get("properties_extracted", 0)
            run["error_count"] = len(stats.get("errors", []))
            run["preparation_stage"] = stats.get("preparation_stage")
            run["preparation_message"] = stats.get("preparation_message")
            run["preparation_updated_at"] = stats.get("preparation_updated_at")

            started = run.get("started_at", 0)
            completed = run.get("completed_at", 0)
            if started and completed:
                run["duration_ms"] = int((completed - started) * 1000)
            else:
                run.setdefault("duration_ms", 0)

            if db.has_collection("ontology_registry") and run.get("_key"):
                try:
                    oid_result = list(
                        run_aql(
                            db,
                            "FOR o IN ontology_registry "
                            "FILTER o.extraction_run_id == @rid LIMIT 1 RETURN o._key",
                            bind_vars={"rid": run["_key"]},
                        )
                    )
                    if oid_result:
                        run["ontology_id"] = oid_result[0]
                except Exception:
                    log.debug(
                        "Could not resolve ontology_id for run enrichment",
                        exc_info=True,
                    )
            if "ontology_id" not in run and run.get("target_ontology_id"):
                run["ontology_id"] = run["target_ontology_id"]
        finally:
            if run_db_name:
                clear_active_arango_database()

    return payload


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Get extraction run status and stats."""
    return await run_sync(_get_run_sync, run_id)


@router.get("/runs/{run_id}/status")
async def get_run_status(run_id: str) -> dict[str, Any]:
    """Lightweight run snapshot for frequent UI polls — never blocks on Arango gateway."""
    return extraction_service.get_run_status_for_poll(run_id)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> CancelRunResponse:
    """Request cooperative cancellation of a preparing or running extraction."""
    try:
        result = await run_sync(extraction_service.cancel_extraction_run, run_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CancelRunResponse(**result)


def _get_run_sync(run_id: str) -> dict[str, Any]:
    return extraction_service.get_run(run_id=run_id)


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str) -> dict[str, Any]:
    """Delete an extraction run and its results document."""
    return await run_sync(_delete_run_sync, run_id)


@router.get("/runs/{run_id}/steps")
async def get_run_steps(run_id: str) -> dict[str, Any]:
    """Get per-agent step detail: inputs, outputs, token usage, errors, duration."""
    steps = await run_sync(_get_run_steps_sync, run_id)
    return {"run_id": run_id, "steps": steps}


def _get_run_steps_sync(run_id: str) -> list[dict[str, Any]]:
    db = extraction_service.db_for_run(run_id)
    return extraction_service.get_run_steps(db, run_id=run_id)


@router.get("/runs/{run_id}/results")
async def get_run_results(run_id: str) -> dict[str, Any]:
    """Get extracted entities from a run."""
    return await run_sync(_get_run_results_sync, run_id)


def _get_run_results_sync(run_id: str) -> dict[str, Any]:
    db = extraction_service.db_for_run(run_id)
    return extraction_service.get_run_results(db, run_id=run_id)


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str) -> RetryResponse:
    """Retry a failed extraction run."""
    new_run = await extraction_service.retry_run(
        extraction_service.db_for_run(run_id),
        run_id=run_id,
    )
    return RetryResponse(
        run_id=run_id,
        new_run_id=new_run["_key"],
        status=new_run["status"],
    )


@router.get("/runs/{run_id}/cost")
async def get_run_cost(run_id: str) -> dict[str, Any]:
    """Get LLM cost breakdown: tokens by model, estimated cost."""
    return await run_sync(_get_run_cost_sync, run_id)


def _get_run_cost_sync(run_id: str) -> dict[str, Any]:
    from app.services.run_progress_cache import get_cached_run_progress

    cached = get_cached_run_progress(run_id)
    if cached and str(cached.get("status")) in ("running", "paused", "preparing"):
        return extraction_service.get_run_cost(None, run_id=run_id)
    db = extraction_service.db_for_run(run_id)
    return extraction_service.get_run_cost(db, run_id=run_id)


def _delete_run_sync(run_id: str) -> dict[str, Any]:
    db = extraction_service.db_for_run(run_id)
    if not db.has_collection("extraction_runs"):
        raise HTTPException(status_code=404, detail="No extraction runs collection")
    col = db.collection("extraction_runs")
    if not col.has(run_id):
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    col.delete(run_id)
    results_key = f"results_{run_id}"
    if col.has(results_key):
        col.delete(results_key)
    log.info("deleted extraction run %s", run_id)
    return {"deleted": True, "run_id": run_id}
