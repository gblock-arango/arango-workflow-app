"""Tests for progressive gateway / Arango preparation checkpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.extraction_gateway_checkpoints import (
    STAGE_GATEWAY_ARANGO,
    STAGE_GATEWAY_HEALTH,
    STAGE_RUN_PERSISTED,
    connect_arango_checkpoint,
    persist_run_record_checkpoint,
    probe_gateway_health_checkpoint,
    record_checkpoint_cache,
)
from app.services.run_progress_cache import drop_run_progress_cache, get_cached_run_progress


@pytest.fixture
def progress_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_PROGRESS_CACHE_DIR", str(tmp_path))
    return tmp_path


class TestExtractionGatewayCheckpoints:
    run_id = "run_abc123def456"

    def setup_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def teardown_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def test_probe_gateway_health_ok(self, progress_cache_dir) -> None:
        with patch(
            "app.services.extraction_gateway_checkpoints.gateway_connectivity_status",
            return_value={
                "gateway_ok": True,
                "gateway_url": "http://gateway/health",
                "gateway_message": "ok",
            },
        ):
            probe_gateway_health_checkpoint(self.run_id)

        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        assert cached["stats"]["preparation_stage"] == STAGE_GATEWAY_ARANGO
        progress = cached["stats"]["preparation_progress"]
        assert progress["gateway_ok"] is True
        checkpoints = progress.get("checkpoints") or []
        assert len(checkpoints) >= 2
        assert checkpoints[-1]["stage"] == STAGE_GATEWAY_ARANGO

    def test_probe_gateway_health_failure(self, progress_cache_dir) -> None:
        with patch(
            "app.services.extraction_gateway_checkpoints.gateway_connectivity_status",
            return_value={
                "gateway_ok": False,
                "gateway_url": "http://gateway/health",
                "gateway_message": "connection refused",
            },
        ):
            with pytest.raises(RuntimeError, match="Gateway /health failed"):
                probe_gateway_health_checkpoint(self.run_id)

        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        assert cached["status"] == "failed"
        assert cached["stats"]["preparation_stage"] == STAGE_GATEWAY_HEALTH

    def test_persist_run_record_read_back(self, progress_cache_dir) -> None:
        col = MagicMock()
        run_record = {"_key": self.run_id, "status": "preparing"}
        col.insert = MagicMock()

        with patch(
            "app.db.utils.doc_get",
            side_effect=[None, run_record],
        ), patch(
            "app.services.extraction_gateway_checkpoints.record_checkpoint_arango",
        ) as mock_arango:
            db = MagicMock()
            persist_run_record_checkpoint(db, col, self.run_id, run_record)

        col.insert.assert_called_once_with(run_record)
        mock_arango.assert_called_once()
        args, kwargs = mock_arango.call_args
        assert args[1] == self.run_id
        assert kwargs["stage"] == STAGE_RUN_PERSISTED
        assert kwargs["progress"]["arango_verified"] is True

    def test_record_checkpoint_appends_log(self, progress_cache_dir) -> None:
        record_checkpoint_cache(
            self.run_id,
            stage=STAGE_GATEWAY_HEALTH,
            message="first",
        )
        record_checkpoint_cache(
            self.run_id,
            stage=STAGE_GATEWAY_ARANGO,
            message="second",
        )
        cached = get_cached_run_progress(self.run_id)
        checkpoints = cached["stats"]["preparation_progress"]["checkpoints"]
        assert len(checkpoints) == 2
        assert checkpoints[0]["message"] == "first"
        assert checkpoints[1]["message"] == "second"

    def test_connect_arango_checkpoint(self, progress_cache_dir) -> None:
        mock_db = MagicMock()
        mock_col = MagicMock()
        with patch("app.db.client.get_db", return_value=mock_db), patch(
            "app.services.extraction._get_collection",
            return_value=mock_col,
        ):
            db, col = connect_arango_checkpoint(self.run_id)

        assert db is mock_db
        assert col is mock_col
        cached = get_cached_run_progress(self.run_id)
        assert cached["stats"]["preparation_stage"] == STAGE_RUN_PERSISTED

    def test_connect_arango_dns_error_includes_registry_hint(self, progress_cache_dir) -> None:
        with patch(
            "app.db.client.get_db",
            side_effect=RuntimeError(
                "Gateway Arango probe failed: [Errno -2] Name or service not known"
            ),
        ):
            with pytest.raises(RuntimeError, match="ARANGO_REGISTRY_TABLE"):
                connect_arango_checkpoint(self.run_id)

        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        assert cached["status"] == "failed"
        assert cached["stats"]["preparation_stage"] == STAGE_GATEWAY_ARANGO
