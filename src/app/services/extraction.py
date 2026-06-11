"""ExtractionRunService — orchestrates extraction pipeline lifecycle.

Creates extraction_runs records, dispatches LangGraph pipeline, updates status,
and tracks token usage and cost.
"""

from __future__ import annotations

import asyncio
import contextlib
import concurrent.futures
import logging
import os
import threading
import time
import uuid
from typing import Any, cast

from typing import Any as StandardCollection  # gateway collection handle
from app.db.types import StandardDatabase

from app.api.errors import ConflictError, NotFoundError, ServiceBusyError
from app.config import settings
from app.db.arango_database_names import resolve_arango_database_name, validate_arango_database_name
from app.db.client import (
    clear_active_arango_database,
    _is_duplicate_name_error,
    effective_arango_database_name,
    get_db,
    set_active_arango_database,
)
from app.db.gateway_database import GatewayAPIError
from app.db.pagination import decode_cursor, encode_cursor, paginate
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import doc_get, insert_temporal_edge_if_absent, run_aql
from app.extraction.judges.qualitative_eval_node import run_qualitative_evaluation
from app.extraction.pipeline import run_pipeline
from app.models.common import PaginatedResponse
from app.services.confidence import compute_class_confidence
from app.services.edge_repair import resolve_range_class
from app.workflow_platform.databricks_outbound_auth import (
    pin_outbound_service_principal_bearer,
    release_outbound_service_principal_bearer,
)
from app.services.run_progress_cache import (
    drop_run_progress_cache,
    get_cached_run_progress,
    seed_run_progress,
    update_run_progress_cache,
)

log = logging.getLogger(__name__)
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()
_cancelled_runs: set[str] = set()

CANCELLABLE_RUN_STATUSES = frozenset({"preparing", "queued", "running", "paused"})


class ExtractionCancelled(Exception):
    """Raised when cooperative cancellation is requested for an extraction run."""


def request_extraction_cancel(run_id: str) -> None:
    _cancelled_runs.add(run_id)


def clear_extraction_cancel(run_id: str) -> None:
    _cancelled_runs.discard(run_id)


def is_extraction_cancelled(run_id: str) -> bool:
    return run_id in _cancelled_runs


def check_extraction_cancelled(run_id: str) -> None:
    if is_extraction_cancelled(run_id):
        raise ExtractionCancelled(f"Extraction run {run_id} cancelled")

PREPARATION_STAGE_GATEWAY_HEALTH = "gateway_health"
PREPARATION_STAGE_GATEWAY_ARANGO = "gateway_arango"
PREPARATION_STAGE_RUN_PERSISTED = "run_persisted"
PREPARATION_STAGE_STARTING = "starting"  # legacy
PREPARATION_STAGE_LOADING_UC = "loading_uc_chunks"
PREPARATION_STAGE_MATERIALIZING = "materializing_arango"
PREPARATION_STAGE_SCHEMA = "schema_migrations"
PREPARATION_STAGE_LAUNCHING = "launching_pipeline"

_MODEL_TOKEN_RATES_PER_MILLION: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}


def _generate_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def _get_collection(db: StandardDatabase, name: str) -> StandardCollection:
    if not db.has_collection(name):
        try:
            db.create_collection(name)
        except GatewayAPIError as exc:
            if not _is_duplicate_name_error(exc):
                raise
    return db.collection(name)


def _apply_run_arango_database(
    run_id: str,
    *,
    run: dict[str, Any] | None = None,
    arango_database: str | None = None,
) -> str | None:
    """Pin the run's target database on the current thread (explicit, cache, or run doc)."""
    name = (arango_database or "").strip() or None
    if not name:
        cached = get_cached_run_progress(run_id)
        if cached and cached.get("arango_database"):
            name = str(cached["arango_database"])
        elif run and run.get("arango_database"):
            name = str(run["arango_database"])
    if not name:
        return None
    set_active_arango_database(name)
    return name


def db_for_run(run_id: str) -> StandardDatabase:
    """Open the Arango database that owns this extraction run."""
    run = get_run(run_id=run_id)
    db_name = run.get("arango_database")
    if db_name:
        set_active_arango_database(str(db_name))
    else:
        _apply_run_arango_database(run_id, run=run)
    return get_db()


def mark_run_cancelled(run_id: str, message: str = "Cancelled by user") -> None:
    """Best-effort cancelled marker for UI polls and run record."""
    update_run_progress_cache(
        run_id,
        status="cancelled",
        message=message,
    )
    try:
        _apply_run_arango_database(run_id)
        db = get_db()
        col = _get_collection(db, "extraction_runs")
        run = doc_get(col, run_id) or {}
        stats = dict(run.get("stats") or {})
        stats["preparation_message"] = message
        stats["preparation_updated_at"] = time.time()
        col.update(
            {
                "_key": run_id,
                "status": "cancelled",
                "completed_at": time.time(),
                "stats": stats,
            }
        )
    except Exception:
        log.exception("could not mark extraction run cancelled", extra={"run_id": run_id})


def cancel_extraction_run(run_id: str) -> dict[str, Any]:
    """Request cooperative cancellation of an active extraction run."""
    cached = get_cached_run_progress(run_id)
    status = cached.get("status") if cached else None
    if status is None:
        _apply_run_arango_database(run_id)
        db = get_db()
        col = _get_collection(db, "extraction_runs")
        run = doc_get(col, run_id)
        if run is None:
            raise NotFoundError(f"Extraction run '{run_id}' not found")
        status = run.get("status")

    if status == "cancelled":
        return {"run_id": run_id, "status": "cancelled", "already_cancelled": True}
    if status not in CANCELLABLE_RUN_STATUSES:
        raise ConflictError(f"Cannot cancel run in status '{status}'")

    request_extraction_cancel(run_id)
    mark_run_cancelled(run_id)
    return {"run_id": run_id, "status": "cancelled"}


def mark_run_preparation_failed(run_id: str, message: str) -> None:
    """Best-effort failure marker when the prepare thread crashes before inner handlers run."""
    update_run_progress_cache(
        run_id,
        status="failed",
        message=message,
        stats_patch={"errors": [message]},
    )
    try:
        _apply_run_arango_database(run_id)
        db = get_db()
        col = _get_collection(db, "extraction_runs")
        run = doc_get(col, run_id) or {}
        stats = dict(run.get("stats") or {})
        errors = list(stats.get("errors") or [])
        errors.append(message)
        stats["errors"] = errors
        stats["preparation_message"] = message
        stats["preparation_updated_at"] = time.time()
        col.update(
            {
                "_key": run_id,
                "status": "failed",
                "completed_at": time.time(),
                "stats": stats,
            }
        )
    except Exception:
        log.exception("could not mark extraction run failed", extra={"run_id": run_id})


def schedule_execute_run(
    *,
    run_id: str,
    document_ids: list[str],
    config_overrides: dict[str, Any] | None = None,
    domain_ontology_ids: list[str] | None = None,
    target_ontology_id: str | None = None,
    run_record: dict[str, Any] | None = None,
) -> None:
    """Start LangGraph extraction on a daemon thread (prep in ``prepare_arango`` node).

    ``asyncio.create_task`` is unreliable under uvicorn multi-worker: the coroutine
    may never run after the HTTP response returns. A dedicated thread with its own
    event loop keeps the run alive independent of the request worker.
    """
    def _runner() -> None:
        # M2M: pin this app's service principal bearer for all gateway calls in this thread
        # (app.yaml arango-gateway-app-invoke CAN_USE). Eager snapshot avoids ContextVar gaps
        # across asyncio.to_thread workers.
        sp_auth = pin_outbound_service_principal_bearer()
        active_db = (
            str(run_record["arango_database"])
            if run_record and run_record.get("arango_database")
            else None
        )
        if active_db:
            set_active_arango_database(active_db)
        try:
            from app.services.preparation_heartbeat import (
                start_preparation_session,
                stop_preparation_session,
            )

            start_preparation_session(run_id)
            update_run_progress_cache(
                run_id,
                stage=PREPARATION_STAGE_GATEWAY_HEALTH,
                message="Worker scheduled — LangGraph prepare_arango starting…",
            )
            try:
                asyncio.run(
                    execute_run(
                        run_id=run_id,
                        document_ids=document_ids,
                        config_overrides=config_overrides,
                        domain_ontology_ids=domain_ontology_ids,
                        target_ontology_id=target_ontology_id,
                    )
                )
            except ExtractionCancelled:
                log.info("extraction run cancelled", extra={"run_id": run_id})
                mark_run_cancelled(run_id)
            except Exception as exc:
                log.exception("execute_run thread failed", extra={"run_id": run_id})
                mark_run_preparation_failed(run_id, str(exc))
            finally:
                stop_preparation_session(run_id)
                clear_extraction_cancel(run_id)
                with contextlib.suppress(Exception):
                    cached = get_cached_run_progress(run_id)
                    if cached and cached.get("status") in (
                        "completed",
                        "failed",
                        "cancelled",
                    ):
                        drop_run_progress_cache(run_id)
        finally:
            release_outbound_service_principal_bearer(sp_auth)
            if active_db:
                clear_active_arango_database()

    thread = threading.Thread(
        target=_runner,
        name=f"extract-run-{run_id[:16]}",
        daemon=True,
    )
    thread.start()
    log.info("scheduled execute_run thread", extra={"run_id": run_id})


def schedule_prepare_and_execute_run(
    *,
    run_id: str,
    document_ids: list[str],
    config_overrides: dict[str, Any] | None = None,
    domain_ontology_ids: list[str] | None = None,
    target_ontology_id: str | None = None,
    run_record: dict[str, Any] | None = None,
) -> None:
    """Deprecated alias — prep now runs inside the ``prepare_arango`` LangGraph node."""
    schedule_execute_run(
        run_id=run_id,
        document_ids=document_ids,
        config_overrides=config_overrides,
        domain_ontology_ids=domain_ontology_ids,
        target_ontology_id=target_ontology_id,
        run_record=run_record,
    )


def update_run_preparation(
    db: StandardDatabase,
    run_id: str,
    *,
    stage: str,
    message: str,
    progress: dict[str, Any] | None = None,
) -> None:
    """Persist low-overhead preparation progress on the run record (polled by UI)."""
    update_run_progress_cache(
        run_id,
        stage=stage,
        message=message,
        progress=progress,
    )
    # Schema migrations and the post-schema launch transition hold the gateway for
    # minutes; heartbeats must not queue competing writes on the same client
    # (120s timeout freezes the UI poll).
    if stage in (PREPARATION_STAGE_SCHEMA, PREPARATION_STAGE_LAUNCHING):
        return
    try:
        col = _get_collection(db, "extraction_runs")
        run = doc_get(col, run_id)
        if run is None:
            return
        stats = dict(run.get("stats") or {})
        stats["preparation_stage"] = stage
        stats["preparation_message"] = message
        stats["preparation_updated_at"] = time.time()
        if progress is not None:
            stats["preparation_progress"] = progress
        col.update({"_key": run_id, "stats": stats})
    except Exception:
        log.warning(
            "arango preparation update failed (file cache already updated)",
            extra={"run_id": run_id, "stage": stage},
            exc_info=True,
        )


def build_run_record(
    *,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    config_overrides: dict[str, Any] | None = None,
    domain_ontology_ids: list[str] | None = None,
    target_ontology_id: str | None = None,
    arango_database: str | None = None,
    initial_status: str = "running",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build an extraction run document without touching the gateway."""
    doc_ids = _normalize_doc_ids(document_id=document_id, document_ids=document_ids)
    if not doc_ids:
        raise ValueError("At least one document ID is required")

    resolved_run_id = run_id or _generate_run_id()
    now = time.time()

    is_tier2 = bool(domain_ontology_ids)
    prompt_version = "tier2_standard" if is_tier2 else "tier1_standard"

    run_record: dict[str, Any] = {
        "_key": resolved_run_id,
        "doc_id": doc_ids[0],
        "doc_ids": doc_ids,
        "model": settings.llm_extraction_model,
        "prompt_version": prompt_version,
        "started_at": now,
        "completed_at": None,
        "status": initial_status,
        "stats": {
            "passes": settings.extraction_passes,
            "consistency_threshold": settings.extraction_consistency_threshold,
            "token_usage": {},
            "errors": [],
            "step_logs": [],
        },
    }

    if initial_status == "preparing":
        run_record["stats"]["preparation_stage"] = "queued"
        run_record["stats"]["preparation_message"] = (
            "Queued — gateway health check, persist run in Arango, then UC chunks via proxy"
        )
        run_record["stats"]["preparation_updated_at"] = now

    if domain_ontology_ids:
        run_record["domain_ontology_ids"] = domain_ontology_ids
    if target_ontology_id:
        run_record["target_ontology_id"] = target_ontology_id
    if arango_database:
        run_record["arango_database"] = arango_database

    if config_overrides:
        run_record["stats"].update(config_overrides)

    return run_record


def begin_extraction_run(
    *,
    document_ids: list[str],
    config_overrides: dict[str, Any] | None = None,
    domain_ontology_ids: list[str] | None = None,
    target_ontology_id: str | None = None,
    arango_database: str | None = None,
) -> dict[str, Any]:
    """Return run metadata immediately; persist to Arango in the prepare thread.

    Seeds the shared file progress cache so Diagnostics can poll before gateway insert.
    """
    resolved_database = resolve_arango_database_name(arango_database)
    run_record = build_run_record(
        document_ids=document_ids,
        config_overrides=config_overrides,
        domain_ontology_ids=domain_ontology_ids,
        target_ontology_id=target_ontology_id,
        arango_database=resolved_database,
        initial_status="preparing",
    )
    run_record["stats"]["preparation_message"] = (
        f"Queued — database {resolved_database} (created automatically if missing), "
        "then LangGraph prepare_arango (gateway, UC chunks, schema)"
    )
    run_id = str(run_record["_key"])
    seed_run_progress(
        run_id,
        status="preparing",
        stage="queued",
        message=str(run_record["stats"]["preparation_message"]),
        stats=run_record["stats"],
        doc_id=run_record.get("doc_id"),
        doc_ids=run_record.get("doc_ids"),
        target_ontology_id=run_record.get("target_ontology_id"),
        arango_database=run_record.get("arango_database"),
        pending_run_record=run_record,
    )
    schedule_execute_run(
        run_id=run_id,
        document_ids=document_ids,
        config_overrides=config_overrides,
        domain_ontology_ids=domain_ontology_ids,
        target_ontology_id=target_ontology_id,
        run_record=run_record,
    )
    log.info(
        "extraction run scheduled (fast start)",
        extra={"run_id": run_id, "doc_ids": document_ids, "status": "preparing"},
    )
    return run_record


def create_run_record(
    db: StandardDatabase | None = None,
    *,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    config_overrides: dict[str, Any] | None = None,
    domain_ontology_ids: list[str] | None = None,
    target_ontology_id: str | None = None,
    arango_database: str | None = None,
    initial_status: str = "running",
) -> dict[str, Any]:
    """Create an extraction run record (synchronous gateway insert).

    Accepts either ``document_id`` (single, backward compat) or
    ``document_ids`` (multi-doc).  Both are normalized into
    ``doc_ids: list[str]`` on the stored record.
    """
    if db is None:
        db = get_db()

    if arango_database:
        resolved_database = validate_arango_database_name(arango_database)
    else:
        resolved_database = effective_arango_database_name()
    if db is None:
        set_active_arango_database(resolved_database)
        db = get_db()
    run_record = build_run_record(
        document_id=document_id,
        document_ids=document_ids,
        config_overrides=config_overrides,
        domain_ontology_ids=domain_ontology_ids,
        target_ontology_id=target_ontology_id,
        arango_database=resolved_database,
        initial_status=initial_status,
    )
    doc_ids = list(run_record.get("doc_ids") or [])
    run_id = str(run_record["_key"])

    col = _get_collection(db, "extraction_runs")
    col.insert(run_record)

    if initial_status == "preparing":
        seed_run_progress(
            run_id,
            status="preparing",
            stage="queued",
            message=str(run_record["stats"]["preparation_message"]),
            stats=run_record["stats"],
        )

    chunk_count = 0
    if initial_status != "preparing":
        chunk_count = sum(len(_load_document_chunks(db, did)) for did in doc_ids)
    log.info(
        "extraction run created",
        extra={
            "run_id": run_id,
            "doc_ids": doc_ids,
            "chunk_count": chunk_count,
            "status": initial_status,
        },
    )

    return run_record


def _normalize_doc_ids(
    *,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
) -> list[str]:
    """Merge singular/plural document ID args into a deduplicated list.

    Returns an empty list (instead of raising) when called from
    ``execute_run`` with both args ``None`` — the caller fills in from the
    stored run record.
    """
    ids: list[str] = []
    if document_ids:
        ids.extend(document_ids)
    if document_id and document_id not in ids:
        ids.insert(0, document_id)
    return ids


async def execute_run(
    run_id: str,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    config_overrides: dict[str, Any] | None = None,
    event_callback: Any | None = None,
    domain_ontology_ids: list[str] | None = None,
    target_ontology_id: str | None = None,
    preloaded_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute the extraction pipeline for an existing run record.

    Designed to run as a background task after the HTTP response is sent.
    When no event_callback is provided, defaults to publishing events
    over WebSocket via the extraction event bus.
    """
    if event_callback is None:
        from app.api.ws_extraction import publish_event

        event_callback = publish_event

    cached = get_cached_run_progress(run_id)
    pending_run_record = (cached or {}).get("pending_run_record") if cached else None
    deferred_prep = bool(
        cached
        and cached.get("status") == "preparing"
        and isinstance(pending_run_record, dict)
    )

    db: StandardDatabase | None = None
    col: StandardCollection | None = None
    run_record: dict[str, Any] | None = None

    if deferred_prep:
        run_record = dict(pending_run_record)
    else:
        _apply_run_arango_database(run_id)
        db = get_db()
        col = _get_collection(db, "extraction_runs")
        run_record = doc_get(col, run_id)
        if run_record is None:
            raise NotFoundError(f"Extraction run '{run_id}' not found")

    doc_ids = _normalize_doc_ids(document_id=document_id, document_ids=document_ids)
    if not doc_ids:
        doc_ids = run_record.get("doc_ids") or []
        if not doc_ids and run_record.get("doc_id"):
            doc_ids = [run_record["doc_id"]]

    if target_ontology_id is None:
        target_ontology_id = run_record.get("target_ontology_id")

    if domain_ontology_ids is None:
        domain_ontology_ids = run_record.get("domain_ontology_ids")

    domain_context = ""
    if domain_ontology_ids and not deferred_prep and db is not None:
        try:
            from app.services.ontology_context import serialize_multi_domain_context

            domain_context = serialize_multi_domain_context(
                db,
                ontology_ids=domain_ontology_ids,
            )
            log.info(
                "serialized domain context for tier 2",
                extra={
                    "run_id": run_id,
                    "ontology_ids": domain_ontology_ids,
                    "context_length": len(domain_context),
                },
            )
        except Exception:
            log.warning(
                "failed to serialize domain context, falling back to tier 1",
                exc_info=True,
                extra={"run_id": run_id},
            )

    if not deferred_prep:
        try:
            from app.services.uc_entity_selections import format_uc_entities_for_prompt

            uc_block = format_uc_entities_for_prompt()
            if uc_block:
                domain_context = (
                    f"{domain_context}\n\n{uc_block}" if domain_context else uc_block
                )
        except Exception:
            log.debug("UC entity selection context unavailable", exc_info=True)

    chunks_from_uc = preloaded_chunks is not None or deferred_prep
    if preloaded_chunks is not None:
        chunks = list(preloaded_chunks)
    elif deferred_prep:
        chunks = []
    else:
        assert db is not None
        chunks = []
        for did in doc_ids:
            chunks.extend(_load_document_chunks(db, did))

    primary_doc_id = doc_ids[0] if doc_ids else "unknown"

    if not chunks and not deferred_prep:
        source = "UC volume" if chunks_from_uc else "Arango"
        raise ValueError(
            f"No chunks found in {source} for document(s) {doc_ids} — "
            "complete Parse & Chunk first"
        )

    check_extraction_cancelled(run_id)

    publish = event_callback
    if event_callback is not None:

        async def _persisting_event_callback(**kwargs: Any) -> None:
            check_extraction_cancelled(run_id)
            await event_callback(**kwargs)
            event_type = kwargs.get("event_type")
            step = kwargs.get("step")
            if not step or event_type not in (
                "step_started",
                "step_completed",
                "step_failed",
            ):
                return
            step_str = str(step)
            if event_type == "step_started":
                await asyncio.to_thread(
                    update_run_current_step,
                    run_id,
                    step_str,
                    message=f"Agent step: {step_str}",
                )
            data = kwargs.get("data")
            if event_type == "step_completed" and isinstance(data, dict) and data:
                from app.services.run_agent_diagnostics import record_live_run_metrics

                await asyncio.to_thread(record_live_run_metrics, run_id, data)
            await asyncio.to_thread(
                record_run_step_event,
                run_id,
                event_type=str(event_type),
                step=step_str,
                error=str(kwargs["error"]) if kwargs.get("error") else None,
            )

        publish = _persisting_event_callback

    from app.services.run_agent_diagnostics import init_agent_diagnostics

    prep_message = (
        "LangGraph prepare_arango (gateway, UC chunks, schema)…"
        if deferred_prep
        else f"LangGraph pipeline running ({len(chunks)} chunks)"
    )
    await asyncio.to_thread(
        init_agent_diagnostics,
        run_id,
        message=prep_message,
    )
    await asyncio.to_thread(
        update_run_current_step,
        run_id,
        "prepare_arango",
        message=prep_message,
    )

    pipeline_metadata: dict[str, Any] = {
        "domain_ontology_ids": domain_ontology_ids or [],
        "doc_ids": doc_ids,
        "target_ontology_id": target_ontology_id,
        "chunks_from_uc": chunks_from_uc,
    }
    if deferred_prep:
        pipeline_metadata["pending_run_record"] = run_record
        if run_record.get("arango_database"):
            pipeline_metadata["arango_database"] = run_record["arango_database"]

    final_state: dict[str, Any] = {}
    try:
        final_state = cast(
            "dict[str, Any]",
            await run_pipeline(
                run_id=run_id,
                document_id=primary_doc_id,
                chunks=chunks,
                event_callback=publish,
                domain_context=domain_context,
                domain_ontology_ids=domain_ontology_ids or [],
                doc_ids=doc_ids,
                target_ontology_id=target_ontology_id,
                chunks_from_uc=chunks_from_uc,
                cancel_check=lambda: is_extraction_cancelled(run_id),
                pipeline_metadata=pipeline_metadata,
            ),
        )

        prep_result = final_state.get("prepare_arango_result") or {}
        if prep_result.get("status") == "failed":
            if col is None:
                _apply_run_arango_database(run_id, run=run_record)
                db = get_db()
                col = _get_collection(db, "extraction_runs")
            failed_at = time.time()
            col.update(
                {
                    "_key": run_id,
                    "status": "failed",
                    "completed_at": failed_at,
                    "stats": {
                        **run_record["stats"],
                        "errors": final_state.get("errors", []),
                        "step_logs": [
                            _serialize_step_log(sl) for sl in final_state.get("step_logs", [])
                        ],
                        "finalize_graph": final_state.get("finalize_graph_result") or {},
                    },
                }
            )
            return doc_get(col, run_id) or {}

        if col is None:
            _apply_run_arango_database(run_id, run=run_record)
            db = get_db()
            col = _get_collection(db, "extraction_runs")
            refreshed = doc_get(col, run_id)
            if refreshed:
                run_record = refreshed

        completed_at = time.time()
        status = "completed"
        if final_state.get("errors"):
            status = "completed_with_errors"
        if final_state.get("consistency_result") is None:
            status = "failed"

        consistency = final_state.get("consistency_result")
        classes_extracted = len(consistency.classes) if consistency else 0
        properties_extracted = (
            sum(_count_class_properties(c) for c in consistency.classes) if consistency else 0
        )
        pass_results = final_state.get("extraction_passes", [])
        pass_agreement_rate = _compute_agreement_rate(pass_results) if pass_results else 0.0
        if pass_agreement_rate == 0.0:
            for sl in final_state.get("step_logs", []):
                sl_dict = (
                    sl
                    if isinstance(sl, dict)
                    else (sl.model_dump() if hasattr(sl, "model_dump") else dict(sl))
                )
                if sl_dict.get("step") == "consistency_checker":
                    rates = sl_dict.get("metadata", {}).get("agreement_rates", {})
                    if rates:
                        pass_agreement_rate = sum(rates.values()) / len(rates)
                    break

        # Belief-revision summary (IBR.12). The belief_revision agent
        # writes one summary dict to state with counts of touchpoints,
        # verdicts, auto-applied / flagged revisions, and LLM calls --
        # OR a ``status="skipped"`` payload (with ``reason`` like
        # ``feature_flag_off`` / ``no_extraction_results``) when the
        # phase short-circuited. Either way we surface it on the run
        # so the Pipeline Monitor can render the IBR tiles without
        # parsing audit step_logs. ``None`` here means the agent never
        # ran (e.g. pipeline crashed before the IBR node fired); the
        # frontend renders that as a neutral "no data" tile rather
        # than zeros.
        belief_revision_summary = final_state.get("belief_revision_summary")
        finalize_result = final_state.get("finalize_graph_result") or {}
        ontology_id_from_finalize = finalize_result.get("ontology_id")

        update_data: dict[str, Any] = {
            "completed_at": completed_at,
            "status": status,
            "stats": {
                **run_record["stats"],
                "token_usage": final_state.get("token_usage", {}),
                "errors": final_state.get("errors", []),
                "step_logs": [_serialize_step_log(sl) for sl in final_state.get("step_logs", [])],
                "classes_extracted": classes_extracted,
                "properties_extracted": properties_extracted,
                "pass_agreement_rate": pass_agreement_rate,
                "belief_revision": belief_revision_summary,
                "finalize_graph": finalize_result,
            },
        }
        if ontology_id_from_finalize:
            update_data["ontology_id"] = ontology_id_from_finalize
        col.update({"_key": run_id, **update_data})

        if (
            final_state.get("consistency_result")
            and finalize_result.get("status") == "completed"
        ):
            task = asyncio.create_task(
                _run_qualitative_eval_background(
                    run_id=run_id,
                    final_state=final_state,
                )
            )
            _BACKGROUND_TASKS.add(task)
            task.add_done_callback(_BACKGROUND_TASKS.discard)

    except ExtractionCancelled:
        mark_run_cancelled(run_id)
        if col is None:
            _apply_run_arango_database(run_id, run=run_record)
            db = get_db()
            col = _get_collection(db, "extraction_runs")
        updated = doc_get(col, run_id)
        return updated or {}
    except Exception as exc:
        log.exception("extraction pipeline failed", extra={"run_id": run_id})
        if col is None:
            _apply_run_arango_database(run_id, run=run_record)
            db = get_db()
            col = _get_collection(db, "extraction_runs")
        partial_logs: list[dict[str, Any]] = []
        partial_belief_revision: dict[str, Any] | None = None
        if final_state and final_state.get("step_logs"):
            partial_logs = [_serialize_step_log(sl) for sl in final_state["step_logs"]]
        if final_state:
            # If the IBR node ran before the crash (or was skipped via
            # feature-flag), preserve its summary on the failed run so
            # the Pipeline Monitor can still show "IBR ran: N
            # touchpoints, then pipeline failed". ``None`` means the
            # crash happened before the IBR node fired.
            partial_belief_revision = final_state.get("belief_revision_summary")
        col.update(
            {
                "_key": run_id,
                "status": "failed",
                "completed_at": time.time(),
                "stats": {
                    **run_record["stats"],
                    "errors": [str(exc)],
                    "step_logs": partial_logs,
                    "token_usage": (final_state.get("token_usage", {}) if final_state else {}),
                    "belief_revision": partial_belief_revision,
                },
            }
        )

    updated = doc_get(col, run_id)
    return updated or {}


async def _run_qualitative_eval_background(
    *,
    run_id: str,
    final_state: dict[str, Any],
) -> None:
    """Fire-and-forget qualitative evaluation — never blocks staging."""
    try:
        consistency_result = final_state.get("consistency_result")
        if consistency_result is None or not getattr(consistency_result, "classes", None):
            return

        classes = consistency_result.classes
        chunks = final_state.get("document_chunks", [])
        strategy_config = final_state.get("strategy_config", {})
        batch_size = strategy_config.get("chunk_batch_size", 5)

        result = await run_qualitative_evaluation(
            classes=classes,
            chunks=chunks,
            batch_size=batch_size,
        )

        # Persist to extraction run record
        db = get_db()
        if db.has_collection("extraction_runs"):
            col = db.collection("extraction_runs")
            run_doc = doc_get(col, run_id)
            if run_doc:
                stats = run_doc.get("stats", {})
                stats["qualitative_evaluation"] = result
                col.update({"_key": run_id, "stats": stats})
                log.info("qualitative evaluation stored for run %s", run_id)

    except Exception:
        log.warning(
            "background qualitative evaluation failed for run %s",
            run_id,
            exc_info=True,
        )


async def start_run(
    db: StandardDatabase | None = None,
    *,
    document_id: str,
    config_overrides: dict[str, Any] | None = None,
    event_callback: Any | None = None,
    target_ontology_id: str | None = None,
    domain_ontology_ids: list[str] | None = None,
    arango_database: str | None = None,
) -> dict[str, Any]:
    """Create and execute an extraction run synchronously (legacy helper)."""
    if db is None:
        db = get_db()
    run_record = create_run_record(
        db,
        document_id=document_id,
        config_overrides=config_overrides,
        target_ontology_id=target_ontology_id,
        domain_ontology_ids=domain_ontology_ids,
        arango_database=arango_database,
    )
    return await execute_run(
        run_id=run_record["_key"],
        document_ids=[document_id],
        config_overrides=config_overrides,
        event_callback=event_callback,
        target_ontology_id=target_ontology_id,
        domain_ontology_ids=domain_ontology_ids,
    )


def get_run(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Get extraction run details."""
    if db is not None:
        try:
            if db.has_collection("extraction_runs"):
                run = doc_get(db.collection("extraction_runs"), run_id)
                if run is not None:
                    return enrich_run_for_client(run)
        except Exception:
            log.debug(
                "get_run lookup failed in provided database",
                extra={"run_id": run_id},
                exc_info=True,
            )
        log.debug(
            "get_run missed in provided database — searching extraction databases",
            extra={"run_id": run_id},
        )

    _apply_run_arango_database(run_id)
    try:
        database = get_db()
        col = _get_collection(database, "extraction_runs")
        run = doc_get(col, run_id)
        if run is not None:
            return enrich_run_for_client(run)
    except Exception:
        log.debug("get_run primary database lookup failed", extra={"run_id": run_id}, exc_info=True)

    from app.db.arango_database_names import discover_extraction_databases
    from app.db.client import clear_active_arango_database

    for db_name in discover_extraction_databases():
        set_active_arango_database(db_name)
        try:
            database = get_db()
            if not database.has_collection("extraction_runs"):
                continue
            run = doc_get(database.collection("extraction_runs"), run_id)
            if run is not None:
                enriched = enrich_run_for_client(run)
                enriched.setdefault("arango_database", db_name)
                return enriched
        except Exception:
            log.debug("get_run search missed %s", db_name, exc_info=True)
        finally:
            clear_active_arango_database()

    raise NotFoundError(f"Extraction run '{run_id}' not found")


def enrich_run_for_client(run: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``stats`` preparation fields for polling UIs."""
    out = dict(run)
    stats = out.get("stats")
    if not isinstance(stats, dict):
        return out
    for key in (
        "preparation_stage",
        "preparation_message",
        "preparation_updated_at",
        "preparation_progress",
        "agent_diagnostics",
        "token_usage",
        "model",
    ):
        if key not in out and stats.get(key) is not None:
            out[key] = stats[key]
    errors = stats.get("errors")
    if isinstance(errors, list) and errors and "preparation_errors" not in out:
        out["preparation_errors"] = errors
    return out


def build_preparing_status_stub(
    run_id: str,
    *,
    message: str | None = None,
) -> dict[str, Any]:
    """Synthetic snapshot when the run is accepted but not yet in cache or Arango."""
    now = time.time()
    return build_run_status_snapshot(
        {
            "_key": run_id,
            "status": "preparing",
            "stats": {
                "preparation_stage": "queued",
                "preparation_message": message
                or "Run accepted — waiting for gateway persist (poll again shortly)…",
                "preparation_updated_at": now,
                "errors": [],
                "step_logs": [],
            },
        }
    )


def read_run_status_poll_fast(run_id: str) -> dict[str, Any] | None:
    """File-cache read only — safe to call on the asyncio event loop (no gateway I/O)."""
    cached = get_cached_run_progress(run_id)
    if cached is None:
        return None
    return build_run_status_snapshot(cached)


def fetch_run_status_from_gateway(run_id: str) -> dict[str, Any]:
    """Best-effort Arango read with short timeout; never 404 while run may still be preparing."""
    timeout = float(os.environ.get("RUN_STATUS_GATEWAY_TIMEOUT_SECONDS", "8"))

    def _fetch() -> dict[str, Any]:
        return get_run(run_id=run_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_fetch)
        try:
            run = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            cached = get_cached_run_progress(run_id)
            if cached is not None:
                return build_run_status_snapshot(cached)
            raise ServiceBusyError(
                "Arango gateway busy — status poll will retry",
                details={"run_id": run_id},
            ) from exc
        except NotFoundError:
            cached = get_cached_run_progress(run_id)
            if cached is not None:
                return build_run_status_snapshot(cached)
            return build_preparing_status_stub(run_id)
    return build_run_status_snapshot(run)


def get_run_status_for_poll(run_id: str) -> dict[str, Any]:
    """Return run snapshot for UI polls — cache only, never blocks on Arango gateway."""
    fast = read_run_status_poll_fast(run_id)
    if fast is not None:
        return fast
    return build_preparing_status_stub(
        run_id,
        message="Run accepted — status cache warming (no gateway call on this poll)…",
    )


def build_run_status_snapshot(run: dict[str, Any]) -> dict[str, Any]:
    """Small payload for high-frequency UI polls (diagnostics + agent DAG fallback)."""
    enriched = enrich_run_for_client(run)
    stats = enriched.get("stats") if isinstance(enriched.get("stats"), dict) else {}
    step_logs = stats.get("step_logs")
    if not isinstance(step_logs, list):
        step_logs = []
    errors = stats.get("errors")
    if not isinstance(errors, list):
        errors = []
    agent_diagnostics = stats.get("agent_diagnostics")
    token_usage = stats.get("token_usage")
    return {
        "_key": enriched.get("_key"),
        "status": enriched.get("status"),
        "started_at": enriched.get("started_at"),
        "completed_at": enriched.get("completed_at"),
        "doc_id": enriched.get("doc_id"),
        "doc_ids": enriched.get("doc_ids"),
        "target_ontology_id": enriched.get("target_ontology_id"),
        "arango_database": enriched.get("arango_database"),
        "ontology_id": enriched.get("ontology_id"),
        "preparation_stage": enriched.get("preparation_stage"),
        "preparation_message": enriched.get("preparation_message"),
        "preparation_updated_at": enriched.get("preparation_updated_at"),
        "preparation_progress": enriched.get("preparation_progress"),
        "preparation_errors": enriched.get("preparation_errors"),
        "current_step": stats.get("current_step"),
        "agent_diagnostics": agent_diagnostics if isinstance(agent_diagnostics, dict) else None,
        "token_usage": token_usage if isinstance(token_usage, dict) else None,
        "model": enriched.get("model") or stats.get("model"),
        "stats": {
            "step_logs": step_logs[-40:],
            "errors": errors[:20],
            "preparation_stage": stats.get("preparation_stage"),
            "preparation_message": stats.get("preparation_message"),
            "preparation_updated_at": stats.get("preparation_updated_at"),
            "preparation_progress": stats.get("preparation_progress"),
            "agent_diagnostics": agent_diagnostics if isinstance(agent_diagnostics, dict) else None,
            "token_usage": token_usage if isinstance(token_usage, dict) else None,
            "current_step": stats.get("current_step"),
        },
    }


def update_run_current_step(run_id: str, step: str, *, message: str | None = None) -> None:
    """Best-effort progress marker while LangGraph runs (polled by UI)."""
    now = time.time()
    msg = message or f"Agent step: {step}"
    update_run_progress_cache(
        run_id,
        status="running",
        stage="launching_pipeline",
        message=msg,
        stats_patch={"current_step": step},
        touch_session=False,
    )
    try:
        db = get_db()
        col = _get_collection(db, "extraction_runs")
        run = doc_get(col, run_id)
        if run is None:
            return
        stats = dict(run.get("stats") or {})
        stats["current_step"] = step
        stats["preparation_message"] = msg
        stats["preparation_updated_at"] = now
        col.update({"_key": run_id, "stats": stats})
    except Exception:
        log.debug("could not update run current_step", extra={"run_id": run_id, "step": step})


def record_run_step_event(
    run_id: str,
    *,
    event_type: str,
    step: str,
    error: str | None = None,
) -> None:
    """Persist incremental step_logs so REST polls can drive the agent DAG."""
    from app.services.run_agent_diagnostics import sync_agent_diagnostics_from_step_logs
    from app.services.run_progress_cache import get_cached_run_progress

    now = time.time()
    cached = get_cached_run_progress(run_id)
    cached_stats = dict(cached.get("stats") or {}) if cached else {}
    logs: list[dict[str, Any]] = [
        dict(entry) for entry in (cached_stats.get("step_logs") or []) if isinstance(entry, dict)
    ]
    idx = next((i for i, entry in enumerate(logs) if entry.get("step") == step), None)
    current_step = cached_stats.get("current_step")

    if event_type == "step_started":
        patch: dict[str, Any] = {"step": step, "status": "running", "started_at": now}
        if idx is not None:
            logs[idx] = {**logs[idx], **patch}
        else:
            logs.append(patch)
        current_step = step
    elif event_type == "step_completed":
        patch = {"step": step, "status": "completed", "completed_at": now}
        if idx is not None:
            merged = {**logs[idx], **patch}
            merged.setdefault("started_at", now)
            logs[idx] = merged
        else:
            logs.append({**patch, "started_at": now})
    elif event_type == "step_failed":
        patch = {
            "step": step,
            "status": "failed",
            "completed_at": now,
            "error": error or "step failed",
        }
        if idx is not None:
            logs[idx] = {**logs[idx], **patch}
        else:
            logs.append({**patch, "started_at": now})
    else:
        return

    logs = logs[-60:]
    sync_agent_diagnostics_from_step_logs(
        run_id,
        logs,
        current_step=str(current_step) if current_step else step,
    )
    update_run_progress_cache(
        run_id,
        status="running",
        message=f"Agent step: {step} ({event_type.replace('step_', '')})",
        touch_session=False,
    )

    try:
        db = get_db()
        col = _get_collection(db, "extraction_runs")
        run = doc_get(col, run_id)
        if run is None:
            return
        stats = dict(run.get("stats") or {})
        stats["step_logs"] = logs
        stats["current_step"] = current_step
        stats["preparation_updated_at"] = now
        col.update({"_key": run_id, "stats": stats})
    except Exception:
        log.debug(
            "could not record run step event",
            extra={"run_id": run_id, "step": step, "event_type": event_type},
        )


def list_runs(
    db: StandardDatabase | None = None,
    *,
    cursor: str | None = None,
    limit: int = 25,
    status: str | None = None,
) -> PaginatedResponse[dict[str, Any]]:
    """List extraction runs with cursor-based pagination."""
    if db is not None:
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        return paginate(
            db,
            collection="extraction_runs",
            sort_field="started_at",
            sort_order="desc",
            limit=limit,
            cursor=cursor,
            filters=filters if filters else None,
            extra_aql='FILTER NOT STARTS_WITH(doc._key, "results_")',
        )

    from app.db.arango_database_names import discover_extraction_databases
    from app.db.client import clear_active_arango_database

    filters = {"status": status} if status else None
    merged: list[dict[str, Any]] = []
    for db_name in discover_extraction_databases():
        set_active_arango_database(db_name)
        try:
            database = get_db()
            if not database.has_collection("extraction_runs"):
                continue
            page = paginate(
                database,
                collection="extraction_runs",
                sort_field="started_at",
                sort_order="desc",
                limit=max(limit, 25),
                cursor=None,
                filters=filters,
                extra_aql='FILTER NOT STARTS_WITH(doc._key, "results_")',
            )
            for row in page.data:
                row.setdefault("arango_database", db_name)
                merged.append(row)
        except Exception:
            log.debug("list_runs skipped database %s", db_name, exc_info=True)
        finally:
            clear_active_arango_database()

    merged.sort(key=lambda row: float(row.get("started_at") or 0), reverse=True)
    if cursor:
        try:
            cursor_val, cursor_key = decode_cursor(cursor)
            merged = [
                row
                for row in merged
                if (float(row.get("started_at") or 0), str(row.get("_key")))
                < (float(cursor_val), cursor_key)
            ]
        except Exception:
            log.debug("invalid list_runs cursor", exc_info=True)
    page_data = merged[:limit]
    next_cursor = None
    if len(merged) > limit and page_data:
        last = page_data[-1]
        next_cursor = encode_cursor(last.get("started_at"), str(last.get("_key")))
    return PaginatedResponse(data=page_data, next_cursor=next_cursor, has_more=next_cursor is not None)


def get_run_steps(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    """Get per-agent step logs for a run."""
    run = get_run(db, run_id=run_id)
    logs = run.get("stats", {}).get("step_logs", [])
    return cast(list[dict[str, Any]], logs)


def get_run_results(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Get extraction results (stored classes and properties) for a run."""
    if db is None:
        db = get_db()

    run = get_run(db, run_id=run_id)
    results_key = f"results_{run_id}"

    col = _get_collection(db, "extraction_runs")
    results_doc = doc_get(col, results_key)

    if results_doc and "extraction_result" in results_doc:
        return cast(dict[str, Any], results_doc["extraction_result"])

    return {
        "classes": [],
        "properties": [],
        "run_id": run_id,
        "status": run.get("status", "unknown"),
    }


async def retry_run(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    event_callback: Any | None = None,
) -> dict[str, Any]:
    """Retry a failed extraction run."""
    if db is None:
        db = get_db()

    run = get_run(db, run_id=run_id)
    if run["status"] not in ("failed", "completed_with_errors"):
        raise ValueError(f"Can only retry failed runs, current status: {run['status']}")

    doc_ids = run.get("doc_ids") or [run["doc_id"]]
    return await start_run(
        db,
        document_id=doc_ids[0],
        event_callback=event_callback,
        target_ontology_id=run.get("target_ontology_id"),
        domain_ontology_ids=run.get("domain_ontology_ids"),
        arango_database=run.get("arango_database"),
    )


def get_run_cost(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    include_quality_metrics: bool = True,
) -> dict[str, Any]:
    """Get token usage and estimated cost for a run.

    Also includes quality indicators (avg_confidence, completeness_pct)
    when the run has an associated ontology.

    Active runs are served from the progress cache (no gateway read) so
    Metrics cards can poll live during LangGraph execution.
    """
    from app.services.run_progress_cache import get_cached_run_progress

    cached = get_cached_run_progress(run_id)
    cached_status = str(cached.get("status") or "") if cached else ""
    if cached and cached_status in ("running", "paused", "preparing"):
        return _run_cost_from_progress_cache(
            run_id,
            cached,
            include_quality_metrics=False,
        )

    if db is None:
        db = get_db()

    try:
        run = get_run(db, run_id=run_id)
    except NotFoundError:
        if cached:
            return _run_cost_from_progress_cache(
                run_id,
                cached,
                include_quality_metrics=include_quality_metrics,
            )
        raise

    payload = _run_cost_from_run_record(
        db,
        run_id=run_id,
        run=run,
        include_quality_metrics=include_quality_metrics,
    )
    if cached:
        payload = _merge_live_cost_fields(payload, cached)
    return payload


def _run_cost_from_progress_cache(
    run_id: str,
    cached: dict[str, Any],
    *,
    include_quality_metrics: bool,
) -> dict[str, Any]:
    """Build cost/metrics payload from file cache only."""
    stats = dict(cached.get("stats") or {})
    model = stats.get("model") or settings.llm_extraction_model
    agent_diag = dict(stats.get("agent_diagnostics") or {})
    token_usage = dict(stats.get("token_usage") or {})

    prompt_tokens = max(
        int(token_usage.get("prompt_tokens", 0)),
        int(agent_diag.get("prompt_tokens", 0)),
    )
    completion_tokens = max(
        int(token_usage.get("completion_tokens", 0)),
        int(agent_diag.get("completion_tokens", 0)),
    )
    total_tokens = max(
        int(token_usage.get("total_tokens", 0)),
        int(agent_diag.get("total_tokens", 0)),
        prompt_tokens + completion_tokens,
    )

    rates = _MODEL_TOKEN_RATES_PER_MILLION.get(model, {"input": 3.0, "output": 15.0})
    estimated_cost = (prompt_tokens / 1_000_000) * rates["input"] + (
        completion_tokens / 1_000_000
    ) * rates["output"]

    started = cached.get("started_at") or agent_diag.get("agent_started_at") or 0
    completed = cached.get("completed_at") or 0
    now = time.time()
    if started and not completed:
        duration_ms = int((now - float(started)) * 1000)
    elif started and completed:
        duration_ms = int((float(completed) - float(started)) * 1000)
    else:
        duration_ms = 0

    llm_calls = int(agent_diag.get("llm_calls", 0))
    agent_started = agent_diag.get("agent_started_at") or started
    llm_calls_per_min: float | None = None
    if llm_calls > 0 and agent_started:
        elapsed_min = max((now - float(agent_started)) / 60.0, 1.0 / 60.0)
        llm_calls_per_min = round(llm_calls / elapsed_min, 2)

    running_steps = agent_diag.get("running_steps")
    agents_running = len(running_steps) if isinstance(running_steps, list) else 0

    return {
        "run_id": run_id,
        "status": cached.get("status"),
        "live": cached_status_is_live(cached.get("status")),
        "model": model,
        "total_duration_ms": duration_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": round(estimated_cost, 6),
        "classes_extracted": int(stats.get("classes_extracted", 0)),
        "properties_extracted": int(stats.get("properties_extracted", 0)),
        "pass_agreement_rate": float(stats.get("pass_agreement_rate", 0.0)),
        "merge_candidates_found": int(stats.get("merge_candidates_found", 0)),
        "token_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
        "input_cost_per_million_tokens": rates["input"],
        "output_cost_per_million_tokens": rates["output"],
        "avg_confidence": None,
        "completeness_pct": None,
        "belief_revision": stats.get("belief_revision"),
        "llm_calls": llm_calls,
        "llm_calls_per_min": llm_calls_per_min,
        "prompt_chars": int(agent_diag.get("prompt_chars", 0)),
        "agents_running": agents_running,
        "current_step": stats.get("current_step"),
        "agent_diagnostics": agent_diag or None,
        "step_logs": stats.get("step_logs", [])[-12:],
    }


def cached_status_is_live(status: Any) -> bool:
    return str(status or "") in ("running", "paused", "preparing")


def _merge_live_cost_fields(payload: dict[str, Any], cached: dict[str, Any]) -> dict[str, Any]:
    """Overlay cache-backed live counters onto a gateway-sourced cost payload."""
    live = _run_cost_from_progress_cache(
        str(payload.get("run_id") or cached.get("_key") or ""),
        cached,
        include_quality_metrics=False,
    )
    merged = dict(payload)
    for key in (
        "classes_extracted",
        "properties_extracted",
        "pass_agreement_rate",
        "merge_candidates_found",
        "llm_calls",
        "llm_calls_per_min",
        "prompt_chars",
        "agents_running",
        "current_step",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_cost",
        "belief_revision",
        "agent_diagnostics",
        "step_logs",
    ):
        live_val = live.get(key)
        if live_val is None:
            continue
        if key in ("classes_extracted", "properties_extracted", "merge_candidates_found", "llm_calls"):
            merged[key] = max(int(merged.get(key, 0)), int(live_val))
        elif key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            merged[key] = max(int(merged.get(key, 0)), int(live_val))
        elif key == "pass_agreement_rate":
            if float(live_val) > 0:
                merged[key] = live_val
        elif key == "estimated_cost":
            merged[key] = max(float(merged.get(key, 0)), float(live_val))
        else:
            merged[key] = live_val
    if cached_status_is_live(cached.get("status")):
        merged["live"] = True
        merged["status"] = cached.get("status")
    return merged


def _run_cost_from_run_record(
    db: StandardDatabase,
    *,
    run_id: str,
    run: dict[str, Any],
    include_quality_metrics: bool,
) -> dict[str, Any]:
    """Gateway-backed cost payload for completed or idle runs."""
    stats = run.get("stats", {})
    token_usage = stats.get("token_usage", {})
    model = run.get("model", settings.llm_extraction_model)

    prompt_tokens = token_usage.get("prompt_tokens", 0)
    completion_tokens = token_usage.get("completion_tokens", 0)
    total_tokens = token_usage.get("total_tokens", prompt_tokens + completion_tokens)
    rates = _MODEL_TOKEN_RATES_PER_MILLION.get(
        model,
        {"input": 3.0, "output": 15.0},
    )
    estimated_cost = (prompt_tokens / 1_000_000) * rates["input"] + (
        completion_tokens / 1_000_000
    ) * rates["output"]

    started = run.get("started_at", 0)
    completed = run.get("completed_at", 0)
    duration_ms = int((completed - started) * 1000) if started and completed else 0

    avg_confidence: float | None = None
    completeness_pct: float | None = None
    ontology_id = run.get("ontology_id") or run.get("target_ontology_id")
    if not ontology_id and db.has_collection("ontology_registry"):
        matches = list(
            run_aql(
                db,
                "FOR o IN ontology_registry "
                "FILTER o.extraction_run_id == @rid "
                "LIMIT 1 RETURN o._key",
                bind_vars={"rid": run_id},
            )
        )
        if matches:
            ontology_id = matches[0]
    if not ontology_id and db.has_collection("ontology_registry"):
        doc_ids = run.get("doc_ids") or ([run["doc_id"]] if run.get("doc_id") else [])
        if doc_ids:
            matches = list(
                run_aql(
                    db,
                    "FOR o IN ontology_registry "
                    "FILTER o.source_document_id IN @dids OR o.source_document IN @dids "
                    "LIMIT 1 RETURN o._key",
                    bind_vars={"dids": doc_ids},
                )
            )
            if matches:
                ontology_id = matches[0]

    if include_quality_metrics and ontology_id:
        try:
            from app.services.quality_metrics import compute_ontology_quality

            oq = compute_ontology_quality(db, ontology_id, include_estimated_cost=False)
            avg_confidence = oq.get("avg_confidence")
            completeness_pct = oq.get("completeness")
        except Exception:
            log.debug("quality metrics unavailable for run %s", run_id, exc_info=True)

    return {
        "run_id": run_id,
        "status": run.get("status"),
        "live": False,
        "model": model,
        "total_duration_ms": duration_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": round(estimated_cost, 6),
        "classes_extracted": stats.get("classes_extracted", 0),
        "properties_extracted": stats.get("properties_extracted", 0),
        "pass_agreement_rate": stats.get("pass_agreement_rate", 0.0),
        "merge_candidates_found": int(stats.get("merge_candidates_found", 0)),
        "token_usage": token_usage,
        "input_cost_per_million_tokens": rates["input"],
        "output_cost_per_million_tokens": rates["output"],
        "avg_confidence": avg_confidence,
        "completeness_pct": completeness_pct,
        "belief_revision": stats.get("belief_revision"),
        "llm_calls": 0,
        "llm_calls_per_min": None,
        "prompt_chars": 0,
        "agents_running": 0,
        "current_step": stats.get("current_step"),
        "agent_diagnostics": stats.get("agent_diagnostics"),
        "step_logs": (stats.get("step_logs") or [])[-12:],
    }


def _load_document_chunks(
    db: StandardDatabase,
    document_id: str,
) -> list[dict[str, Any]]:
    """Load chunks for a document from the database."""
    if not db.has_collection("chunks"):
        return []

    query = """\
FOR chunk IN chunks
  FILTER chunk.doc_id == @doc_id
  SORT chunk.chunk_index ASC
  RETURN chunk"""

    return list(run_aql(db, query, bind_vars={"doc_id": document_id}))


def _store_results(
    db: StandardDatabase,
    *,
    run_id: str,
    result: Any,
) -> None:
    """Persist extraction results alongside the run record."""
    col = _get_collection(db, "extraction_runs")
    results_key = f"results_{run_id}"

    result_data = result.model_dump() if hasattr(result, "model_dump") else result
    doc = {
        "_key": results_key,
        "run_id": run_id,
        "extraction_result": result_data,
        "stored_at": time.time(),
    }

    try:
        col.insert(doc)
    except Exception:
        col.update({"_key": results_key, **doc})


def _count_class_properties(cls: Any) -> int:
    """Count total properties (attributes + relationships), with legacy fallback."""
    if hasattr(cls, "attributes"):
        n = len(cls.attributes) + len(cls.relationships)
        if n > 0:
            return n
        return len(cls.properties)
    if isinstance(cls, dict):
        attrs = cls.get("attributes", [])
        rels = cls.get("relationships", [])
        if attrs or rels:
            return len(attrs) + len(rels)
        return len(cls.get("properties", []))
    return 0


_XSD_TYPES = {
    "xsd:string",
    "xsd:integer",
    "xsd:int",
    "xsd:decimal",
    "xsd:float",
    "xsd:double",
    "xsd:boolean",
    "xsd:date",
    "xsd:dateTime",
    "xsd:time",
    "xsd:anyURI",
    "xsd:long",
    "xsd:short",
    "xsd:byte",
    "xsd:nonNegativeInteger",
    "xsd:positiveInteger",
    "xsd:duration",
    "xsd:gYear",
    "xsd:gMonth",
    "xsd:base64Binary",
    "xsd:hexBinary",
    "xsd:normalizedString",
    "xsd:token",
}


def _is_object_property(
    range_val: str,
    property_type: str,
    uri_to_key: dict[str, str],
    class_keys: dict[str, str],
) -> bool:
    """Determine if a property is an object property (relationship between classes)."""
    if property_type == "object":
        return True
    if property_type == "datatype":
        return False
    if range_val.startswith("http"):
        return True
    if range_val.lower() in _XSD_TYPES or range_val.lower().startswith("xsd:"):
        return False
    if "#" in range_val:
        frag = range_val.split("#")[-1]
        if frag in class_keys or range_val in uri_to_key:
            return True
        return True
    frag = range_val.split("/")[-1]
    return frag in class_keys or range_val in class_keys


def _infer_property_type(
    range_val: str,
    property_type: str,
    uri_to_key: dict[str, str],
    class_keys: dict[str, str],
) -> str:
    """Return 'owl:ObjectProperty' or 'owl:DatatypeProperty'."""
    if _is_object_property(range_val, property_type, uri_to_key, class_keys):
        return "owl:ObjectProperty"
    return "owl:DatatypeProperty"


def _materialize_to_graph(
    db: StandardDatabase,
    *,
    run_id: str,
    document_id: str,
    ontology_id: str,
    result: Any,
    faithfulness_scores: dict[str, float] | None = None,
    validity_scores: dict[str, float] | None = None,
) -> None:
    """Write extracted classes/properties into PGT-aligned graph collections.

    Attributes  → ``ontology_datatype_properties`` + ``rdfs_domain`` edges
    Relationships → ``ontology_object_properties`` + ``rdfs_domain`` + ``rdfs_range_class`` edges

    Backward compat: if a class has only legacy ``properties`` (no ``attributes``
    / ``relationships``), they are split using ``_is_object_property()``.
    """
    now = time.time()
    classes = result.classes if hasattr(result, "classes") else result.get("classes", [])

    vertex_collections = (
        "ontology_classes",
        "ontology_datatype_properties",
        "ontology_object_properties",
    )
    edge_collections = (
        "rdfs_domain",
        "rdfs_range_class",
        "subclass_of",
        "extracted_from",
        "has_chunk",
        "produced_by",
    )
    for col_name in (*vertex_collections, *edge_collections):
        if not db.has_collection(col_name):
            db.create_collection(col_name, edge=(col_name in edge_collections))

    cls_col = db.collection("ontology_classes")
    dt_prop_col = db.collection("ontology_datatype_properties")
    obj_prop_col = db.collection("ontology_object_properties")
    rdfs_domain_col = db.collection("rdfs_domain")
    rdfs_range_col = db.collection("rdfs_range_class")
    extracted_col = db.collection("extracted_from")
    subclass_col = db.collection("subclass_of")

    class_keys: dict[str, str] = {}  # label -> key (legacy name; really label_to_key)
    uri_to_key: dict[str, str] = {}  # full URI -> key
    fragment_to_key: dict[str, str] = {}  # URI fragment -> key (for resolver tier 2)
    class_parent_uris: list[tuple[str, str, list[dict[str, Any]]]] = []
    deferred_rels: list[dict[str, Any]] = []

    for cls in classes:
        cls_data = cls.model_dump() if hasattr(cls, "model_dump") else dict(cls)
        label = cls_data.get("label", "Unknown")
        uri = cls_data.get("uri", f"http://example.org/ontology#{label.replace(' ', '')}")
        key = uri.split("#")[-1].split("/")[-1]

        class_doc = {
            "_key": key,
            "label": label,
            "uri": uri,
            "description": cls_data.get("description", ""),
            "ontology_id": ontology_id,
            "extraction_run_id": run_id,
            "confidence": cls_data.get("confidence", 0.0),
            "faithfulness_score": cls_data.get("faithfulness_score"),
            "semantic_validity_score": cls_data.get("semantic_validity_score"),
            "evidence": cls_data.get("evidence", []),
            "parent_evidence": cls_data.get("parent_evidence", []),
            "rdf_type": "owl:Class",
            "created": now,
            "expired": NEVER_EXPIRES,
        }
        try:
            cls_col.insert(class_doc, overwrite=True)
        except Exception as exc:
            log.warning("class insert failed for %s: %s", key, exc)
        class_keys[label] = key
        uri_to_key[uri] = key
        # Index by URI fragment (post ``#`` / final path segment) so the
        # range resolver can find a class by fragment even when its label
        # diverges from the URI suffix (the common LLM case).
        fragment_to_key[key] = key

        parent_uri = cls_data.get("parent_uri")
        if parent_uri:
            class_parent_uris.append((key, parent_uri, cls_data.get("parent_evidence", [])))

        # --- PGT-aligned property handling ---
        attributes: list[dict[str, Any]] = cls_data.get("attributes", [])
        relationships: list[dict[str, Any]] = cls_data.get("relationships", [])

        # Backward compat: split legacy properties when PGT fields are absent
        if not attributes and not relationships:
            for prop in cls_data.get("properties", []):
                prop_range = prop.get("range", "xsd:string")
                prop_type = prop.get("property_type", "")
                if _is_object_property(prop_range, prop_type, uri_to_key, class_keys):
                    relationships.append(
                        {
                            "uri": prop.get("uri", ""),
                            "label": prop.get("label", ""),
                            "description": prop.get("description", ""),
                            "target_class_uri": prop_range,
                            "confidence": prop.get("confidence", 0.0),
                            "evidence": prop.get("evidence", []),
                        }
                    )
                else:
                    attributes.append(
                        {
                            "uri": prop.get("uri", ""),
                            "label": prop.get("label", ""),
                            "description": prop.get("description", ""),
                            "range_datatype": prop_range,
                            "confidence": prop.get("confidence", 0.0),
                            "evidence": prop.get("evidence", []),
                        }
                    )

        # Attributes → ontology_datatype_properties + rdfs_domain
        for attr in attributes:
            attr_label = attr.get("label", "unknown_attr")
            prop_key = f"{key}_{attr_label.replace(' ', '_').lower()}"
            attr_uri = attr.get("uri") or f"{uri.rsplit('#', 1)[0]}#{attr_label.replace(' ', '')}"
            prop_doc = {
                "_key": prop_key,
                "uri": attr_uri,
                "label": attr_label,
                "description": attr.get("description", ""),
                "range_datatype": attr.get("range_datatype", "xsd:string"),
                "ontology_id": ontology_id,
                "confidence": attr.get("confidence", 0.0),
                "evidence": attr.get("evidence", []),
                "created": now,
                "expired": NEVER_EXPIRES,
            }
            try:
                dt_prop_col.insert(prop_doc, overwrite=True)
            except Exception as exc:
                log.warning("datatype property insert failed for %s: %s", prop_key, exc)

            # Idempotent: a re-extraction of the same class from a
            # second document used to silently insert a duplicate
            # rdfs_domain edge here, leaving N>1 live rows for the
            # same logical (datatype-property, class) pair. See
            # ``app.db.utils.insert_temporal_edge_if_absent`` for the
            # full bug-history rationale.
            with contextlib.suppress(Exception):
                insert_temporal_edge_if_absent(
                    db,
                    rdfs_domain_col,
                    from_id=f"ontology_datatype_properties/{prop_key}",
                    to_id=f"ontology_classes/{key}",
                    ontology_id=ontology_id,
                    now=now,
                )

        # Collect relationships for deferred processing (need all class_keys first)
        for rel in relationships:
            rel_label = rel.get("label", "unknown_rel")
            prop_key = f"{key}_{rel_label.replace(' ', '_').lower()}"
            rel_uri = rel.get("uri") or f"{uri.rsplit('#', 1)[0]}#{rel_label.replace(' ', '')}"
            deferred_rels.append(
                {
                    "domain_key": key,
                    "prop_key": prop_key,
                    "uri": rel_uri,
                    "label": rel_label,
                    "description": rel.get("description", ""),
                    "target_class_uri": rel.get("target_class_uri", ""),
                    # Forward an LLM-supplied target_class_label if present
                    # (the prompts don't request it today, but the resolver
                    # accepts it and a future prompt change can start emitting
                    # it without further pipeline work).
                    "target_class_label": rel.get("target_class_label"),
                    "confidence": rel.get("confidence", 0.0),
                    "evidence": rel.get("evidence", []),
                }
            )

        with contextlib.suppress(Exception):
            extracted_col.insert(
                {
                    "_from": f"ontology_classes/{key}",
                    "_to": f"documents/{document_id}",
                    "run_id": run_id,
                    "ontology_id": ontology_id,
                    "created": now,
                    "expired": NEVER_EXPIRES,
                }
            )

    # subclass_of edges
    for child_key, parent_uri, parent_evidence in class_parent_uris:
        parent_key = uri_to_key.get(parent_uri)
        if not parent_key:
            parent_frag = parent_uri.split("#")[-1].split("/")[-1]
            parent_key = class_keys.get(parent_frag) or class_keys.get(parent_uri)
        if parent_key and parent_key != child_key:
            with contextlib.suppress(Exception):
                subclass_col.insert(
                    {
                        "_from": f"ontology_classes/{child_key}",
                        "_to": f"ontology_classes/{parent_key}",
                        "ontology_id": ontology_id,
                        "evidence": parent_evidence,
                        "created": now,
                        "expired": NEVER_EXPIRES,
                    }
                )
        elif parent_key == child_key:
            log.warning("skipping self-referential subclass_of: %s", child_key)

    # Deferred relationships → ontology_object_properties + rdfs_domain + rdfs_range_class
    #
    # Resolution uses ``edge_repair.resolve_range_class`` which tries four
    # ordered tiers (uri / fragment / label / miss). The raw
    # ``target_class_uri`` and the humanised ``target_class_label`` are
    # persisted on every property document regardless of resolution success,
    # so a later repair pass (or a curator) can always recover the LLM's
    # original intent. Misses now log a WARNING (the silent failure mode
    # was the original orphan-property bug).
    for rel in deferred_rels:
        target_uri = rel["target_class_uri"]
        resolution = resolve_range_class(
            target_uri,
            uri_to_key=uri_to_key,
            fragment_to_key=fragment_to_key,
            label_to_key=class_keys,
            target_label=rel.get("target_class_label"),
        )

        prop_key = rel["prop_key"]
        prop_doc = {
            "_key": prop_key,
            "uri": rel["uri"],
            "label": rel["label"],
            "description": rel["description"],
            "ontology_id": ontology_id,
            "confidence": rel["confidence"],
            "evidence": rel.get("evidence", []),
            # Persist the LLM's range intent even when resolution missed,
            # so future repair / re-extraction can pick up where this run
            # left off.
            "target_class_uri": target_uri,
            "target_class_label": resolution.target_label,
            "created": now,
            "expired": NEVER_EXPIRES,
        }
        try:
            obj_prop_col.insert(prop_doc, overwrite=True)
        except Exception as exc:
            log.warning("object property insert failed for %s: %s", prop_key, exc)

        domain_key = rel["domain_key"]
        # Idempotent (see datatype-property branch above for the bug
        # rationale). The previous bare insert here was the dominant
        # source of duplicate live rdfs_domain edges in the wild --
        # an audit on WTW Ontology found 6 duplicated pairs, all
        # from object-property re-extraction across documents.
        try:
            insert_temporal_edge_if_absent(
                db,
                rdfs_domain_col,
                from_id=f"ontology_object_properties/{prop_key}",
                to_id=f"ontology_classes/{domain_key}",
                ontology_id=ontology_id,
                now=now,
            )
        except Exception as exc:
            log.warning(
                "rdfs_domain insert failed for object property %s -> %s: %s",
                prop_key,
                domain_key,
                exc,
            )

        if resolution.class_key:
            if resolution.tier == "label":
                # Tier 4 hit -- the URI didn't match anything but the
                # humanised label matched a class. Worth an INFO line so
                # we can monitor how often the resolver is bailing out
                # the LLM in the wild.
                log.info(
                    "resolved object-property %s range via label match: "
                    "target_uri=%r -> class_key=%r (label=%r)",
                    prop_key,
                    target_uri,
                    resolution.class_key,
                    resolution.target_label,
                )
            # Idempotent: live audit on WTW Ontology found zero
            # duplicate pairs here (rdfs_range_class is more
            # brittle to re-resolve, so the second extraction
            # often skipped this insert anyway), but the fix is
            # cheap and the contract is the same as rdfs_domain --
            # one live edge per logical (property, range-class)
            # pair, no exceptions.
            try:
                insert_temporal_edge_if_absent(
                    db,
                    rdfs_range_col,
                    from_id=f"ontology_object_properties/{prop_key}",
                    to_id=f"ontology_classes/{resolution.class_key}",
                    ontology_id=ontology_id,
                    now=now,
                )
            except Exception as exc:
                log.warning(
                    "rdfs_range_class insert failed for object property %s -> %s: %s",
                    prop_key,
                    resolution.class_key,
                    exc,
                )
        else:
            # All four resolver tiers missed. The property still exists with
            # its rdfs_domain edge and persisted target_class_{uri,label},
            # so post-hoc repair (``edge_repair.repair_orphan_object_property_ranges``)
            # can still recover it. But surface it now -- the original bug
            # was that this case was silent.
            log.warning(
                "could not resolve target_class_uri for object property %s "
                "(target_uri=%r, target_label=%r); property persisted as "
                "orphan and will be a candidate for edge_repair",
                prop_key,
                target_uri,
                resolution.target_label,
            )

    # has_chunk edges
    if db.has_collection("has_chunk"):
        has_chunk_col = db.collection("has_chunk")
    else:
        # ``create_collection`` is typed as ``StandardCollection | AsyncJob |
        # BatchJob | None`` because the same handle is reused for batch / async
        # execution; on a ``StandardDatabase`` only ``StandardCollection`` is
        # ever returned for a successful create.
        has_chunk_col = cast(
            StandardCollection,
            db.create_collection("has_chunk", edge=True),
        )
    if db.has_collection("chunks"):
        chunk_docs = list(
            run_aql(
                db,
                "FOR c IN chunks FILTER c.doc_id == @doc_id RETURN c._key",
                bind_vars={"doc_id": document_id},
            )
        )
        for chunk_key in chunk_docs:
            with contextlib.suppress(Exception):
                has_chunk_col.insert(
                    {
                        "_from": f"documents/{document_id}",
                        "_to": f"chunks/{chunk_key}",
                        "ontology_id": ontology_id,
                        "run_id": run_id,
                        "created": now,
                        "expired": NEVER_EXPIRES,
                    },
                    overwrite=True,
                )

    _recompute_multi_signal_confidence(
        db,
        ontology_id=ontology_id,
        classes=classes,
        class_keys=class_keys,
        uri_to_key=uri_to_key,
        faithfulness_scores=faithfulness_scores,
        validity_scores=validity_scores,
    )

    log.info(
        "materialized extraction to graph",
        extra={"run_id": run_id, "classes": len(class_keys), "ontology_id": ontology_id},
    )


def _recompute_multi_signal_confidence(
    db: StandardDatabase,
    *,
    ontology_id: str,
    classes: list[Any],
    class_keys: dict[str, str],
    uri_to_key: dict[str, str],
    faithfulness_scores: dict[str, float] | None = None,
    validity_scores: dict[str, float] | None = None,
    property_agreement_scores: dict[str, float] | None = None,
) -> None:
    """Second pass: recompute confidence for each class using multi-signal scoring.

    Runs AFTER all classes, properties, and edges have been materialized so
    that structural connectivity is fully available.

    Uses ``rdfs_domain`` to count properties per class (split by source
    collection) and ``rdfs_range_class`` / ``extends_domain`` for lateral
    connectivity.
    """
    if faithfulness_scores is None:
        faithfulness_scores = {}
    if validity_scores is None:
        validity_scores = {}
    if property_agreement_scores is None:
        property_agreement_scores = {}

    cls_col = db.collection("ontology_classes")
    subclass_col = db.collection("subclass_of")
    extracted_col = db.collection("extracted_from")

    has_rdfs_domain = db.has_collection("rdfs_domain")
    has_rdfs_range = db.has_collection("rdfs_range_class")
    has_extends = db.has_collection("extends_domain")

    all_descriptions: list[str] = []
    for cls in classes:
        cls_data = cls.model_dump() if hasattr(cls, "model_dump") else dict(cls)
        all_descriptions.append(cls_data.get("description", ""))

    for cls in classes:
        cls_data = cls.model_dump() if hasattr(cls, "model_dump") else dict(cls)
        label = cls_data.get("label", "Unknown")
        uri = cls_data.get("uri", "")
        key = uri_to_key.get(uri) or class_keys.get(label)
        if not key:
            continue

        agreement_ratio = cls_data.get("confidence", 0.5)
        description = cls_data.get("description", "")
        class_id = f"ontology_classes/{key}"

        faithfulness = faithfulness_scores.get(
            uri,
            cls_data.get("llm_confidence", 0.5),
        )
        semantic_validity = validity_scores.get(uri, 0.5)
        prop_agreement = property_agreement_scores.get(
            uri,
            cls_data.get("property_agreement", 1.0),
        )

        # Count properties via rdfs_domain edges pointing TO this class,
        # grouped by source collection (datatype vs object).
        datatype_count = 0
        object_count = 0
        if has_rdfs_domain:
            prop_type_counts = list(
                run_aql(
                    db,
                    "FOR e IN rdfs_domain "
                    "FILTER e._to == @cls_id AND e.ontology_id == @oid "
                    "LET col = PARSE_IDENTIFIER(e._from).collection "
                    "COLLECT type = col WITH COUNT INTO cnt "
                    "RETURN {type, cnt}",
                    bind_vars={"cls_id": class_id, "oid": ontology_id},
                )
            )
            for row in prop_type_counts:
                t = row.get("type", "")
                cnt = row.get("cnt", 0)
                if t == "ontology_object_properties":
                    object_count += cnt
                elif t == "ontology_datatype_properties":
                    datatype_count += cnt

        has_parent = bool(
            list(
                run_aql(
                    db,
                    "FOR e IN @@col FILTER e._from == @cls_id AND e.ontology_id == @oid "
                    "LIMIT 1 RETURN true",
                    bind_vars={
                        "@col": subclass_col.name,
                        "cls_id": class_id,
                        "oid": ontology_id,
                    },
                )
            )
        )

        has_children = bool(
            list(
                run_aql(
                    db,
                    "FOR e IN @@col FILTER e._to == @cls_id AND e.ontology_id == @oid "
                    "LIMIT 1 RETURN true",
                    bind_vars={
                        "@col": subclass_col.name,
                        "cls_id": class_id,
                        "oid": ontology_id,
                    },
                )
            )
        )

        # Lateral connectivity: class is domain of an object property, or
        # range of one, or linked via extends_domain.
        has_lateral = object_count > 0
        if not has_lateral and has_rdfs_range:
            has_lateral = bool(
                list(
                    run_aql(
                        db,
                        "FOR e IN rdfs_range_class "
                        "FILTER e._to == @cls_id AND e.ontology_id == @oid "
                        "LIMIT 1 RETURN true",
                        bind_vars={"cls_id": class_id, "oid": ontology_id},
                    )
                )
            )
        if not has_lateral and has_extends:
            has_lateral = bool(
                list(
                    run_aql(
                        db,
                        "FOR e IN extends_domain "
                        "FILTER (e._from == @cls_id OR e._to == @cls_id) "
                        "AND e.ontology_id == @oid "
                        "LIMIT 1 RETURN true",
                        bind_vars={"cls_id": class_id, "oid": ontology_id},
                    )
                )
            )

        provenance_count_result = list(
            run_aql(
                db,
                "FOR e IN @@col FILTER e._from == @cls_id COLLECT WITH COUNT INTO cnt RETURN cnt",
                bind_vars={
                    "@col": extracted_col.name,
                    "cls_id": class_id,
                },
            )
        )
        provenance_count = provenance_count_result[0] if provenance_count_result else 0

        new_confidence = compute_class_confidence(
            agreement_ratio=agreement_ratio,
            faithfulness=faithfulness,
            semantic_validity=semantic_validity,
            datatype_property_count=datatype_count,
            object_property_count=object_count,
            has_parent=has_parent,
            has_children=has_children,
            has_lateral_edges=has_lateral,
            description=description,
            all_descriptions=all_descriptions,
            provenance_count=provenance_count,
            property_agreement=prop_agreement,
        )

        try:
            cls_col.update(
                {
                    "_key": key,
                    "confidence": new_confidence,
                    "faithfulness_score": faithfulness,
                    "semantic_validity_score": semantic_validity,
                }
            )
        except Exception as exc:
            log.warning("confidence update failed for %s: %s", key, exc)


def _create_produced_by_edge(
    db: StandardDatabase,
    *,
    ontology_id: str,
    run_id: str,
) -> None:
    """Create a produced_by edge from ontology_registry → extraction_runs."""
    try:
        for col_name in ("produced_by",):
            if not db.has_collection(col_name):
                db.create_collection(col_name, edge=True)

        col = db.collection("produced_by")
        col.insert(
            {
                "_from": f"ontology_registry/{ontology_id}",
                "_to": f"extraction_runs/{run_id}",
                "created": time.time(),
                "expired": NEVER_EXPIRES,
            },
            overwrite=True,
        )
        log.info(
            "created produced_by edge",
            extra={"ontology_id": ontology_id, "run_id": run_id},
        )
    except Exception:
        log.warning("produced_by edge creation failed", exc_info=True)


def _update_existing_ontology(
    db: StandardDatabase,
    *,
    ontology_id: str,
    run_id: str,
    result: Any,
) -> str | None:
    """Update an existing ontology registry entry for incremental extraction.

    Increments class/property counts and updates the timestamp.
    Returns the ontology_id on success, None on failure.
    """
    try:
        from app.db import registry_repo

        entry = registry_repo.get_registry_entry(ontology_id)
        if entry is None:
            log.warning(
                "target ontology %s not found, falling back to new registration",
                ontology_id,
            )
            return None

        classes = result.classes if hasattr(result, "classes") else result.get("classes", [])
        new_class_count = len(classes)
        new_prop_count = sum(_count_class_properties(c) for c in classes)

        registry_repo.update_registry_entry(
            ontology_id,
            {
                "class_count": entry.get("class_count", 0) + new_class_count,
                "property_count": entry.get("property_count", 0) + new_prop_count,
                "extraction_run_id": run_id,
            },
        )
        log.info(
            "updated existing ontology for incremental extraction",
            extra={"ontology_id": ontology_id, "run_id": run_id, "new_classes": new_class_count},
        )
        return ontology_id
    except Exception:
        log.warning("failed to update existing ontology %s", ontology_id, exc_info=True)
        return None


def _auto_register_ontology(
    db: StandardDatabase,
    *,
    run_id: str,
    document_id: str,
    result: Any,
) -> str | None:
    """Register an ontology in the library after successful extraction.

    Returns the ontology_id (_key) on success, None on failure.
    """
    try:
        from app.db import documents_repo, registry_repo

        doc = documents_repo.get_document(document_id)
        filename = doc.get("filename", "unknown") if doc else "unknown"
        name = filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()

        classes = result.classes if hasattr(result, "classes") else result.get("classes", [])
        class_count = len(classes)

        entry = registry_repo.create_registry_entry(
            {
                "name": name,
                "description": f"Ontology extracted from {filename}",
                "tier": "local",
                "source_document_id": document_id,
                "extraction_run_id": run_id,
                "class_count": class_count,
                "property_count": sum(_count_class_properties(c) for c in classes),
                "namespace": "http://example.org/ontology#",
            }
        )
        ontology_id_raw = entry.get("_key", run_id)
        ontology_key = str(ontology_id_raw)
        log.info(
            "auto-registered ontology",
            extra={
                "run_id": run_id,
                "ontology_name": name,
                "classes": class_count,
                "ontology_id": ontology_key,
            },
        )
        return ontology_key
    except Exception:
        log.warning("auto-registration failed — ontology can be registered manually", exc_info=True)
        return None


def _compute_agreement_rate(pass_results: list[Any]) -> float:
    """Compute cross-pass agreement rate as fraction of overlapping class URIs."""
    if len(pass_results) < 2:
        return 1.0
    uri_sets: list[set[str]] = []
    for pr in pass_results:
        classes = pr.classes if hasattr(pr, "classes") else pr.get("classes", [])
        uris = set()
        for c in classes:
            uri = c.uri if hasattr(c, "uri") else c.get("uri", "")
            if uri:
                uris.add(uri)
        uri_sets.append(uris)
    if not uri_sets or all(len(s) == 0 for s in uri_sets):
        return 0.0
    intersection = uri_sets[0]
    union = set(uri_sets[0])
    for s in uri_sets[1:]:
        intersection = intersection & s
        union = union | s
    return len(intersection) / len(union) if union else 0.0


def _serialize_step_log(step_log: dict[str, Any] | Any) -> dict[str, Any]:
    """Serialize a step log entry for storage."""
    if isinstance(step_log, dict):
        return cast(dict[str, Any], step_log)
    if hasattr(step_log, "model_dump"):
        return cast(dict[str, Any], step_log.model_dump())
    return cast(dict[str, Any], dict(step_log))
