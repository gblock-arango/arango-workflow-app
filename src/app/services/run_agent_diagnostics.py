"""Cache-first LLM and agent telemetry for diagnostics status polls."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.run_progress_cache import get_cached_run_progress, update_run_progress_cache

log = logging.getLogger(__name__)

_EMPTY_DIAG: dict[str, Any] = {
    "agent_started_at": None,
    "llm_calls": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "prompt_chars": 0,
    "last_llm_at": None,
    "last_llm_step": None,
    "running_steps": [],
}


def usage_from_response(response: Any) -> tuple[int, int]:
    """Return (prompt_tokens, completion_tokens) from a LangChain response."""
    if not hasattr(response, "usage_metadata") or not response.usage_metadata:
        return 0, 0
    usage = response.usage_metadata
    prompt = int(usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("output_tokens", 0) or usage.get("completion_tokens", 0) or 0)
    return prompt, completion


def _read_agent_diagnostics(run_id: str) -> dict[str, Any]:
    cached = get_cached_run_progress(run_id)
    if cached is None:
        return dict(_EMPTY_DIAG)
    stats = cached.get("stats")
    if not isinstance(stats, dict):
        return dict(_EMPTY_DIAG)
    raw = stats.get("agent_diagnostics")
    if not isinstance(raw, dict):
        return dict(_EMPTY_DIAG)
    return {**_EMPTY_DIAG, **raw}


def _running_steps_from_logs(logs: list[dict[str, Any]]) -> list[str]:
    return [
        str(entry["step"])
        for entry in logs
        if isinstance(entry, dict) and entry.get("status") == "running" and entry.get("step")
    ]


def init_agent_diagnostics(
    run_id: str,
    *,
    message: str | None = None,
    preserve_preparation_status: bool = False,
) -> None:
    """Seed agent telemetry when LangGraph starts."""
    now = time.time()
    diag = {**_EMPTY_DIAG, "agent_started_at": now}
    msg = message or "LangGraph extraction pipeline running"
    if preserve_preparation_status:
        # Deferred prep: gateway/UC/schema still run inside prepare_arango — do not
        # flip status to running or stage to launching_pipeline yet.
        update_run_progress_cache(
            run_id,
            message=msg,
            stats_patch={"agent_diagnostics": diag},
            touch_session=False,
        )
        return
    update_run_progress_cache(
        run_id,
        status="running",
        stage="launching_pipeline",
        message=msg,
        stats_patch={"agent_diagnostics": diag},
        touch_session=False,
    )


def record_llm_call(
    run_id: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    prompt_chars: int = 0,
    step: str | None = None,
) -> None:
    """Increment LLM counters in the shared progress cache (no gateway I/O)."""
    try:
        from app.services.extraction import preparation_still_active

        diag = _read_agent_diagnostics(run_id)
        now = time.time()
        diag["llm_calls"] = int(diag.get("llm_calls", 0)) + 1
        diag["prompt_tokens"] = int(diag.get("prompt_tokens", 0)) + max(0, prompt_tokens)
        diag["completion_tokens"] = int(diag.get("completion_tokens", 0)) + max(0, completion_tokens)
        diag["total_tokens"] = int(diag["prompt_tokens"]) + int(diag["completion_tokens"])
        diag["prompt_chars"] = int(diag.get("prompt_chars", 0)) + max(0, prompt_chars)
        diag["last_llm_at"] = now
        if step:
            diag["last_llm_step"] = step
        if diag.get("agent_started_at") is None:
            diag["agent_started_at"] = now
        cached = get_cached_run_progress(run_id)
        status_patch: str | None = "running"
        if preparation_still_active(cached):
            status_patch = None
        update_run_progress_cache(
            run_id,
            status=status_patch,
            stats_patch={"agent_diagnostics": diag},
            touch_session=False,
        )
    except Exception:
        log.debug("could not record llm call", extra={"run_id": run_id}, exc_info=True)


def sync_agent_diagnostics_from_step_logs(
    run_id: str,
    step_logs: list[dict[str, Any]],
    *,
    current_step: str | None = None,
) -> None:
    """Refresh running agent list from step_logs without blocking on Arango."""
    try:
        from app.services.extraction import preparation_still_active

        diag = _read_agent_diagnostics(run_id)
        diag["running_steps"] = _running_steps_from_logs(step_logs)
        patch: dict[str, Any] = {"agent_diagnostics": diag, "step_logs": step_logs}
        if current_step is not None:
            patch["current_step"] = current_step
        cached = get_cached_run_progress(run_id)
        status_patch: str | None = "running"
        preview = dict(cached or {})
        preview["stats"] = {**(dict(preview.get("stats") or {})), **patch}
        if preparation_still_active(preview):
            status_patch = "preparing"
        update_run_progress_cache(
            run_id,
            status=status_patch,
            stats_patch=patch,
            touch_session=False,
        )
    except Exception:
        log.debug(
            "could not sync agent diagnostics from step_logs",
            extra={"run_id": run_id},
            exc_info=True,
        )


_LIVE_METRIC_KEYS = (
    "classes_extracted",
    "properties_extracted",
    "pass_agreement_rate",
    "merge_candidates_found",
    "belief_revision",
    "current_step",
)


def record_live_run_metrics(run_id: str, patch: dict[str, Any]) -> None:
    """Merge partial entity / agent metrics into the shared progress cache."""
    if not patch:
        return
    try:
        cached = get_cached_run_progress(run_id)
        stats = dict(cached.get("stats") or {}) if cached else {}
        for key in _LIVE_METRIC_KEYS:
            if key in patch and patch[key] is not None:
                stats[key] = patch[key]
        from app.services.extraction import preparation_still_active

        status_patch: str | None = "running"
        preview = dict(cached or {})
        preview["stats"] = stats
        if preparation_still_active(preview):
            status_patch = None
        update_run_progress_cache(
            run_id,
            status=status_patch,
            stats_patch=stats,
            touch_session=False,
        )
    except Exception:
        log.debug("could not record live run metrics", extra={"run_id": run_id}, exc_info=True)


def merge_agent_diagnostics_for_poll(
    cached_stats: dict[str, Any],
    gateway_stats: dict[str, Any],
) -> dict[str, Any]:
    """Never regress LLM counters when merging cache with gateway reads."""
    cached = cached_stats.get("agent_diagnostics")
    gateway = gateway_stats.get("agent_diagnostics")
    if not isinstance(cached, dict) and not isinstance(gateway, dict):
        return {}
    base = dict(gateway) if isinstance(gateway, dict) else {}
    if isinstance(cached, dict):
        for key in (
            "llm_calls",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_chars",
        ):
            base[key] = max(int(base.get(key, 0)), int(cached.get(key, 0)))
        for key in ("last_llm_at", "last_llm_step", "agent_started_at"):
            cached_val = cached.get(key)
            gateway_val = base.get(key)
            if cached_val is not None and (gateway_val is None or cached_val > gateway_val):
                base[key] = cached_val
        cached_running = cached.get("running_steps")
        gateway_running = base.get("running_steps")
        if isinstance(cached_running, list) and (
            not isinstance(gateway_running, list) or len(cached_running) >= len(gateway_running)
        ):
            base["running_steps"] = cached_running
    return base
