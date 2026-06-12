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
    "loading_uc_chunks",
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


def _use_volume_files_api() -> bool:
    if (os.environ.get("RUN_PROGRESS_CACHE_DIR") or "").strip():
        return False
    try:
        from app.workflow_platform.workflow_data_volume import use_files_api_for_io

        return use_files_api_for_io()
    except Exception:
        return False


def _cache_volume_rel(run_id: str) -> str:
    _validate_run_id(run_id)
    return f"instance_data/run-progress/{run_id}.json"


def _cache_dir() -> Path:
    if _use_volume_files_api():
        # Production Databricks Apps: shared via UC Files API, not /Volumes mount.
        try:
            from app.workflow_platform.workflow_data_volume import workflow_data_root

            return workflow_data_root() / "instance_data" / "run-progress"
        except Exception:
            return Path("/tmp/aoe-run-progress")
    raw = (os.environ.get("RUN_PROGRESS_CACHE_DIR") or "").strip()
    if raw:
        return Path(raw)
    try:
        from app.workflow_platform.workflow_data_volume import workflow_data_root

        root = workflow_data_root()
        if root.is_dir():
            return root / "instance_data" / "run-progress"
    except Exception:
        log.debug(
            "workflow UC volume not mounted; using /tmp for run progress cache",
            exc_info=True,
        )
    return Path("/tmp/aoe-run-progress")


def _now() -> float:
    return time.time()


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.match(run_id):
        raise ValueError(f"invalid run_id for progress cache: {run_id!r}")


def _path(run_id: str) -> Path:
    _validate_run_id(run_id)
    return _cache_dir() / f"{run_id}.json"


def _read_file(run_id: str) -> dict[str, Any] | None:
    if _use_volume_files_api():
        try:
            from app.workflow_platform.workflow_data_volume import read_bytes

            raw = read_bytes(_cache_volume_rel(run_id))
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                return None
            return data
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError, ValueError):
            log.warning(
                "could not read run progress cache from UC Files API",
                extra={"run_id": run_id},
                exc_info=True,
            )
            return None

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
    entry = {**entry, "cached_at": _now()}
    payload = json.dumps(entry, separators=(",", ":")).encode("utf-8")

    if _use_volume_files_api():
        try:
            from app.workflow_platform.workflow_data_volume import write_bytes

            write_bytes(relative_path=_cache_volume_rel(run_id), content=payload)
            with _lock:
                _l1[run_id] = (_now(), dict(entry))
            return
        except OSError:
            log.error(
                "could not write run progress cache via UC Files API",
                extra={"run_id": run_id},
                exc_info=True,
            )
            return

    path = _path(run_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_bytes(payload)
        tmp.replace(path)
        with _lock:
            _l1[run_id] = (path.stat().st_mtime, dict(entry))
    except OSError:
        log.error(
            "could not write run progress cache file",
            extra={"run_id": run_id, "path": str(path)},
            exc_info=True,
        )


def _snapshot(entry: dict[str, Any], run_id: str) -> dict[str, Any]:
    stats = entry.get("stats")
    out: dict[str, Any] = {
        "_key": entry.get("_key", run_id),
        "status": entry.get("status"),
        "started_at": entry.get("started_at"),
        "completed_at": entry.get("completed_at"),
        "stats": dict(stats) if isinstance(stats, dict) else {},
    }
    for key in ("doc_id", "doc_ids", "target_ontology_id", "arango_database", "pending_run_record"):
        if entry.get(key) is not None:
            out[key] = entry[key]
    return out


def seed_run_progress(
    run_id: str,
    *,
    status: str,
    stage: str,
    message: str,
    progress: dict[str, Any] | None = None,
    stats: dict[str, Any] | None = None,
    doc_id: str | None = None,
    doc_ids: list[str] | None = None,
    target_ontology_id: str | None = None,
    arango_database: str | None = None,
    pending_run_record: dict[str, Any] | None = None,
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
    entry: dict[str, Any] = {
        "_key": run_id,
        "status": status,
        "stats": base_stats,
    }
    if doc_id:
        entry["doc_id"] = doc_id
    if doc_ids:
        entry["doc_ids"] = doc_ids
    if target_ontology_id:
        entry["target_ontology_id"] = target_ontology_id
    if arango_database:
        entry["arango_database"] = arango_database
    if pending_run_record:
        entry["pending_run_record"] = pending_run_record
    try:
        _write_file(run_id, entry)
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
    touch_session: bool = True,
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
        if touch_session:
            from app.services.preparation_heartbeat import record_preparation_session

            record_preparation_session(
                run_id,
                stage=stage,
                message=message,
                progress=progress,
                status=status,
            )
    except ValueError:
        log.warning("skipped update_run_progress_cache for invalid run_id", extra={"run_id": run_id})


def get_cached_run_progress(run_id: str) -> dict[str, Any] | None:
    """Return cached run progress from L1 or shared store (local file or UC Files API)."""
    try:
        _validate_run_id(run_id)
    except ValueError:
        return None

    now = _now()
    with _lock:
        l1 = _l1.get(run_id)
        if l1 is not None and now - l1[0] < 1.0:
            return _snapshot(l1[1], run_id)

    if not _use_volume_files_api():
        try:
            path = _path(run_id)
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
        _l1[run_id] = (now, dict(entry))
    return _snapshot(entry, run_id)


def list_cached_run_ids() -> list[str]:
    """Return run IDs with entries in the shared progress store."""
    ids: list[str] = []
    if _use_volume_files_api():
        try:
            from app.workflow_platform.workflow_data_volume import list_files

            for entry in list_files(prefix="instance_data/run-progress", max_entries=500):
                name = str(entry.get("name") or "")
                if name.startswith("run_") and name.endswith(".json"):
                    ids.append(name[: -len(".json")])
        except Exception:
            log.debug("could not list run progress cache via UC Files API", exc_info=True)
        return ids

    cache_dir = _cache_dir()
    try:
        if cache_dir.is_dir():
            for path in cache_dir.glob("run_*.json"):
                ids.append(path.stem)
    except OSError:
        log.debug("could not list run progress cache dir", exc_info=True)
    return ids


def clear_all_run_progress_cache() -> list[str]:
    """Remove every run progress cache file (UC volume or local dir)."""
    cleared: list[str] = []
    for run_id in list_cached_run_ids():
        drop_run_progress_cache(run_id)
        cleared.append(run_id)
    with _lock:
        _l1.clear()
    return cleared


def drop_run_progress_cache(run_id: str) -> None:
    try:
        _validate_run_id(run_id)
    except ValueError:
        return
    with _lock:
        _l1.pop(run_id, None)
    if _use_volume_files_api():
        with contextlib.suppress(Exception):
            from app.workflow_platform.workflow_data_volume import delete_relative

            delete_relative(_cache_volume_rel(run_id))
        return
    with contextlib.suppress(OSError):
        _path(run_id).unlink(missing_ok=True)


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
    cached_rank = preparation_stage_rank(str(cached_stage or ""))
    gateway_rank = preparation_stage_rank(str(gateway_stage or ""))

    try:
        from app.services.extraction import prepare_arango_step_completed

        prep_done = prepare_arango_step_completed(cached_stats) or prepare_arango_step_completed(
            gateway_stats
        )
    except Exception:
        prep_done = False

    if prep_done and cached_rank >= gateway_rank:
        stats["preparation_stage"] = cached_stage
        stats["preparation_message"] = cached_stats.get("preparation_message")
        stats["preparation_updated_at"] = cached_stats.get("preparation_updated_at")
        if cached_stats.get("preparation_progress") is not None:
            stats["preparation_progress"] = cached_stats.get("preparation_progress")
    elif not prep_done and gateway_stage and gateway_rank < cached_rank:
        stats["preparation_stage"] = gateway_stage
        stats["preparation_message"] = gateway_stats.get("preparation_message")
        stats["preparation_updated_at"] = gateway_stats.get("preparation_updated_at")
        if gateway_stats.get("preparation_progress") is not None:
            stats["preparation_progress"] = gateway_stats.get("preparation_progress")
    elif cached_rank >= gateway_rank:
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

    from app.services.run_agent_diagnostics import merge_agent_diagnostics_for_poll

    merged_diag = merge_agent_diagnostics_for_poll(cached_stats, gateway_stats)
    if merged_diag:
        stats["agent_diagnostics"] = merged_diag
    cached_token = cached_stats.get("token_usage")
    gateway_token = gateway_stats.get("token_usage")
    if isinstance(cached_token, dict):
        if not isinstance(gateway_token, dict):
            stats["token_usage"] = cached_token
        else:
            stats["token_usage"] = {
                "prompt_tokens": max(
                    int(gateway_token.get("prompt_tokens", 0)),
                    int(cached_token.get("prompt_tokens", 0)),
                ),
                "completion_tokens": max(
                    int(gateway_token.get("completion_tokens", 0)),
                    int(cached_token.get("completion_tokens", 0)),
                ),
                "total_tokens": max(
                    int(gateway_token.get("total_tokens", 0)),
                    int(cached_token.get("total_tokens", 0)),
                ),
            }

    merged["stats"] = stats
    cached_status = cached.get("status")
    gateway_status = merged.get("status")
    if run_status_rank(str(cached_status or "")) >= run_status_rank(str(gateway_status or "")):
        merged["status"] = cached_status
    try:
        from app.services.extraction import effective_status_for_ui

        merged["status"] = effective_status_for_ui({**merged, "stats": stats})
    except Exception:
        pass
    return merged
