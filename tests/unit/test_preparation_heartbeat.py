"""Tests for preparation heartbeat session."""

from __future__ import annotations

import time

from app.services.preparation_heartbeat import (
    PREPARATION_HEARTBEAT_INTERVAL_SEC,
    start_preparation_session,
    stop_preparation_session,
)
from app.services.run_progress_cache import get_cached_run_progress


def test_preparation_session_ticks_cache_while_idle(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_PROGRESS_CACHE_DIR", str(tmp_path))
    run_id = "run_abc123def456"

    session = start_preparation_session(run_id)
    session.record(
        stage="schema_migrations",
        message="Persisting schema migration state to Arango…",
        progress={"phase": "schema_migration", "bootstrap_phase": "persist"},
    )
    session._emit(force=True, suffix="")

    first = get_cached_run_progress(run_id)
    assert first is not None
    assert first["stats"]["preparation_stage"] == "schema_migrations"
    seq1 = first["stats"]["preparation_progress"]["heartbeat_seq"]

    time.sleep(PREPARATION_HEARTBEAT_INTERVAL_SEC + 0.5)
    second = get_cached_run_progress(run_id)
    assert second is not None
    seq2 = second["stats"]["preparation_progress"]["heartbeat_seq"]
    assert seq2 > seq1
    assert "still working" in second["stats"]["preparation_message"]

    stop_preparation_session(run_id)
