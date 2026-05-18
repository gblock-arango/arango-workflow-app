"""WebSocket endpoint for extraction pipeline progress per PRD Section 7.8.

Events: step_started, step_completed, step_failed, pipeline_paused, completed.
Uses in-memory event bus (asyncio.Queue) with event history replay for late
joiners. Redis Pub/Sub is Phase 6.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket

from app.api.ws_broadcast import WebSocketBroadcaster

router = APIRouter()

_broadcaster = WebSocketBroadcaster(keep_history=True)

_TERMINAL_EVENTS = frozenset({"completed", "failed"})


async def publish_event(
    *,
    run_id: str,
    event_type: str,
    step: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Publish an event to all WebSocket subscribers for a run."""
    await _broadcaster.publish(
        key=run_id,
        event_type=event_type,
        data=data,
        type=event_type,
        step=step,
        run_id=run_id,
    )


def cleanup_run(run_id: str) -> None:
    """Remove all subscribers and event history for a completed run."""
    _broadcaster.cleanup(run_id)


@router.websocket("/ws/extraction/{run_id}")
async def ws_extraction(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint for real-time extraction pipeline updates.

    Replays any missed events on connect, then streams live updates.
    """
    await _broadcaster.serve(
        websocket,
        run_id,
        connected_data={"run_id": run_id},
        terminal_events=_TERMINAL_EVENTS,
    )
