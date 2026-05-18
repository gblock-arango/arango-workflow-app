"""002 — Create versioned vertex collections for temporal ontology data.

Collections: ontology_classes, ontology_properties, ontology_constraints.
These carry ``created`` and ``expired`` timestamp fields for edge-interval
time travel.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

VERSIONED_VERTEX_COLLECTIONS = [
    "ontology_classes",
    "ontology_properties",
    "ontology_constraints",
]


def up(db: StandardDatabase) -> None:
    for name in VERSIONED_VERTEX_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name)
            log.info("created versioned vertex collection %s", name)
        else:
            log.debug("versioned vertex collection %s already exists", name)
