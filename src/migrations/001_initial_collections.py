"""001 — Create non-temporal document collections.

Collections: documents, chunks, extraction_runs, curation_decisions,
notifications, organizations, users, aoe_system_meta, ontology_registry.
"""

from __future__ import annotations

import logging

from app.db.types import StandardDatabase

log = logging.getLogger(__name__)

NON_TEMPORAL_COLLECTIONS = [
    "documents",
    "chunks",
    "extraction_runs",
    "curation_decisions",
    "notifications",
    "organizations",
    "users",
    "aoe_system_meta",
    "ontology_registry",
]


def _existing_collection_names(db: StandardDatabase) -> set[str]:
    names: set[str] = set()
    for item in db.collections():
        if isinstance(item, dict):
            name = item.get("name") or item.get("_key")
        else:
            name = getattr(item, "name", None)
        if name:
            names.add(str(name))
    return names


def up(db: StandardDatabase) -> None:
    # One catalog listing instead of has_collection per name (gateway mode).
    existing = _existing_collection_names(db)
    for name in NON_TEMPORAL_COLLECTIONS:
        if name in existing:
            log.debug("collection %s already exists", name)
            continue
        db.create_collection(name)
        log.info("created collection %s", name)
