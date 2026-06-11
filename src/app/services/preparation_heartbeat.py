"""Cache-only heartbeats during extraction prepare (never blocks on Arango).

The prepare thread holds the gateway HTTP client for minutes at a time. Status
polls read only the file/UC progress cache, so a background ticker must refresh
``preparation_updated_at`` every ~12s while blocking work runs.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.services.run_progress_cache import update_run_progress_cache

log = logging.getLogger(__name__)

# UI guarantee: never more than 15s without a visible server-side update.
PREPARATION_HEARTBEAT_INTERVAL_SEC = 12.0
PREPARATION_UI_MAX_SILENCE_SEC = 15.0

_lock = threading.Lock()
_sessions: dict[str, PreparationSession] = {}


class PreparationSession:
    """Background cache ticker for one extraction prepare run."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._state_lock = threading.Lock()
        self._stage = "queued"
        self._message = "Preparation worker starting…"
        self._progress: dict[str, Any] = {}
        self._status = "preparing"
        self._started = time.perf_counter()
        self._heartbeat_seq = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def record(
        self,
        *,
        stage: str | None = None,
        message: str | None = None,
        progress: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> None:
        """Merge latest stage/message from the prepare thread (no cache write)."""
        with self._state_lock:
            if stage is not None:
                self._stage = stage
            if message is not None:
                self._message = message
            if progress is not None:
                self._progress = {**self._progress, **progress}
            if status is not None:
                self._status = status

    def start(self) -> None:
        self._emit(force=True, suffix="")
        self._thread = threading.Thread(
            target=self._loop,
            name=f"prep-hb-{self.run_id[:12]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.wait(PREPARATION_HEARTBEAT_INTERVAL_SEC):
            self._emit(force=False)

    def _emit(self, *, force: bool, suffix: str | None = None) -> None:
        with self._state_lock:
            stage = self._stage
            base_message = self._message
            progress = dict(self._progress)
            status = self._status
            self._heartbeat_seq += 1
            seq = self._heartbeat_seq

        elapsed_s = int(time.perf_counter() - self._started)
        progress["heartbeat_elapsed_s"] = elapsed_s
        progress["heartbeat_at"] = time.time()
        progress["heartbeat_seq"] = seq

        if suffix is None:
            suffix = "" if force else f" — still working ({elapsed_s}s)"
        message = f"{base_message}{suffix}"

        try:
            update_run_progress_cache(
                self.run_id,
                status=status,
                stage=stage,
                message=message,
                progress=progress,
                touch_session=False,
            )
        except Exception:
            log.debug(
                "preparation heartbeat cache write failed",
                extra={"run_id": self.run_id, "stage": stage},
                exc_info=True,
            )


def start_preparation_session(run_id: str) -> PreparationSession:
    with _lock:
        existing = _sessions.get(run_id)
        if existing is not None:
            return existing
        session = PreparationSession(run_id)
        _sessions[run_id] = session
        session.start()
        return session


def stop_preparation_session(run_id: str) -> None:
    with _lock:
        session = _sessions.pop(run_id, None)
    if session is not None:
        session.stop()


def record_preparation_session(
    run_id: str,
    *,
    stage: str | None = None,
    message: str | None = None,
    progress: dict[str, Any] | None = None,
    status: str | None = None,
) -> None:
    """Sync session state after a cache write (heartbeat loop picks it up)."""
    with _lock:
        session = _sessions.get(run_id)
    if session is None:
        return
    session.record(
        stage=stage,
        message=message,
        progress=progress,
        status=status,
    )
