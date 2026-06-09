"""Shared run progress cache for high-frequency status polls.

Uvicorn multi-worker processes do not share memory. Progress is written to small JSON
files under ``RUN_PROGRESS_CACHE_DIR`` (default ``/tmp/aoe-run-progress``) so any
worker can serve ``GET /runs/{id}/status`` without blocking on a busy Arango gateway.

Each process also keeps an in-memory L1 cache keyed by file mtime.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_RUN_ID_RE = re.compile(r"^run_[0-9a-f]{12}$")
PREPARATION_STAGE_ORDER: tuple[str, ...] = (
    "queued",
    "gateway_health",
    "gateway_arango",
    "run_persisted",
    "starting",  # legacy alias — treat as gateway_arango in rank()
    "materializing_arango",
    "schema_migrations",
    "launching_pipeline",
)
_STAGE_ALIASES: dict[str, str] = {
    "starting": "gateway_arango",
}
_STATUS_RANK: dict[str, int] = {
    "queued": 0,
    "preparing": 1,
    "running": 2,
    "paused": 2,
    "completed": 3,
    "completed_with_errors": 3,
    "failed": 3,
    "cancelled": 3,
}
_lock = threading.Lock()
_l1: dict[str, tuple[float, dict[str, Any]]] = {}


def _cache_dir() -> Path:
    raw = os.environ.get("RUN_PROGRESS_CACHE_DIR", "/tmp/aoe-run-progress")
    return Path(raw)


def _now() -> float:
    return time.time()


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.match(run_id):
        raise ValueError(f"invalid run_id for progress cache: {run_id!r}")


def _path(run_id: str) -> Path:
    _validate_run_id(run_id)
    return _cache_dir() / f"{run_id}.json"


def _read_file(run_id: str) -> dict[str, Any] | None:
    path = _path(run_id)
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, json.JSONDecodeError, ValueError):
        log.debug("could not read run progress cache", extra={"run_id": run_id}, exc_info=True)
        return None


def _write_file(run_id: str, entry: dict[str, Any]) -> None:
    path = _path(run_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {**entry, "cached_at": _now()}
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entry, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        with _lock:
            _l1[run_id] = (path.stat().st_mtime, dict(entry))
    except OSError:
        log.warning(
            "could not write run progress cache file",
            extra={"run_id": run_id, "path": str(path)},
            exc_info=True,
        )


def _snapshot(entry: dict[str, Any], run_id: str) -> dict[str, Any]:
    stats = entry.get("stats")
    return {
        "_key": entry.get("_key", run_id),
        "status": entry.get("status"),
        "started_at": entry.get("started_at"),
        "completed_at": entry.get("completed_at"),
        "stats": dict(stats) if isinstance(stats, dict) else {},
    }


def seed_run_progress(
    run_id: str,
    *,
    status: str,
    stage: str,
    message: str,
    progress: dict[str, Any] | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    """Insert or refresh cache when a run is created or the prepare thread starts."""
    base_stats: dict[str, Any] = {
        "preparation_stage": stage,
        "preparation_message": message,
        "preparation_updated_at": _now(),
        "errors": [],
        "step_logs": [],
    }
    if progress is not None:
        base_stats["preparation_progress"] = progress
    if stats:
        base_stats.update(stats)
    try:
        _write_file(
            run_id,
            {
                "_key": run_id,
                "status": status,
                "stats": base_stats,
            },
        )
    except ValueError:
        log.warning("skipped seed_run_progress for invalid run_id", extra={"run_id": run_id})


def update_run_progress_cache(
    run_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    message: str | None = None,
    progress: dict[str, Any] | None = None,
    stats_patch: dict[str, Any] | None = None,
) -> None:
    """Merge preparation / agent progress into the shared cache."""
    try:
        entry = _read_file(run_id) or {"_key": run_id, "stats": {}}
        stats = dict(entry.get("stats") or {})
        if stage is not None:
            stats["preparation_stage"] = stage
        if message is not None:
            stats["preparation_message"] = message
        stats["preparation_updated_at"] = _now()
        if progress is not None:
            stats["preparation_progress"] = progress
        if stats_patch:
            stats.update(stats_patch)
        if status is not None:
            entry["status"] = status
        entry["stats"] = stats
        entry["_key"] = run_id
        _write_file(run_id, entry)
    except ValueError:
        log.warning("skipped update_run_progress_cache for invalid run_id", extra={"run_id": run_id})


def get_cached_run_progress(run_id: str) -> dict[str, Any] | None:
    """Return cached run progress from L1 or shared file store."""
    try:
        path = _path(run_id)
    except ValueError:
        return None

    try:
        mtime = path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        mtime = 0.0

    with _lock:
        l1 = _l1.get(run_id)
        if l1 is not None and l1[0] >= mtime:
            return _snapshot(l1[1], run_id)

    entry = _read_file(run_id)
    if entry is None:
        return None
    with _lock:
        _l1[run_id] = (mtime or _now(), dict(entry))
    return _snapshot(entry, run_id)


def drop_run_progress_cache(run_id: str) -> None:
    try:
        path = _path(run_id)
    except ValueError:
        return
    with _lock:
        _l1.pop(run_id, None)
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def preparation_stage_rank(stage: str | None) -> int:
    if not stage:
        return 0
    normalized = _STAGE_ALIASES.get(stage, stage)
    try:
        return PREPARATION_STAGE_ORDER.index(normalized)
    except ValueError:
        return 0


def run_status_rank(status: str | None) -> int:
    if not status:
        return 0
    return _STATUS_RANK.get(status, 0)


def merge_run_progress_for_poll(
    cached: dict[str, Any],
    gateway_run: dict[str, Any],
) -> dict[str, Any]:
    """Combine file cache with a gateway read; never regress preparation stage or status."""
    merged = dict(gateway_run)
    cached_stats = dict(cached.get("stats") or {})
    gateway_stats = dict(merged.get("stats") or {})
    stats = dict(gateway_stats)

    cached_stage = cached_stats.get("preparation_stage")
    gateway_stage = gateway_stats.get("preparation_stage")
    if preparation_stage_rank(str(cached_stage or "")) >= preparation_stage_rank(
        str(gateway_stage or "")
    ):
        stats["preparation_stage"] = cached_stage
        stats["preparation_message"] = cached_stats.get("preparation_message")
        stats["preparation_updated_at"] = cached_stats.get("preparation_updated_at")
        if cached_stats.get("preparation_progress") is not None:
            stats["preparation_progress"] = cached_stats.get("preparation_progress")

    cached_logs = cached_stats.get("step_logs")
    gateway_logs = gateway_stats.get("step_logs")
    if isinstance(cached_logs, list) and (
        not isinstance(gateway_logs, list) or len(cached_logs) >= len(gateway_logs)
    ):
        stats["step_logs"] = cached_logs
    if cached_stats.get("current_step") and not gateway_stats.get("current_step"):
        stats["current_step"] = cached_stats.get("current_step")

    merged["stats"] = stats
    cached_status = cached.get("status")
    gateway_status = merged.get("status")
    if run_status_rank(str(cached_status or "")) >= run_status_rank(str(gateway_status or "")):
        merged["status"] = cached_status
    return merged
