"""007 — ArangoSearch view on ``ontology_classes`` for BM25 blocking.

Creates an ``ontology_classes_search`` view covering ``label`` and
``description`` fields with ``text_en`` analyzer for full-text search
used by entity resolution blocking and the search API.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

VIEW_NAME = "ontology_classes_search"

VIEW_PROPERTIES = {
    "links": {
        "ontology_classes": {
            "analyzers": ["text_en"],
            "includeAllFields": False,
            "fields": {
                "label": {"analyzers": ["text_en"]},
                "description": {"analyzers": ["text_en"]},
            },
        },
    },
}


def up(db: StandardDatabase) -> None:
    existing_views = {v["name"] for v in db.views()}
    if VIEW_NAME in existing_views:
        log.debug("ArangoSearch view %s already exists", VIEW_NAME)
        return

    db.create_arangosearch_view(VIEW_NAME, properties=VIEW_PROPERTIES)
    log.info("created ArangoSearch view %s", VIEW_NAME)
