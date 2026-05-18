"""006 — Sparse TTL indexes on ``ttlExpireAt`` for all versioned collections.

Historical versions (those with ``expired != NEVER_EXPIRES``) are
garbage-collected via ArangoDB's TTL index mechanism.  Current documents
have ``ttlExpireAt = null`` and are skipped thanks to ``sparse: true``.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError

log = logging.getLogger(__name__)

VERSIONED_COLLECTIONS = [
    "ontology_classes",
    "ontology_properties",
    "ontology_constraints",
    "subclass_of",
    "equivalent_class",
    "has_property",
    "extends_domain",
    "extracted_from",
    "related_to",
    "merge_candidate",
    "imports",
]


def up(db: StandardDatabase) -> None:
    for name in VERSIONED_COLLECTIONS:
        idx_name = f"idx_{name}_ttl"
        col = db.collection(name)

        for idx in col.indexes():
            if idx.get("name") == idx_name:
                log.debug("TTL index %s already exists on %s", idx_name, name)
                break
        else:
            try:
                col.add_ttl_index(
                    fields=["ttlExpireAt"],
                    expiry_time=0,
                    name=idx_name,
                    in_background=True,
                )
                log.info("created TTL index %s on %s", idx_name, name)
            except IndexCreateError:
                log.debug("TTL index %s already exists on %s (race)", idx_name, name)
