"""004 — Create the ``domain_ontology`` named graph.

Per PRD Section 5.1, the domain_ontology graph uses:
  Vertices: ontology_classes, ontology_properties, ontology_constraints
  Edges:    subclass_of, equivalent_class, has_property, related_to
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

DOMAIN_ONTOLOGY_EDGE_DEFINITIONS = [
    {
        "edge_collection": "subclass_of",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["ontology_classes"],
    },
    {
        "edge_collection": "equivalent_class",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["ontology_classes"],
    },
    {
        "edge_collection": "has_property",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["ontology_properties"],
    },
    {
        "edge_collection": "related_to",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["ontology_classes"],
    },
]


def up(db: StandardDatabase) -> None:
    graph_name = "domain_ontology"
    if not db.has_graph(graph_name):
        db.create_graph(
            graph_name,
            edge_definitions=DOMAIN_ONTOLOGY_EDGE_DEFINITIONS,
        )
        log.info("created named graph %s", graph_name)
    else:
        log.debug("named graph %s already exists", graph_name)
