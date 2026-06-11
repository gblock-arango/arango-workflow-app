"""Arango + UC preparation for the LangGraph ``prepare_arango`` node.

All gateway health checks, run persistence, UC chunk load, and schema migrations
run here so Diagnostics can poll the same preparation stages as before.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.db.types import StandardDatabase
from app.services.extraction_gateway_checkpoints import (
    connect_arango_checkpoint,
    persist_run_record_checkpoint,
    probe_gateway_health_checkpoint,
)
from app.services.extraction_materialize import load_chunks_for_extraction
from app.services.run_progress_cache import get_cached_run_progress, update_run_progress_cache

log = logging.getLogger(__name__)

PREPARATION_STAGE_LOADING_UC = "loading_uc_chunks"
PREPARATION_STAGE_SCHEMA = "schema_migrations"
PREPARATION_STAGE_LAUNCHING = "launching_pipeline"


def _resolve_pending_run_record(
    run_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    pending = metadata.get("pending_run_record")
    if isinstance(pending, dict) and pending.get("_key"):
        return pending
    cached = get_cached_run_progress(run_id)
    if cached and isinstance(cached.get("pending_run_record"), dict):
        return cached["pending_run_record"]
    return None


def run_prepare_arango_workflow(
    *,
    run_id: str,
    doc_ids: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Execute full extraction prep; returns chunks and summary for pipeline state."""
    from app.services.extraction import check_extraction_cancelled, update_run_preparation

    errors: list[str] = []
    chunks: list[dict[str, Any]] = []
    arango_database = metadata.get("arango_database")
    if not arango_database:
        cached = get_cached_run_progress(run_id)
        if cached and cached.get("arango_database"):
            arango_database = cached["arango_database"]

    pending_run_record = _resolve_pending_run_record(run_id, metadata)

    def _wrap_cancellable(callback: Any) -> Any:
        def on_progress(message: str, progress: dict[str, Any] | None = None) -> None:
            check_extraction_cancelled(run_id)
            callback(message, progress)

        return on_progress

    db: StandardDatabase | None = None
    col: Any = None

    try:
        check_extraction_cancelled(run_id)
        probe_gateway_health_checkpoint(run_id)

        check_extraction_cancelled(run_id)
        db, col = connect_arango_checkpoint(run_id, str(arango_database) if arango_database else None)

        check_extraction_cancelled(run_id)
        persist_run_record_checkpoint(db, col, run_id, pending_run_record or {})

        total = len(doc_ids)
        for index, doc_id in enumerate(doc_ids, start=1):

            def on_uc_progress(message: str, progress: dict[str, Any] | None = None) -> None:
                merged: dict[str, Any] = {
                    "doc_id": doc_id,
                    "doc_index": index,
                    "doc_total": total,
                }
                if progress:
                    merged.update(progress)
                update_run_preparation(
                    db,
                    run_id,
                    stage=PREPARATION_STAGE_LOADING_UC,
                    message=f"({index}/{total}) {message}",
                    progress=merged,
                )

            on_uc_progress = _wrap_cancellable(on_uc_progress)
            on_uc_progress(f"Loading chunks from UC volume for {doc_id}")
            doc_chunks = load_chunks_for_extraction(doc_id, on_progress=on_uc_progress)
            chunks.extend(doc_chunks)

        if not chunks:
            errors.append("No document chunks available for extraction")

        def on_schema_progress(message: str, progress: dict[str, Any] | None = None) -> None:
            merged: dict[str, Any] = {"phase": "schema_migrations"}
            if progress:
                merged.update(progress)
            update_run_preparation(
                db,
                run_id,
                stage=PREPARATION_STAGE_SCHEMA,
                message=message,
                progress=merged,
            )

        on_schema_progress = _wrap_cancellable(on_schema_progress)
        on_schema_progress(
            "Starting ontology schema migrations through gateway…",
            {"phase": "schema_migrations"},
        )

        from app.services.schema_bootstrap import ensure_ontology_schema

        schema_result = ensure_ontology_schema(db=db, on_progress=on_schema_progress)

        missing = [
            name
            for name in (
                "extraction_runs",
                "documents",
                "chunks",
                "ontology_classes",
                "ontology_datatype_properties",
                "ontology_object_properties",
                "ontology_registry",
            )
            if not db.has_collection(name)
        ]
        if missing:
            errors.append(f"Missing required collections: {', '.join(missing)}")

        launch_message = (
            f"Schema complete — loaded {len(chunks)} chunks from UC, "
            "starting LangGraph agent pipeline"
        )
        update_run_progress_cache(
            run_id,
            status="running",
            stage=PREPARATION_STAGE_LAUNCHING,
            message=launch_message,
            progress={"phase": "launching_pipeline"},
        )
        try:
            from app.db.utils import doc_get

            run = doc_get(col, run_id) or {}
            stats = dict(run.get("stats") or {})
            stats["preparation_stage"] = PREPARATION_STAGE_LAUNCHING
            stats["preparation_message"] = launch_message
            stats["preparation_updated_at"] = time.time()
            stats["preparation_progress"] = {"phase": "launching_pipeline"}
            col.update({"_key": run_id, "status": "running", "stats": stats})
        except Exception:
            log.warning(
                "arango run status update failed (file cache already running)",
                extra={"run_id": run_id},
            )

        status = "failed" if errors else "completed"
        return {
            "status": status,
            "chunk_count": len(chunks),
            "chunks": chunks,
            "migrations_applied": schema_result.get("migrations_applied") or [],
            "migration_count": schema_result.get("migration_count", 0),
            "missing_collections": missing,
            "errors": errors,
        }
    except Exception as exc:
        log.exception("prepare_arango workflow failed", extra={"run_id": run_id})
        from app.services.extraction import mark_run_preparation_failed

        mark_run_preparation_failed(run_id, str(exc))
        return {
            "status": "failed",
            "chunk_count": len(chunks),
            "chunks": chunks,
            "errors": [str(exc), *errors],
        }
