"""Unit tests for cache-first agent / LLM diagnostics."""

from __future__ import annotations

import time

import pytest

from app.services.run_agent_diagnostics import (
    init_agent_diagnostics,
    merge_agent_diagnostics_for_poll,
    record_llm_call,
    sync_agent_diagnostics_from_step_logs,
)
from app.services.extraction import build_run_status_snapshot
from app.services.run_progress_cache import drop_run_progress_cache, get_cached_run_progress, seed_run_progress


@pytest.fixture
def progress_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_PROGRESS_CACHE_DIR", str(tmp_path))
    return tmp_path


class TestRunAgentDiagnostics:
    run_id = "run_abc123def456"

    def setup_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def teardown_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def test_record_llm_call_increments_cache(self, progress_cache_dir) -> None:
        seed_run_progress(
            self.run_id,
            status="running",
            stage="launching_pipeline",
            message="agents",
        )
        init_agent_diagnostics(self.run_id)
        record_llm_call(
            self.run_id,
            prompt_tokens=100,
            completion_tokens=50,
            prompt_chars=400,
            step="extractor_pass_1",
        )
        record_llm_call(self.run_id, prompt_tokens=20, completion_tokens=10, prompt_chars=80)

        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        diag = cached["stats"]["agent_diagnostics"]
        assert diag["llm_calls"] == 2
        assert diag["prompt_tokens"] == 120
        assert diag["completion_tokens"] == 60
        assert diag["total_tokens"] == 180
        assert diag["prompt_chars"] == 480
        assert diag["last_llm_step"] == "extractor_pass_1"

    def test_sync_step_logs_updates_running_steps(self, progress_cache_dir) -> None:
        init_agent_diagnostics(self.run_id)
        logs = [
            {"step": "extractor", "status": "running", "started_at": time.time()},
            {"step": "strategy_selector", "status": "completed", "started_at": time.time()},
        ]
        sync_agent_diagnostics_from_step_logs(self.run_id, logs, current_step="extractor")

        cached = get_cached_run_progress(self.run_id)
        assert cached["stats"]["agent_diagnostics"]["running_steps"] == ["extractor"]
        assert cached["stats"]["current_step"] == "extractor"

    def test_build_snapshot_includes_agent_diagnostics(self) -> None:
        snap = build_run_status_snapshot(
            {
                "_key": self.run_id,
                "status": "running",
                "stats": {
                    "step_logs": [{"step": "extractor", "status": "running"}],
                    "agent_diagnostics": {"llm_calls": 3, "prompt_tokens": 900},
                    "current_step": "extractor",
                },
            }
        )
        assert snap["agent_diagnostics"]["llm_calls"] == 3
        assert snap["stats"]["agent_diagnostics"]["llm_calls"] == 3
        assert snap["current_step"] == "extractor"

    def test_merge_never_regresses_llm_counters(self) -> None:
        merged = merge_agent_diagnostics_for_poll(
            {"agent_diagnostics": {"llm_calls": 5, "prompt_tokens": 1000}},
            {"agent_diagnostics": {"llm_calls": 2, "prompt_tokens": 400}},
        )
        assert merged["llm_calls"] == 5
        assert merged["prompt_tokens"] == 1000

    def test_get_run_cost_from_cache_while_running(self, progress_cache_dir) -> None:
        from app.services.extraction import get_run_cost
        from app.services.run_agent_diagnostics import init_agent_diagnostics, record_llm_call
        from app.services.run_progress_cache import seed_run_progress

        seed_run_progress(
            self.run_id,
            status="running",
            stage="launching_pipeline",
            message="running",
            stats={"started_at": time.time() - 60},
        )
        init_agent_diagnostics(self.run_id)
        record_llm_call(self.run_id, prompt_tokens=500, completion_tokens=100)
        from app.services.run_agent_diagnostics import record_live_run_metrics

        record_live_run_metrics(
            self.run_id,
            {"classes_extracted": 12, "properties_extracted": 40, "current_step": "er_agent"},
        )

        payload = get_run_cost(None, run_id=self.run_id)
        assert payload["live"] is True
        assert payload["classes_extracted"] == 12
        assert payload["properties_extracted"] == 40
        assert payload["llm_calls"] == 1
        assert payload["current_step"] == "er_agent"
