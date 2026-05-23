"""Ensure OntoExtract ArangoDB schema (migrations) before chunking or extraction."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from app.db.client import get_db
from app.db.schema import init_schema
from app.db.types import StandardDatabase

log = logging.getLogger(__name__)

_lock = threading.Lock()
_last_applied: list[str] | None = None

_STAGING_COLLECTIONS = ("documents", "chunks")


def ensure_staging_schema(*, db: StandardDatabase | None = None) -> dict[str, Any]:
    """Ensure ``documents`` / ``chunks`` exist for UC upload staging only.

    Does **not** run full ontology migrations (graphs, TTL indexes, etc.). Use
    :func:`ensure_ontology_schema` before parse/chunk/embed, extraction, or ontology import.
    """
    database = db or get_db()
    created: list[str] = []
    for name in _STAGING_COLLECTIONS:
        if not database.has_collection(name):
            database.create_collection(name)
            created.append(name)
            log.info("staging schema: created collection %s", name)
    return {"ok": True, "collections_created": created}


async def ensure_staging_schema_async(*, db: StandardDatabase | None = None) -> dict[str, Any]:
    return await asyncio.to_thread(ensure_staging_schema, db=db)


def ensure_ontology_schema(*, db: StandardDatabase | None = None) -> dict[str, Any]:
    """Apply pending migrations idempotently (``make migrate`` equivalent).

    Safe to call before document chunking or extraction runs. Uses a process-wide
    lock so concurrent prepares only run the migration runner once at a time.
    """
    global _last_applied

    database = db or get_db()
    with _lock:
        newly_applied = init_schema(database)
        if newly_applied:
            _last_applied = newly_applied
            log.info(
                "ontology schema bootstrap applied migrations",
                extra={"count": len(newly_applied), "migrations": newly_applied},
            )
        else:
            log.debug("ontology schema bootstrap: already up to date")

    return {
        "ok": True,
        "migrations_applied": newly_applied,
        "migration_count": len(newly_applied),
    }


async def ensure_ontology_schema_async(*, db: StandardDatabase | None = None) -> dict[str, Any]:
    """Run :func:`ensure_ontology_schema` in a worker thread (do not block the event loop)."""
    return await asyncio.to_thread(ensure_ontology_schema, db=db)
