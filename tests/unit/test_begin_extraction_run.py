"""Tests for fast-start extraction run scheduling."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.extraction import begin_extraction_run
from app.services.run_progress_cache import get_cached_run_progress


@pytest.fixture
def progress_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_PROGRESS_CACHE_DIR", str(tmp_path))
    return tmp_path


class TestBeginExtractionRun:
    def test_returns_immediately_and_seeds_cache(self, progress_cache_dir) -> None:
        with patch("app.services.extraction.schedule_prepare_and_execute_run") as mock_schedule:
            run_record = begin_extraction_run(document_ids=["doc1"])

        assert run_record["_key"].startswith("run_")
        assert run_record["status"] == "preparing"
        mock_schedule.assert_called_once()
        kwargs = mock_schedule.call_args.kwargs
        assert kwargs["run_id"] == run_record["_key"]
        assert kwargs["run_record"]["_key"] == run_record["_key"]

        cached = get_cached_run_progress(str(run_record["_key"]))
        assert cached is not None
        assert cached["status"] == "preparing"
        assert cached["stats"]["preparation_stage"] == "queued"
