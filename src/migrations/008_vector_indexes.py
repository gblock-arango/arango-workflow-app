"""008 — Placeholder for vector index on ``chunks.embedding``.

The vector index (type: vector, Faiss IVF) requires training data to exist
in the collection before it can be created.  Index creation is therefore
handled at the end of the ingestion pipeline (see ``app/tasks.py``) rather
than at migration time.

This migration only cleans up any previously-created broken inverted index.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

_OLD_INDEX_NAME = "idx_chunks_embedding_hnsw"


def up(db: StandardDatabase) -> None:
    if not db.has_collection("chunks"):
        return

    col = db.collection("chunks")
    for idx in col.indexes():
        if idx.get("name") == _OLD_INDEX_NAME:
            col.delete_index(idx["id"])
            log.info("dropped broken inverted index %s from chunks", _OLD_INDEX_NAME)
            return

    log.debug("no broken index to clean up")
