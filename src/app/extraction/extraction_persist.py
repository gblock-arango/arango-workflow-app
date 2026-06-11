"""Persist filtered extraction results to Arango (registry + graph + named graph)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.db.types import StandardDatabase
from app.extraction.state import ExtractionPipelineState

log = logging.getLogger(__name__)

MaterializeProgressFn = Callable[[str, dict[str, Any] | None], None]


def finalize_extraction_run(
    state: ExtractionPipelineState,
    *,
    db: StandardDatabase | None = None,
    on_lineage_progress: MaterializeProgressFn | None = None,
) -> dict[str, Any]:
    """Write post-filter extraction output to registry and ontology graph collections.

    Returns a summary dict stored on pipeline state as ``finalize_graph_result``.
    """
    from app.db.client import get_db

    database = db or get_db()
    run_id = str(state.get("run_id") or "")
    consistency = state.get("consistency_result")
    if consistency is None:
        return {"status": "skipped", "reason": "no_consistency_result"}

    classes = consistency.classes if hasattr(consistency, "classes") else []
    if not classes:
        return {"status": "skipped", "reason": "empty_consistency_result"}

    metadata = dict(state.get("metadata") or {})
    doc_ids: list[str] = list(metadata.get("doc_ids") or [])
    primary_doc_id = str(state.get("document_id") or (doc_ids[0] if doc_ids else ""))
    if not doc_ids and primary_doc_id:
        doc_ids = [primary_doc_id]
    target_ontology_id = metadata.get("target_ontology_id")
    chunks_from_uc = bool(metadata.get("chunks_from_uc"))
    chunks = list(state.get("document_chunks") or [])

    from app.services.extraction import (
        _auto_register_ontology,
        _create_produced_by_edge,
        _materialize_to_graph,
        _store_results,
        _update_existing_ontology,
    )

    if chunks_from_uc and doc_ids:
        from app.services.extraction_materialize import materialize_embedding_documents_for_lineage

        materialize_embedding_documents_for_lineage(
            doc_ids,
            preloaded_chunks=chunks,
            on_progress=on_lineage_progress,
        )

    _store_results(database, run_id=run_id, result=consistency)

    ontology_id: str | None = None
    if target_ontology_id:
        ontology_id = _update_existing_ontology(
            database,
            ontology_id=str(target_ontology_id),
            run_id=run_id,
            result=consistency,
        )
    if not ontology_id:
        ontology_id = _auto_register_ontology(
            database,
            run_id=run_id,
            document_id=primary_doc_id,
            result=consistency,
        )

    if not ontology_id:
        return {
            "status": "failed",
            "reason": "ontology_registration_failed",
            "classes_written": 0,
        }

    faithfulness = state.get("faithfulness_scores") or {}
    validity = state.get("validity_scores") or {}
    for did in doc_ids:
        _materialize_to_graph(
            database,
            run_id=run_id,
            document_id=did,
            ontology_id=ontology_id,
            result=consistency,
            faithfulness_scores=faithfulness,
            validity_scores=validity,
        )

    _create_produced_by_edge(database, ontology_id=ontology_id, run_id=run_id)

    graph_name: str | None = None
    try:
        from app.services.ontology_graphs import ensure_ontology_graph

        graph_name = ensure_ontology_graph(ontology_id, db=database)
    except Exception:
        log.warning("per-ontology graph creation failed", exc_info=True)

    try:
        from app.db import quality_history_repo

        quality_history_repo.record_event_snapshot(
            ontology_id,
            source="extraction_completion",
            run_id=run_id,
            db=database,
        )
    except Exception:
        log.warning(
            "post-extraction quality snapshot failed",
            extra={"run_id": run_id, "ontology_id": ontology_id},
            exc_info=True,
        )

    return {
        "status": "completed",
        "ontology_id": ontology_id,
        "graph_name": graph_name,
        "classes_written": len(classes),
        "doc_ids": doc_ids,
    }
