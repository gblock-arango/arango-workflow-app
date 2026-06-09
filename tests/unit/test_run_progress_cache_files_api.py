"""Run progress cache via UC Files API (Databricks Apps production path)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services.run_progress_cache import (
    drop_run_progress_cache,
    get_cached_run_progress,
    seed_run_progress,
    update_run_progress_cache,
)


@pytest.fixture
def files_api_cache(monkeypatch):
    store: dict[str, bytes] = {}
    monkeypatch.setenv("RUN_PROGRESS_CACHE_DIR", "")
    monkeypatch.setenv("TEST_DEPLOYMENT_MODE", "self_managed_platform")
    monkeypatch.setenv("UC_WORKFLOW_DATA_IO_MODE", "files_api")

    def fake_write(*, relative_path: str, content: bytes) -> str:
        store[relative_path] = content
        return relative_path

    def fake_read(relative_path: str) -> bytes:
        if relative_path not in store:
            raise FileNotFoundError(relative_path)
        return store[relative_path]

    def fake_delete(relative_path: str) -> None:
        store.pop(relative_path, None)

    with patch(
        "app.workflow_platform.workflow_data_volume.write_bytes",
        side_effect=fake_write,
    ), patch(
        "app.workflow_platform.workflow_data_volume.read_bytes",
        side_effect=fake_read,
    ), patch(
        "app.workflow_platform.workflow_data_volume.delete_relative",
        side_effect=fake_delete,
    ):
        yield store


class TestRunProgressCacheFilesApi:
    run_id = "run_abc123def456"

    def setup_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def teardown_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def test_seed_and_read_via_files_api(self, files_api_cache) -> None:
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="gateway_health",
            message="probing",
        )
        assert f"instance_data/run-progress/{self.run_id}.json" in files_api_cache
        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        assert cached["status"] == "preparing"
        assert cached["stats"]["preparation_stage"] == "gateway_health"

    def test_update_visible_to_second_read(self, files_api_cache) -> None:
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="queued",
            message="queued",
        )
        update_run_progress_cache(
            self.run_id,
            stage="run_persisted",
            message="confirmed",
        )
        cached = get_cached_run_progress(self.run_id)
        assert cached is not None
        assert cached["stats"]["preparation_stage"] == "run_persisted"

    def test_drop_removes_files_api_object(self, files_api_cache) -> None:
        seed_run_progress(
            self.run_id,
            status="preparing",
            stage="queued",
            message="queued",
        )
        key = f"instance_data/run-progress/{self.run_id}.json"
        assert key in files_api_cache
        drop_run_progress_cache(self.run_id)
        assert key not in files_api_cache
