"""021 — Ontology release records and registry pointers.

Creates ``ontology_releases`` for versioned release history. Registry documents
gain optional denormalized fields (``current_release_*``, ``release_state``)
updated by the API when a release is created.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError

log = logging.getLogger(__name__)

_COLLECTION = "ontology_releases"


def up(db: StandardDatabase) -> None:
    if not db.has_collection(_COLLECTION):
        db.create_collection(_COLLECTION)
        log.info("created collection %s", _COLLECTION)

    col = db.collection(_COLLECTION)
    idx_name = "idx_ontology_releases_ontology_version"
    for idx in col.indexes():
        if idx.get("name") == idx_name:
            return
    try:
        col.add_persistent_index(
            fields=["ontology_id", "version"],
            unique=True,
            name=idx_name,
        )
    except IndexCreateError:
        log.warning("could not create unique index %s", idx_name, exc_info=True)
