"""Auth wiring for extraction prepare background threads."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from app.services.extraction import schedule_execute_run
from app.services.run_progress_cache import drop_run_progress_cache
from app.workflow_platform.databricks_outbound_auth import (
    set_outbound_bearer_override,
    set_outbound_service_principal_mode,
)


@pytest.fixture
def progress_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_PROGRESS_CACHE_DIR", str(tmp_path))
    return tmp_path


def _join_prepare_thread(run_id: str, *, timeout: float = 5.0) -> None:
    prefix = f"extract-run-{run_id[:16]}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for thread in threading.enumerate():
            if thread.name == prefix:
                thread.join(timeout=max(0.1, deadline - time.monotonic()))
                return
        time.sleep(0.05)
    raise AssertionError(f"prepare thread {prefix!r} did not finish")


class TestExtractionPrepareAuth:
    run_id = "run_abc123def456"

    def setup_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def teardown_method(self) -> None:
        drop_run_progress_cache(self.run_id)

    def test_prepare_thread_pins_service_principal_bearer(self, progress_cache_dir) -> None:
        seen_headers: list[dict[str, str]] = []

        async def fake_execute(**_kwargs: object) -> None:
            from app.workflow_platform.databricks_outbound_auth import outbound_databricks_auth_headers

            seen_headers.append(outbound_databricks_auth_headers())

        def fake_pin() -> tuple[object, object]:
            return (
                set_outbound_bearer_override("sp-m2m-token"),
                set_outbound_service_principal_mode(True),
            )

        with patch(
            "app.services.extraction.execute_run",
            new=fake_execute,
        ), patch(
            "app.services.extraction.pin_outbound_service_principal_bearer",
            side_effect=fake_pin,
        ), patch("app.services.extraction.release_outbound_service_principal_bearer"):
            schedule_execute_run(
                run_id=self.run_id,
                document_ids=["doc1"],
            )
            _join_prepare_thread(self.run_id)

        assert seen_headers == [{"Authorization": "Bearer sp-m2m-token"}]
