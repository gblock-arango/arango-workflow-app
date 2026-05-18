"""015 — ArangoSearch view for ontology library full-text search (J.5).

Creates an ``ontology_search_view`` covering:
- ``ontology_registry``: name, description
- ``ontology_classes``: label, description
- ``ontology_properties``: label

Uses ``text_en`` analyzer for full-text search with BM25 ranking.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

VIEW_NAME = "ontology_search_view"

VIEW_PROPERTIES = {
    "links": {
        "ontology_registry": {
            "analyzers": ["text_en"],
            "includeAllFields": False,
            "fields": {
                "name": {"analyzers": ["text_en"]},
                "description": {"analyzers": ["text_en"]},
            },
        },
        "ontology_classes": {
            "analyzers": ["text_en"],
            "includeAllFields": False,
            "fields": {
                "label": {"analyzers": ["text_en"]},
                "description": {"analyzers": ["text_en"]},
            },
        },
        "ontology_properties": {
            "analyzers": ["text_en"],
            "includeAllFields": False,
            "fields": {
                "label": {"analyzers": ["text_en"]},
            },
        },
    },
}


def up(db: StandardDatabase) -> None:
    for col_name in ("ontology_registry", "ontology_classes", "ontology_properties"):
        if not db.has_collection(col_name):
            db.create_collection(col_name)
            log.info("created collection %s for search view", col_name)

    existing_views = {v["name"] for v in db.views()}
    if VIEW_NAME in existing_views:
        log.debug("ArangoSearch view %s already exists", VIEW_NAME)
        return

    db.create_arangosearch_view(VIEW_NAME, properties=VIEW_PROPERTIES)
    log.info("created ArangoSearch view %s", VIEW_NAME)
