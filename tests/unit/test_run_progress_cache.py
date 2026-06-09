"""Tests for shared extraction run progress cache (multi-worker file store)."""

from __future__ import annotations

import pytest

from app.services.extraction import build_run_status_snapshot, get_run_status_for_poll
from app.services.run_progress_cache import (
    drop_run_progress_cache,
    get_cached_run_progress,
    merge_run_progress_for_poll,
    seed_run_progress,
    update_run_progress_cache,
)


@pytest.fixture
def progress_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_PROGRESS_CACHE_DIR", str(tmp_path))
    return tmp_path


class TestRunProgressCache:
    run_id = "run_abc123def456"

    def setup_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def teardown_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def test_seed_and_read(self, progress_cache_dir) -> None:
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="queued",
            message="waiting",
        )
        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        assert cached["status"] == "preparing"
        assert cached["stats"]["preparation_stage"] == "queued"
        assert (progress_cache_dir / f"{self.run_id}.json").is_file()

    def test_get_run_status_for_poll_uses_cache_without_db(self, progress_cache_dir) -> None:
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="gateway_health",
            message="worker up",
        )
        snap = get_run_status_for_poll(self.run_id)
        assert snap["status"] == "preparing"
        assert snap["preparation_stage"] == "gateway_health"
        assert build_run_status_snapshot(get_cached_run_progress(self.run_id) or {})[
            "preparation_message"
        ] == "worker up"

    def test_update_merges_stage(self, progress_cache_dir) -> None:
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="queued",
            message="queued",
        )
        update_run_progress_cache(
            self.run_id,
            stage="materializing_arango",
            message="copying chunks",
            progress={"inserted": 1, "total": 10},
        )
        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        assert cached["stats"]["preparation_stage"] == "materializing_arango"
        assert cached["stats"]["preparation_progress"]["inserted"] == 1

    def test_merge_never_regresses_stale_gateway(self) -> None:
        cached = {
            "_key": "run_test",
            "status": "running",
            "stats": {
                "preparation_stage": "launching_pipeline",
                "preparation_message": "starting agents",
                "preparation_updated_at": 200.0,
            },
        }
        gateway = {
            "_key": "run_test",
            "status": "preparing",
            "stats": {
                "preparation_stage": "queued",
                "preparation_message": "Queued — will copy UC chunks",
                "preparation_updated_at": 100.0,
            },
        }
        merged = merge_run_progress_for_poll(cached, gateway)
        assert merged["status"] == "running"
        assert merged["stats"]["preparation_stage"] == "launching_pipeline"

    def test_shared_across_process_simulation(self, progress_cache_dir) -> None:
        """Second read after file write sees updates (simulates another uvicorn worker)."""
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="queued",
            message="queued",
        )
        # Drop L1 by reading from a fresh import path — clear module l1 via drop + re-read file
        from app.services import run_progress_cache as rpc

        with rpc._lock:
            rpc._l1.pop(self.run_id, None)

        update_run_progress_cache(
            self.run_id,
            stage="gateway_health",
            message="thread started",
        )
        with rpc._lock:
            rpc._l1.pop(self.run_id, None)

        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        assert cached["stats"]["preparation_stage"] == "gateway_health"
