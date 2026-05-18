"""WebSocket endpoint for curation collaboration per PRD Section 7.8.

Events: decision_made, entity_merged, staging_promoted.
Broadcasts curation decision events to all connected curators on the same session.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket

from app.api.ws_broadcast import WebSocketBroadcaster

router = APIRouter()

_broadcaster = WebSocketBroadcaster(keep_history=False)


async def publish_curation_event(
    *,
    session_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
    user_id: str = "",
) -> None:
    """Publish a curation event to all WebSocket subscribers for a session."""
    await _broadcaster.publish(
        key=session_id,
        event_type=event_type,
        data=data,
        user_id=user_id,
        session_id=session_id,
    )


def cleanup_session(session_id: str) -> None:
    """Remove all subscribers for a closed session."""
    _broadcaster.cleanup(session_id)


@router.websocket("/ws/curation/{session_id}")
async def ws_curation(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time curation collaboration.

    Curators on the same session receive events as decisions are made.
    """
    await _broadcaster.serve(
        websocket,
        session_id,
        connected_data={"session_id": session_id},
    )
