"""Status poll behaviour — cache-first, no 404 while preparing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.errors import NotFoundError
from app.services.extraction import (
    fetch_run_status_from_gateway,
    get_run_status_for_poll,
    read_run_status_poll_fast,
    update_run_current_step,
)
from app.services.run_progress_cache import drop_run_progress_cache, seed_run_progress


@pytest.fixture
def progress_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_PROGRESS_CACHE_DIR", str(tmp_path))
    return tmp_path


class TestRunStatusPoll:
    run_id = "run_abc123def456"

    def setup_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def teardown_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def test_read_fast_from_cache(self, progress_cache_dir) -> None:
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="gateway_health",
            message="probing",
        )
        snap = read_run_status_poll_fast(self.run_id)
        assert snap is not None
        assert snap["status"] == "preparing"
        assert snap["preparation_stage"] == "gateway_health"

    def test_fetch_returns_stub_when_not_in_arango(self, progress_cache_dir) -> None:
        with patch("app.services.extraction.get_db") as mock_get_db, patch(
            "app.services.extraction.get_run",
            side_effect=NotFoundError(f"Extraction run '{self.run_id}' not found"),
        ):
            snap = fetch_run_status_from_gateway(self.run_id)
        mock_get_db.assert_called()
        assert snap["status"] == "preparing"

    def test_poll_never_calls_gateway(self, progress_cache_dir) -> None:
        with patch("app.services.extraction.fetch_run_status_from_gateway") as mock_gw:
            snap = get_run_status_for_poll(self.run_id)
        mock_gw.assert_not_called()
        assert snap["status"] == "preparing"

    def test_get_run_status_for_poll_uses_cache_without_gateway(self, progress_cache_dir) -> None:
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="run_persisted",
            message="verified",
        )
        with patch("app.services.extraction.get_db") as mock_get_db:
            snap = get_run_status_for_poll(self.run_id)
            mock_get_db.assert_not_called()
        assert snap["preparation_stage"] == "run_persisted"

    def test_prepare_arango_current_step_does_not_force_launching_pipeline(
        self, progress_cache_dir
    ) -> None:
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="gateway_health",
            message="probing gateway",
        )
        update_run_current_step(self.run_id, "prepare_arango", message="Agent step: prepare_arango")
        snap = read_run_status_poll_fast(self.run_id)
        assert snap is not None
        assert snap["status"] == "preparing"
        assert snap["stats"]["preparation_stage"] == "gateway_health"
        assert snap["stats"]["current_step"] == "prepare_arango"
