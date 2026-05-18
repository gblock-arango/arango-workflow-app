"""020 — Repair MDI-prefixed temporal indexes.

Older deployments may have been created with incorrect ``prefixFields`` (for
example ``created`` instead of ``ontology_id``), which defeats efficient
ontology-scoped temporal queries.

Idempotent: drops ``idx_<collection>_mdi_temporal`` when present, then
recreates mdi-prefixed (or persistent fallback) indexes matching migration 005.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError
from arango.request import Request

log = logging.getLogger(__name__)

# Same scope as 005 + PGT (017) + process edges that carry ontology_id + temporal fields.
COLLECTIONS_FOR_MDI_TEMPORAL: tuple[str, ...] = (
    "ontology_classes",
    "ontology_properties",
    "ontology_constraints",
    "ontology_object_properties",
    "ontology_datatype_properties",
    "subclass_of",
    "equivalent_class",
    "has_property",
    "extends_domain",
    "extracted_from",
    "related_to",
    "merge_candidate",
    "imports",
    "rdfs_domain",
    "rdfs_range_class",
    "has_chunk",
    "produced_by",
)


def _drop_named_index(db: StandardDatabase, collection_name: str, index_name: str) -> bool:
    if not db.has_collection(collection_name):
        return False
    col = db.collection(collection_name)
    for idx in col.indexes():
        if idx.get("name") == index_name:
            col.delete_index(idx["id"])
            log.info("dropped index %s on %s", index_name, collection_name)
            return True
    return False


def _create_mdi_index(db: StandardDatabase, collection_name: str) -> None:
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
        log.debug("index %s already exists on %s (via fallback)", idx_name, collection_name)


def up(db: StandardDatabase) -> None:
    for name in COLLECTIONS_FOR_MDI_TEMPORAL:
        if not db.has_collection(name):
            continue
        idx_name = f"idx_{name}_mdi_temporal"
        _drop_named_index(db, name, idx_name)
        _create_mdi_index(db, name)
