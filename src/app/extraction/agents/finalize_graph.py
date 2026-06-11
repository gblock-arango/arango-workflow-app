"""Finalize graph node — registry, ontology vertices/edges, and named graph."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.extraction.extraction_persist import finalize_extraction_run
from app.extraction.state import ExtractionPipelineState, StepLog

log = logging.getLogger(__name__)


def finalize_graph_node(state: ExtractionPipelineState) -> dict[str, Any]:
    """LangGraph terminal node: persist filtered extraction to Arango."""
    start = time.time()
    run_id = state.get("run_id", "unknown")
    consistency = state.get("consistency_result")

    if consistency is None:
        step_log = StepLog(
            step="finalize_graph",
            status="skipped",
            started_at=start,
            completed_at=time.time(),
            duration_seconds=round(time.time() - start, 3),
            error="No consistency result to persist",
        )
        return {
            "finalize_graph_result": {"status": "skipped", "reason": "no_consistency_result"},
            "step_logs": [step_log],
        }

    classes = consistency.classes if hasattr(consistency, "classes") else []
    if not classes:
        step_log = StepLog(
            step="finalize_graph",
            status="skipped",
            started_at=start,
            completed_at=time.time(),
            duration_seconds=round(time.time() - start, 3),
            error="Consistency result has no classes",
        )
        return {
            "finalize_graph_result": {"status": "skipped", "reason": "empty_consistency_result"},
            "step_logs": [step_log],
        }

    try:
        persist_result = finalize_extraction_run(state)
    except Exception as exc:
        log.exception("finalize_graph failed", extra={"run_id": run_id})
        step_log = StepLog(
            step="finalize_graph",
            status="failed",
            started_at=start,
            completed_at=time.time(),
            duration_seconds=round(time.time() - start, 3),
            error=str(exc),
        )
        return {
            "finalize_graph_result": {"status": "failed", "error": str(exc)},
            "errors": [f"finalize_graph: {exc}"],
            "step_logs": [step_log],
        }

    duration = time.time() - start
    step_status = "completed" if persist_result.get("status") == "completed" else "failed"
    step_log = StepLog(
        step="finalize_graph",
        status=step_status,
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        error=None if step_status == "completed" else persist_result.get("reason"),
        metadata={
            "ontology_id": persist_result.get("ontology_id"),
            "graph_name": persist_result.get("graph_name"),
            "classes_written": persist_result.get("classes_written"),
        },
    )

    metadata = dict(state.get("metadata") or {})
    if persist_result.get("ontology_id"):
        metadata["ontology_id"] = persist_result["ontology_id"]

    log.info(
        "finalize_graph completed",
        extra={
            "run_id": run_id,
            "ontology_id": persist_result.get("ontology_id"),
            "classes_written": persist_result.get("classes_written"),
            "duration_seconds": round(duration, 3),
        },
    )

    out: dict[str, Any] = {
        "finalize_graph_result": persist_result,
        "metadata": metadata,
        "current_step": "finalize_graph",
        "step_logs": [step_log],
    }
    if step_status == "failed":
        out["errors"] = [
            f"finalize_graph failed: {persist_result.get('reason') or persist_result.get('error')}"
        ]
    return out
