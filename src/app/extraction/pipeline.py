"""LangGraph StateGraph for the ontology extraction pipeline.

Nodes: prepare_arango → strategy_selector → extractor → … → filter → finalize_graph
Conditional edges retry on failure. Checkpointed via MemorySaver.
Human-in-the-loop breakpoint after pre-curation filter (before graph persist).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.extraction.agents.belief_revision import belief_revision_node
from app.extraction.agents.consistency import consistency_checker_node
from app.extraction.agents.er_agent import er_agent_node
from app.extraction.agents.extractor import extractor_node
from app.extraction.agents.filter import filter_agent_node
from app.extraction.agents.finalize_graph import finalize_graph_node
from app.extraction.agents.prepare_arango import prepare_arango_node
from app.extraction.agents.strategy import strategy_selector_node
from app.extraction.judges.quality_judge_node import quality_judge_node
from app.extraction.live_metrics import live_metrics_from_node
from app.extraction.state import ExtractionPipelineState

log = logging.getLogger(__name__)

_EVENT_BUS: dict[str, Any] | None = None

_compiled_lock = threading.Lock()
_compiled_interrupt_after_filter: Any | None = None

_NEXT_STEPS: dict[str, list[str]] = {
    "prepare_arango": ["strategy_selector"],
    "strategy_selector": ["extractor"],
    "extractor": ["consistency_checker"],
    "consistency_checker": ["quality_judge", "er_agent"],
    "quality_judge": ["belief_revision"],
    "er_agent": ["belief_revision"],
    "belief_revision": ["filter"],
    "filter": ["finalize_graph"],
}


def set_event_bus(bus: dict[str, Any] | None) -> None:
    """Register an event bus for pipeline step notifications (WebSocket)."""
    global _EVENT_BUS
    _EVENT_BUS = bus


def _after_prepare_arango(state: ExtractionPipelineState) -> str:
    """Abort the DAG when Arango prep failed."""
    prep = state.get("prepare_arango_result") or {}
    if prep.get("status") == "failed" or state.get("errors"):
        return "abort"
    return "continue"


def _should_retry_extraction(state: ExtractionPipelineState) -> str:
    """Conditional edge: retry extraction if all passes failed."""
    passes = state.get("extraction_passes", [])
    errors = state.get("errors", [])

    if not passes and errors:
        retry_count = sum(1 for e in errors if "retry" in e.lower())
        if retry_count < 2:
            return "retry"
    return "continue"


def _should_proceed_to_finalize(state: ExtractionPipelineState) -> str:
    """Route to graph persist after filter, or END when there is nothing to write."""
    filter_results = state.get("filter_results", {})
    if filter_results.get("status") == "failed":
        return "abort"
    consistency = state.get("consistency_result")
    if consistency is None or (hasattr(consistency, "classes") and len(consistency.classes) == 0):
        return "abort"
    return "finalize"


def build_pipeline() -> StateGraph[Any]:
    """Construct the LangGraph StateGraph for extraction.

    Pipeline topology:

    Prepare Arango -> Strategy -> Extraction -> Consistency
      -+-> Quality Judge -+-> Belief Revision -> Filter -> Finalize Graph
       +-> ER Agent -----+
    """
    graph = StateGraph(ExtractionPipelineState)

    graph.add_node("prepare_arango", prepare_arango_node)
    graph.add_node("strategy_selector", strategy_selector_node)
    graph.add_node("extractor", extractor_node)
    graph.add_node("consistency_checker", consistency_checker_node)
    graph.add_node("quality_judge", quality_judge_node)
    graph.add_node("er_agent", er_agent_node)
    graph.add_node("belief_revision", belief_revision_node)
    graph.add_node("filter", filter_agent_node)
    graph.add_node("finalize_graph", finalize_graph_node)

    graph.set_entry_point("prepare_arango")
    graph.add_conditional_edges(
        "prepare_arango",
        _after_prepare_arango,
        {
            "continue": "strategy_selector",
            "abort": END,
        },
    )
    graph.add_edge("strategy_selector", "extractor")

    graph.add_conditional_edges(
        "extractor",
        _should_retry_extraction,
        {
            "retry": "extractor",
            "continue": "consistency_checker",
        },
    )

    def _fork_after_consistency(state: ExtractionPipelineState) -> list[str]:
        """Fork: run quality_judge and er_agent in parallel."""
        result = state.get("consistency_result")
        if result is None or (hasattr(result, "classes") and len(result.classes) == 0):
            return []
        return ["quality_judge", "er_agent"]

    graph.add_conditional_edges(
        "consistency_checker",
        _fork_after_consistency,
        ["quality_judge", "er_agent"],
    )

    graph.add_edge("quality_judge", "belief_revision")
    graph.add_edge("er_agent", "belief_revision")
    graph.add_edge("belief_revision", "filter")

    graph.add_conditional_edges(
        "filter",
        _should_proceed_to_finalize,
        {
            "finalize": "finalize_graph",
            "abort": END,
        },
    )
    graph.add_edge("finalize_graph", END)

    return graph


def compile_pipeline(
    checkpointer: Any | None = None,
    *,
    interrupt_after_filter: bool = False,
) -> Any:
    """Compile the pipeline with checkpointing.

    Uses MemorySaver by default; accepts custom checkpointer for Redis etc.

    Parameters
    ----------
    interrupt_after_filter:
        If True, pauses after the pre-curation filter and **before**
        ``finalize_graph`` (graph persist). Resume the checkpoint to commit
        ontology writes to Arango.
    """
    graph = build_pipeline()
    if checkpointer is None:
        checkpointer = MemorySaver()

    interrupt_after = ["filter"] if interrupt_after_filter else None

    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_after,
    )
    log.info(
        "extraction pipeline compiled",
        extra={
            "checkpointer": type(checkpointer).__name__,
            "interrupt_after_filter": interrupt_after_filter,
        },
    )
    return compiled


def reset_compiled_pipeline_cache() -> None:
    """Drop cached compiled graph (tests only)."""
    global _compiled_interrupt_after_filter
    with _compiled_lock:
        _compiled_interrupt_after_filter = None


def get_compiled_pipeline(*, interrupt_after_filter: bool = False) -> tuple[Any, bool]:
    """Return ``(compiled_graph, was_cached)``. Caches the interrupt-after-filter variant."""
    global _compiled_interrupt_after_filter
    if not interrupt_after_filter:
        return compile_pipeline(interrupt_after_filter=False), False
    with _compiled_lock:
        if _compiled_interrupt_after_filter is not None:
            return _compiled_interrupt_after_filter, True
        _compiled_interrupt_after_filter = compile_pipeline(interrupt_after_filter=True)
        return _compiled_interrupt_after_filter, False


async def run_pipeline(
    *,
    run_id: str,
    document_id: str,
    chunks: list[dict[str, Any]],
    thread_id: str | None = None,
    event_callback: Any | None = None,
    domain_context: str = "",
    domain_ontology_ids: list[str] | None = None,
    doc_ids: list[str] | None = None,
    target_ontology_id: str | None = None,
    chunks_from_uc: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    pipeline_metadata: dict[str, Any] | None = None,
) -> ExtractionPipelineState:
    """Execute the extraction pipeline end-to-end."""
    from app.services.extraction_gateway_checkpoints import format_duration_ms
    from app.services.run_progress_cache import update_run_progress_cache

    compile_started = time.perf_counter()
    compiled, pipeline_cached = get_compiled_pipeline(interrupt_after_filter=True)
    compile_ms = int((time.perf_counter() - compile_started) * 1000)
    compile_label = format_duration_ms(compile_ms)
    if pipeline_cached:
        pipeline_msg = (
            f"LangGraph pipeline ready (cached, {compile_label}) — entering prepare_arango…"
        )
    else:
        pipeline_msg = (
            f"LangGraph pipeline compiled ({compile_label}) — entering prepare_arango…"
        )
    update_run_progress_cache(
        run_id,
        stage="langgraph_startup",
        message=pipeline_msg,
        progress={
            "phase": "langgraph_startup",
            "pipeline_cached": pipeline_cached,
            "compile_ms": compile_ms,
        },
    )

    metadata = {
        "domain_ontology_ids": domain_ontology_ids or [],
        "doc_ids": doc_ids or ([document_id] if document_id else []),
        "target_ontology_id": target_ontology_id,
        "chunks_from_uc": chunks_from_uc,
    }
    if pipeline_metadata:
        metadata.update(pipeline_metadata)

    initial_state: ExtractionPipelineState = {
        "run_id": run_id,
        "document_id": document_id,
        "document_chunks": chunks,
        "extraction_passes": [],
        "errors": [],
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "step_logs": [],
        "current_step": "initialized",
        "metadata": metadata,
        "faithfulness_scores": {},
        "validity_scores": {},
        "er_results": {},
        "filter_results": {},
        "merge_candidates": [],
        "domain_context": domain_context,
        "prepare_arango_result": None,
        "finalize_graph_result": None,
    }

    config = {"configurable": {"thread_id": thread_id or run_id}}

    log.info(
        "pipeline execution started",
        extra={"run_id": run_id, "document_id": document_id, "chunk_count": len(chunks)},
    )

    final_state: dict[str, Any] | None = None
    last_node: str | None = None
    try:
        if event_callback:
            await event_callback(
                run_id=run_id,
                event_type="step_started",
                step="prepare_arango",
                data={},
            )

        async for event in compiled.astream(initial_state, config=config):
            if cancel_check and cancel_check():
                from app.services.extraction import ExtractionCancelled

                raise ExtractionCancelled(f"Extraction run {run_id} cancelled")
            for node_name, node_output in event.items():
                log.info(
                    "pipeline node completed",
                    extra={"run_id": run_id, "node": node_name},
                )
                last_node = node_name
                if event_callback:
                    node_metrics = live_metrics_from_node(
                        node_name,
                        node_output if isinstance(node_output, dict) else None,
                    )
                    await event_callback(
                        run_id=run_id,
                        event_type="step_completed",
                        step=node_name,
                        data={"current_step": node_name, **node_metrics},
                    )
                    for next_step in _NEXT_STEPS.get(node_name, []):
                        await event_callback(
                            run_id=run_id,
                            event_type="step_started",
                            step=next_step,
                            data={},
                        )
                if isinstance(node_output, dict):
                    final_state = node_output
    except Exception as stream_exc:
        log.exception(
            "pipeline stream error, capturing partial state (run_id=%s)",
            run_id,
        )
        if final_state is None:
            final_state = dict(initial_state)
        final_state.setdefault("errors", []).append(str(stream_exc))

        if event_callback:
            await event_callback(
                run_id=run_id,
                event_type="error",
                step=last_node or "pipeline",
                data={"error": str(stream_exc)},
            )
            await event_callback(
                run_id=run_id,
                event_type="completed",
                step="pipeline",
                data={"errors": final_state.get("errors", [])},
            )

        return final_state  # type: ignore[return-value]

    try:
        snapshot = compiled.get_state(config)
    except Exception:
        snapshot = None
    result_state: ExtractionPipelineState = cast(
        "ExtractionPipelineState",
        snapshot.values if snapshot else (final_state or initial_state),
    )

    is_interrupted = snapshot and snapshot.next if snapshot else False
    if is_interrupted and event_callback:
        await event_callback(
            run_id=run_id,
            event_type="pipeline_paused",
            step="filter",
            data={
                "message": (
                    "Pipeline paused after pre-curation filter. "
                    "Resume to run finalize_graph and persist to Arango."
                ),
                "filter_results": result_state.get("filter_results", {}),
                "merge_candidates": result_state.get("merge_candidates", []),
            },
        )
    elif event_callback:
        await event_callback(
            run_id=run_id,
            event_type="completed",
            step="pipeline",
            data={
                "consistency_result": result_state.get("consistency_result") is not None,
                "finalize_graph": (result_state.get("finalize_graph_result") or {}).get("status"),
                "errors": result_state.get("errors", []),
            },
        )

    log.info(
        "pipeline execution completed",
        extra={
            "run_id": run_id,
            "steps": len(result_state.get("step_logs", [])),
            "errors": len(result_state.get("errors", [])),
            "finalize_status": (result_state.get("finalize_graph_result") or {}).get("status"),
        },
    )

    return result_state
