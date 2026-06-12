"""Preparation vs running status for UI polls and run list."""

from __future__ import annotations

from app.services.extraction import (
    effective_status_for_ui,
    preparation_still_active,
    record_run_step_event,
    update_run_current_step,
)
from app.services.run_progress_cache import drop_run_progress_cache, get_cached_run_progress, seed_run_progress


class TestPreparationStatus:
    run_id = "run_abc123def456"

    def setup_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def teardown_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def test_preparation_still_active_during_gateway_stages(self) -> None:
        run = {
            "status": "preparing",
            "stats": {"preparation_stage": "gateway_arango", "current_step": "prepare_arango"},
        }
        assert preparation_still_active(run) is True

    def test_effective_status_maps_running_back_to_preparing(self) -> None:
        run = {
            "status": "running",
            "stats": {
                "preparation_stage": "loading_uc_chunks",
                "current_step": "prepare_arango",
                "step_logs": [{"step": "prepare_arango", "status": "running"}],
            },
        }
        assert effective_status_for_ui(run) == "preparing"

    def test_record_step_started_keeps_preparing_during_prepare_arango(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv("RUN_PROGRESS_CACHE_DIR", str(tmp_path))
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="gateway_health",
            message="probing",
        )
        record_run_step_event(
            self.run_id,
            event_type="step_started",
            step="prepare_arango",
        )
        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        assert cached["status"] == "preparing"
        assert cached["stats"]["preparation_stage"] == "gateway_health"
        assert cached["stats"]["current_step"] == "prepare_arango"

    def test_update_current_step_prepare_arango_does_not_advance_stage(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv("RUN_PROGRESS_CACHE_DIR", str(tmp_path))
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="run_persisted",
            message="verified",
        )
        update_run_current_step(self.run_id, "prepare_arango", message="Agent step: prepare_arango")
        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        assert cached["status"] == "preparing"
        assert cached["stats"]["preparation_stage"] == "run_persisted"
