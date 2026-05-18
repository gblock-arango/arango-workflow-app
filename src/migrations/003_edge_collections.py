"""003 — Create all ontology edge collections.

Edge collections: subclass_of, equivalent_class, has_property, extends_domain,
extracted_from, related_to, merge_candidate, imports.
All carry ``created`` and ``expired`` fields for temporal semantics.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

EDGE_COLLECTIONS = [
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
    for name in EDGE_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name, edge=True)
            log.info("created edge collection %s", name)
        else:
            log.debug("edge collection %s already exists", name)
