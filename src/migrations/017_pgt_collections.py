"""017 — Create PGT-aligned property collections.

Creates separate vertex collections for ObjectProperty and DatatypeProperty,
and edge collections for rdfs:domain and rdfs:range relationships.
See ADR-006.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError
from arango.request import Request

log = logging.getLogger(__name__)

PGT_VERTEX_COLLECTIONS = [
    "ontology_object_properties",
    "ontology_datatype_properties",
]

PGT_EDGE_COLLECTIONS = [
    "rdfs_domain",
    "rdfs_range_class",
]

ALL_PGT_COLLECTIONS = PGT_VERTEX_COLLECTIONS + PGT_EDGE_COLLECTIONS


def _create_mdi_index(db: StandardDatabase, collection_name: str) -> None:
    """Create an mdi-prefixed temporal index; fall back to persistent."""
    idx_name = f"idx_{collection_name}_mdi_temporal"
    col = db.collection(collection_name)

    for idx in col.indexes():
        if idx.get("name") == idx_name:
            log.debug("index %s already exists on %s", idx_name, collection_name)
            return

    body = {
        "type": "mdi-prefixed",
        "fields": ["created", "expired"],
        "fieldValueTypes": "double",
        "prefixFields": ["ontology_id"],
        "sparse": False,
        "name": idx_name,
    }
    try:
        req = Request(
            method="post",
            endpoint=f"/_api/index?collection={collection_name}",
            data=body,
        )
        resp = db._conn.send_request(req)
        if resp.status_code in (200, 201):
            log.info("created mdi-prefixed index %s on %s", idx_name, collection_name)
            return
        log.warning(
            "mdi-prefixed index creation returned %s on %s — trying fallback",
            resp.status_code,
            collection_name,
        )
    except Exception as exc:
        log.warning(
            "mdi-prefixed index creation failed on %s: %s — trying fallback",
            collection_name,
            exc,
        )

    try:
        col.add_persistent_index(
            fields=["ontology_id", "created", "expired"],
            name=idx_name,
        )
        log.info(
            "created persistent (fallback) index %s on %s",
            idx_name,
            collection_name,
        )
    except IndexCreateError:
        log.debug(
            "index %s already exists on %s (via fallback)",
            idx_name,
            collection_name,
        )


def up(db: StandardDatabase) -> None:
    for name in PGT_VERTEX_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name)
            log.info("created vertex collection %s", name)
        else:
            log.debug("vertex collection %s already exists", name)

    for name in PGT_EDGE_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name, edge=True)
            log.info("created edge collection %s", name)
        else:
            log.debug("edge collection %s already exists", name)

    for name in ALL_PGT_COLLECTIONS:
        _create_mdi_index(db, name)
