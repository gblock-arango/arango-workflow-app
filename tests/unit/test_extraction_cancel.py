"""Unit tests for cooperative extraction cancellation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.errors import ConflictError, NotFoundError
from app.api.extraction import cancel_run
from app.services.extraction import (
    CANCELLABLE_RUN_STATUSES,
    ExtractionCancelled,
    cancel_extraction_run,
    check_extraction_cancelled,
    clear_extraction_cancel,
    is_extraction_cancelled,
    mark_run_cancelled,
    request_extraction_cancel,
)


@pytest.fixture(autouse=True)
def _clear_cancel_registry():
    clear_extraction_cancel("run_test")
    yield
    clear_extraction_cancel("run_test")


class TestExtractionCancelRegistry:
    def test_request_and_check_raises(self):
        request_extraction_cancel("run_test")
        assert is_extraction_cancelled("run_test")
        with pytest.raises(ExtractionCancelled):
            check_extraction_cancelled("run_test")

    def test_clear_removes_flag(self):
        request_extraction_cancel("run_test")
        clear_extraction_cancel("run_test")
        assert not is_extraction_cancelled("run_test")
        check_extraction_cancelled("run_test")


class TestCancelExtractionRun:
    def test_cancels_active_run_from_cache(self):
        with (
            patch(
                "app.services.extraction.get_cached_run_progress",
                return_value={"status": "preparing"},
            ),
            patch("app.services.extraction.mark_run_cancelled") as mock_mark,
        ):
            result = cancel_extraction_run("run_test")
        assert result == {"run_id": "run_test", "status": "cancelled"}
        assert is_extraction_cancelled("run_test")
        mock_mark.assert_called_once_with("run_test")

    def test_idempotent_when_already_cancelled(self):
        with patch(
            "app.services.extraction.get_cached_run_progress",
            return_value={"status": "cancelled"},
        ):
            result = cancel_extraction_run("run_test")
        assert result["already_cancelled"] is True

    def test_raises_not_found(self):
        with (
            patch("app.services.extraction.get_cached_run_progress", return_value=None),
            patch("app.services.extraction.get_db") as mock_get_db,
            patch("app.services.extraction._get_collection") as mock_get_col,
            patch("app.services.extraction.doc_get", return_value=None),
        ):
            mock_get_db.return_value = MagicMock()
            mock_get_col.return_value = MagicMock()
            with pytest.raises(NotFoundError):
                cancel_extraction_run("run_missing")

    def test_raises_conflict_for_terminal_status(self):
        with patch(
            "app.services.extraction.get_cached_run_progress",
            return_value={"status": "completed"},
        ):
            with pytest.raises(ConflictError):
                cancel_extraction_run("run_test")

    def test_cancellable_statuses_include_paused(self):
        assert "paused" in CANCELLABLE_RUN_STATUSES


class TestCancelRunApi:
    @pytest.mark.asyncio
    async def test_cancel_route_returns_response(self):
        with patch(
            "app.api.extraction.run_sync",
            new_callable=AsyncMock,
            return_value={"run_id": "run_test", "status": "cancelled"},
        ):
            result = await cancel_run("run_test")
        assert result.run_id == "run_test"
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_route_maps_not_found(self):
        with patch(
            "app.api.extraction.run_sync",
            new_callable=AsyncMock,
            side_effect=NotFoundError("missing"),
        ):
            with pytest.raises(HTTPException) as exc:
                await cancel_run("run_missing")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_route_maps_conflict(self):
        with patch(
            "app.api.extraction.run_sync",
            new_callable=AsyncMock,
            side_effect=ConflictError("done"),
        ):
            with pytest.raises(HTTPException) as exc:
                await cancel_run("run_test")
        assert exc.value.status_code == 409


class TestMarkRunCancelled:
    def test_updates_cache_and_arango(self):
        mock_col = MagicMock()
        with (
            patch("app.services.extraction.update_run_progress_cache") as mock_cache,
            patch("app.services.extraction.get_db") as mock_get_db,
            patch("app.services.extraction._get_collection", return_value=mock_col),
            patch(
                "app.services.extraction.doc_get",
                return_value={"stats": {"preparation_stage": "schema_migrations"}},
            ),
        ):
            mock_get_db.return_value = MagicMock()
            mark_run_cancelled("run_test", message="Stopped")
        mock_cache.assert_called_once()
        mock_col.update.assert_called_once()
        update_doc = mock_col.update.call_args[0][0]
        assert update_doc["status"] == "cancelled"
