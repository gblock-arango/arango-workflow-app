"""Progressive gateway / Arango checkpoints during extraction preparation."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.db.gateway_connectivity import gateway_connectivity_status
from app.db.gateway_errors import format_gateway_error
from app.db.types import StandardDatabase
from app.services.run_progress_cache import get_cached_run_progress, update_run_progress_cache

log = logging.getLogger(__name__)

STAGE_QUEUED = "queued"
STAGE_GATEWAY_HEALTH = "gateway_health"
STAGE_GATEWAY_ARANGO = "gateway_arango"
STAGE_RUN_PERSISTED = "run_persisted"
STAGE_MATERIALIZING = "materializing_arango"
STAGE_SCHEMA = "schema_migrations"
STAGE_LAUNCHING = "launching_pipeline"


def _append_checkpoint(
    run_id: str,
    *,
    stage: str,
    message: str,
    ok: bool,
    progress: dict[str, Any] | None,
) -> dict[str, Any]:
    cached = get_cached_run_progress(run_id)
    prior = (
        (cached or {}).get("stats", {}).get("preparation_progress", {})
        if isinstance((cached or {}).get("stats"), dict)
        else {}
    )
    checkpoints = list(prior.get("checkpoints") or [])
    checkpoints.append(
        {
            "at": time.time(),
            "stage": stage,
            "ok": ok,
            "message": message[:240],
        }
    )
    merged: dict[str, Any] = dict(prior)
    if progress:
        merged.update(progress)
    merged["checkpoints"] = checkpoints[-24:]
    merged["last_checkpoint_at"] = time.time()
    return merged


def record_checkpoint_cache(
    run_id: str,
    *,
    stage: str,
    message: str,
    ok: bool = True,
    progress: dict[str, Any] | None = None,
) -> None:
    """Write a preparation checkpoint to the shared file cache (instant UI poll)."""
    merged = _append_checkpoint(run_id, stage=stage, message=message, ok=ok, progress=progress)
    update_run_progress_cache(
        run_id,
        status="failed" if not ok else "preparing",
        stage=stage,
        message=message,
        progress=merged,
    )


def record_checkpoint_arango(
    db: StandardDatabase,
    run_id: str,
    *,
    stage: str,
    message: str,
    ok: bool = True,
    progress: dict[str, Any] | None = None,
) -> None:
    """Write checkpoint to cache first, then best-effort Arango stats."""
    from app.services.extraction import update_run_preparation

    merged = _append_checkpoint(run_id, stage=stage, message=message, ok=ok, progress=progress)
    update_run_preparation(
        db,
        run_id,
        stage=stage,
        message=message,
        progress=merged,
    )


def probe_gateway_health_checkpoint(run_id: str) -> None:
    """Fast ``GET /health`` on arango-gateway-app — confirms HTTP path before Arango REST."""
    record_checkpoint_cache(
        run_id,
        stage=STAGE_GATEWAY_HEALTH,
        message="Probing gateway /health…",
        progress={"phase": "gateway_health"},
    )
    started = time.perf_counter()

    def on_health_attempt(attempt: int, total: int, _phase: str) -> None:
        if attempt == 1:
            return
        record_checkpoint_cache(
            run_id,
            stage=STAGE_GATEWAY_HEALTH,
            message=f"Probing gateway /health (attempt {attempt}/{total})…",
            progress={
                "phase": "gateway_health",
                "health_attempt": attempt,
                "health_attempt_total": total,
            },
        )

    status = gateway_connectivity_status(on_health_attempt=on_health_attempt)
    latency_ms = int((time.perf_counter() - started) * 1000)
    ok = bool(status.get("gateway_ok"))
    gateway_url = str(status.get("gateway_url") or "")
    detail = str(status.get("gateway_message") or "unknown")
    progress = {
        "phase": "gateway_health",
        "gateway_ok": ok,
        "gateway_url": gateway_url,
        "gateway_message": detail,
        "latency_ms": latency_ms,
    }
    if not ok:
        hint = detail
        if "401" in detail:
            hint = (
                f"{detail} — prepare thread uses this app's service principal (M2M). "
                "Grant CAN_USE on arango-gateway-app for the workflow SP: "
                "scripts/grant_peer_app_can_use.py (see EXTRACTION_VERIFY_STEPS.md Step −1)."
            )
        elif "timed out" in detail.lower() or "timeout" in detail.lower():
            hint = (
                f"{detail} — gateway app is RUNNING but /health did not answer in time "
                "(workers likely busy on Arango proxy traffic; not a CAN_USE/auth failure). "
                "Wait a minute and retry extraction, or restart arango-gateway-app to clear the queue."
            )
        record_checkpoint_cache(
            run_id,
            stage=STAGE_GATEWAY_HEALTH,
            message=f"Gateway /health failed ({latency_ms}ms): {hint}",
            ok=False,
            progress=progress,
        )
        raise RuntimeError(f"Gateway /health failed: {hint}")

    record_checkpoint_cache(
        run_id,
        stage=STAGE_GATEWAY_ARANGO,
        message=f"Gateway /health OK ({latency_ms}ms) — opening Arango via proxy…",
        progress=progress,
    )


def connect_arango_checkpoint(run_id: str) -> tuple[Any, Any]:
    """``get_db()`` through gateway proxy; surfaces connect latency to UI."""
    from app.config import settings as app_settings
    from app.db.client import (
        _is_missing_database_error,
        get_db,
        recover_missing_arango_database,
    )
    from app.db.gateway_database import GatewayAPIError
    from app.services.extraction import _apply_run_arango_database, _get_collection

    _apply_run_arango_database(run_id)
    started = time.perf_counter()
    db = None
    col = None
    last_exc: BaseException | None = None
    for attempt in range(2):
        try:
            db = get_db()
            col = _get_collection(db, "extraction_runs")
            break
        except (GatewayAPIError, RuntimeError) as exc:
            last_exc = exc
            if (
                attempt == 0
                and app_settings.can_create_databases
                and _is_missing_database_error(exc)
            ):
                recover_missing_arango_database()
                continue
            message = format_gateway_error(exc)
            if not app_settings.can_create_databases and _is_missing_database_error(exc):
                message = (
                    f"{message} — recreate database {app_settings.arango_db!r} in Arango "
                    "(auto-create is disabled on managed_platform)."
                )
            record_checkpoint_cache(
                run_id,
                stage=STAGE_GATEWAY_ARANGO,
                message=f"Arango session failed ({message[:200]})",
                ok=False,
                progress={"phase": "gateway_arango", "gateway_ok": True, "arango_ok": False},
            )
            raise RuntimeError(message) from exc
    if db is None or col is None:
        assert last_exc is not None
        raise last_exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    from app.services.run_progress_cache import get_cached_run_progress

    db_label = (get_cached_run_progress(run_id) or {}).get("arango_database") or "Arango"
    record_checkpoint_cache(
        run_id,
        stage=STAGE_RUN_PERSISTED,
        message=(
            f"Arango session ready on {db_label} ({latency_ms}ms) — persisting run record…"
        ),
        progress={
            "phase": "gateway_arango",
            "gateway_ok": True,
            "connect_latency_ms": latency_ms,
            "collection": "extraction_runs",
        },
    )
    return db, col


def persist_run_record_checkpoint(
    db: Any,
    col: Any,
    run_id: str,
    run_record: dict[str, Any],
) -> None:
    """Insert run doc if missing and read back to prove gateway wrote to Arango."""
    from app.db.utils import doc_get

    started = time.perf_counter()
    if doc_get(col, run_id) is None:
        if run_record is None:
            record_checkpoint_cache(
                run_id,
                stage=STAGE_RUN_PERSISTED,
                message="Run record missing in Arango and no run_record supplied",
                ok=False,
            )
            raise ValueError(f"Run {run_id} not found in Arango and no run_record supplied")
        record_checkpoint_cache(
            run_id,
            stage=STAGE_RUN_PERSISTED,
            message="Inserting run record into Arango via gateway…",
            progress={"phase": "run_persisted", "step": "insert"},
        )
        col.insert(run_record)
        record_checkpoint_cache(
            run_id,
            stage=STAGE_RUN_PERSISTED,
            message="Run record inserted — verifying read-back via gateway…",
            progress={"phase": "run_persisted", "step": "read_back"},
        )
    stored = doc_get(col, run_id)
    latency_ms = int((time.perf_counter() - started) * 1000)
    if stored is None:
        record_checkpoint_cache(
            run_id,
            stage=STAGE_RUN_PERSISTED,
            message="Run insert failed — read-back returned empty",
            ok=False,
            progress={"phase": "run_persisted", "latency_ms": latency_ms},
        )
        raise RuntimeError(f"Run {run_id} not found in Arango after insert")

    record_checkpoint_arango(
        db,
        run_id,
        stage=STAGE_RUN_PERSISTED,
        message=(
            f"Run record confirmed in Arango ({latency_ms}ms) — "
            f"status={stored.get('status', 'preparing')}"
        ),
        progress={
            "phase": "run_persisted",
            "arango_verified": True,
            "latency_ms": latency_ms,
            "run_status": stored.get("status"),
        },
    )
    log.info(
        "extraction run persisted via gateway",
        extra={"run_id": run_id, "latency_ms": latency_ms},
    )
