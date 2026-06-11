"""Prepare ArangoDB node — gateway prep, UC chunks, schema, readiness checks."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.extraction.prepare_arango_workflow import run_prepare_arango_workflow
from app.extraction.state import ExtractionPipelineState, StepLog

log = logging.getLogger(__name__)


def prepare_arango_node(state: ExtractionPipelineState) -> dict[str, Any]:
    """LangGraph entry node: gateway + UC + schema prep (Diagnostics polls these stages)."""
    start = time.time()
    run_id = str(state.get("run_id") or "unknown")
    metadata = dict(state.get("metadata") or {})
    doc_ids: list[str] = list(metadata.get("doc_ids") or [])
    if not doc_ids and state.get("document_id"):
        doc_ids = [str(state["document_id"])]

    prep = run_prepare_arango_workflow(
        run_id=run_id,
        doc_ids=doc_ids,
        metadata=metadata,
    )

    chunks = list(prep.get("chunks") or [])
    errors = list(prep.get("errors") or [])
    duration = time.time() - start
    status = str(prep.get("status") or ("failed" if errors else "completed"))

    prepare_result: dict[str, Any] = {
        "status": status,
        "chunk_count": prep.get("chunk_count", len(chunks)),
        "migrations_applied": prep.get("migrations_applied") or [],
        "migration_count": prep.get("migration_count", 0),
        "missing_collections": prep.get("missing_collections") or [],
    }

    step_log = StepLog(
        step="prepare_arango",
        status=status,
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        error=errors[0] if errors else None,
        metadata={
            "chunk_count": len(chunks),
            "migration_count": prepare_result["migration_count"],
            "missing_collections": prepare_result["missing_collections"],
        },
    )

    log.info(
        "prepare_arango %s",
        status,
        extra={
            "run_id": run_id,
            "chunk_count": len(chunks),
            "migration_count": prepare_result["migration_count"],
            "duration_seconds": round(duration, 3),
        },
    )

    out: dict[str, Any] = {
        "prepare_arango_result": prepare_result,
        "document_chunks": chunks,
        "current_step": "prepare_arango",
        "step_logs": [step_log],
    }
    if errors:
        out["errors"] = errors

    domain_ontology_ids = metadata.get("domain_ontology_ids") or []
    if domain_ontology_ids and status == "completed":
        try:
            from app.services.extraction import db_for_run
            from app.services.ontology_context import serialize_multi_domain_context

            db = db_for_run(run_id)
            domain_context = serialize_multi_domain_context(
                db,
                ontology_ids=list(domain_ontology_ids),
            )
            try:
                from app.services.uc_entity_selections import format_uc_entities_for_prompt

                uc_block = format_uc_entities_for_prompt()
                if uc_block:
                    domain_context = (
                        f"{domain_context}\n\n{uc_block}" if domain_context else uc_block
                    )
            except Exception:
                log.debug("UC entity selection context unavailable", exc_info=True)
            if domain_context:
                out["domain_context"] = domain_context
        except Exception:
            log.warning(
                "failed to serialize domain context after prepare_arango",
                exc_info=True,
                extra={"run_id": run_id},
            )

    return out
