"""Unit tests for extraction pipeline compilation, conditional edges, and run_pipeline.

Complements test_pipeline_events.py which covers WebSocket event emission.
These tests focus on pipeline structure, conditional edge logic, and compile options.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.extraction.pipeline import (
    _NEXT_STEPS,
    _after_prepare_arango,
    _should_proceed_to_finalize,
    _should_retry_extraction,
    build_pipeline,
    compile_pipeline,
    get_compiled_pipeline,
    reset_compiled_pipeline_cache,
    set_event_bus,
)

# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------


class TestShouldRetryExtraction:
    def test_continue_when_passes_exist(self):
        state = {"extraction_passes": [MagicMock()], "errors": []}
        assert _should_retry_extraction(state) == "continue"

    def test_continue_when_no_errors(self):
        state = {"extraction_passes": [], "errors": []}
        assert _should_retry_extraction(state) == "continue"

    def test_retry_when_no_passes_and_errors_with_retry(self):
        state = {"extraction_passes": [], "errors": ["retry needed"]}
        assert _should_retry_extraction(state) == "retry"

    def test_continue_after_two_retries(self):
        state = {
            "extraction_passes": [],
            "errors": ["retry 1", "retry 2"],
        }
        assert _should_retry_extraction(state) == "continue"

    def test_retry_on_first_retry_error(self):
        state = {"extraction_passes": [], "errors": ["first retry attempt"]}
        assert _should_retry_extraction(state) == "retry"


class TestShouldProceedToFinalize:
    def test_abort_when_filter_failed(self):
        state = {"filter_results": {"status": "failed"}}
        assert _should_proceed_to_finalize(state) == "abort"

    def test_finalize_when_filter_succeeded(self):
        mock_result = MagicMock()
        mock_result.classes = [MagicMock()]
        state = {"filter_results": {"status": "completed"}, "consistency_result": mock_result}
        assert _should_proceed_to_finalize(state) == "finalize"

    def test_abort_when_no_consistency_result(self):
        state = {"filter_results": {"status": "completed"}, "consistency_result": None}
        assert _should_proceed_to_finalize(state) == "abort"


class TestAfterPrepareArango:
    def test_abort_on_failed_prep(self):
        state = {"prepare_arango_result": {"status": "failed"}}
        assert _after_prepare_arango(state) == "abort"

    def test_continue_on_success(self):
        state = {"prepare_arango_result": {"status": "completed"}}
        assert _after_prepare_arango(state) == "continue"


# ---------------------------------------------------------------------------
# Pipeline build and compile
# ---------------------------------------------------------------------------


class TestBuildPipeline:
    def test_returns_state_graph(self):
        graph = build_pipeline()
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        graph = build_pipeline()
        node_names = set(graph.nodes.keys())
        expected = {
            "prepare_arango",
            "strategy_selector",
            "extractor",
            "consistency_checker",
            "quality_judge",
            "er_agent",
            "belief_revision",
            "filter",
            "finalize_graph",
        }
        assert expected.issubset(node_names)


class TestCompilePipeline:
    def test_compiles_with_default_checkpointer(self):
        compiled = compile_pipeline()
        assert compiled is not None

    def test_compiles_with_custom_checkpointer(self):
        compiled = compile_pipeline(MemorySaver())
        assert compiled is not None

    def test_compiles_with_interrupt_after_filter(self):
        reset_compiled_pipeline_cache()
        compiled = compile_pipeline(interrupt_after_filter=True)
        assert compiled is not None

    def test_get_compiled_pipeline_caches_interrupt_variant(self):
        reset_compiled_pipeline_cache()
        first, cached1 = get_compiled_pipeline(interrupt_after_filter=True)
        second, cached2 = get_compiled_pipeline(interrupt_after_filter=True)
        assert first is second
        assert cached1 is False
        assert cached2 is True
        reset_compiled_pipeline_cache()


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


class TestSetEventBus:
    def test_sets_and_clears_event_bus(self):
        bus = {"key": "value"}
        set_event_bus(bus)
        from app.extraction.pipeline import _EVENT_BUS

        assert _EVENT_BUS is bus

        set_event_bus(None)
        from app.extraction import pipeline

        assert pipeline._EVENT_BUS is None


# ---------------------------------------------------------------------------
# NEXT_STEPS mapping
# ---------------------------------------------------------------------------


class TestNextStepsMapping:
    def test_has_expected_transitions(self):
        assert _NEXT_STEPS["prepare_arango"] == ["strategy_selector"]
        assert _NEXT_STEPS["strategy_selector"] == ["extractor"]
        assert _NEXT_STEPS["extractor"] == ["consistency_checker"]
        assert _NEXT_STEPS["consistency_checker"] == ["quality_judge", "er_agent"]
        assert _NEXT_STEPS["quality_judge"] == ["belief_revision"]
        assert _NEXT_STEPS["er_agent"] == ["belief_revision"]
        assert _NEXT_STEPS["belief_revision"] == ["filter"]
        assert _NEXT_STEPS["filter"] == ["finalize_graph"]

    def test_finalize_not_in_next_steps(self):
        assert "finalize_graph" not in _NEXT_STEPS


# ---------------------------------------------------------------------------
# run_pipeline: interrupted (paused) state
# ---------------------------------------------------------------------------


class TestRunPipelinePaused:
    @pytest.mark.asyncio
    async def test_emits_pipeline_paused_only_when_interrupt_enabled(self):
        callback = AsyncMock()

        async def fake_stream():
            yield {"filter": {"filter_results": {"status": "ok"}}}

        mock_snapshot = MagicMock()
        mock_snapshot.values = {
            "filter_results": {"status": "ok"},
            "merge_candidates": [{"a": 1}],
            "errors": [],
            "step_logs": [],
            "finalize_graph_result": {"status": "completed"},
        }
        mock_snapshot.next = ["finalize_graph"]  # truthy means interrupted

        mock_compiled = MagicMock()
        mock_compiled.astream = lambda *a, **kw: fake_stream()
        mock_compiled.get_state.return_value = mock_snapshot

        with patch(
            "app.extraction.pipeline.get_compiled_pipeline",
            return_value=(mock_compiled, True),
        ):
            from app.extraction.pipeline import run_pipeline

            await run_pipeline(
                run_id="r1",
                document_id="d1",
                chunks=[],
                event_callback=callback,
            )

        event_types = [c.kwargs["event_type"] for c in callback.call_args_list]
        assert "pipeline_paused" in event_types

    @pytest.mark.asyncio
    async def test_default_pipeline_emits_completed_not_paused(self):
        callback = AsyncMock()

        async def fake_stream():
            yield {
                "finalize_graph": {
                    "finalize_graph_result": {"status": "completed"},
                    "errors": [],
                    "step_logs": [],
                }
            }

        mock_snapshot = MagicMock()
        mock_snapshot.values = {
            "finalize_graph_result": {"status": "completed"},
            "errors": [],
            "step_logs": [],
        }
        mock_snapshot.next = False

        mock_compiled = MagicMock()
        mock_compiled.astream = lambda *a, **kw: fake_stream()
        mock_compiled.get_state.return_value = mock_snapshot

        with patch(
            "app.extraction.pipeline.get_compiled_pipeline",
            return_value=(mock_compiled, False),
        ):
            from app.extraction.pipeline import run_pipeline

            await run_pipeline(
                run_id="r1",
                document_id="d1",
                chunks=[],
                event_callback=callback,
            )

        event_types = [c.kwargs["event_type"] for c in callback.call_args_list]
        assert "pipeline_paused" not in event_types
        assert "completed" in event_types
