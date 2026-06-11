"""GatewayGraph edge definition helpers for migrations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db.gateway_database import GatewayGraph


def test_edge_definitions_normalizes_arango_shape():
    db = MagicMock()
    graph = GatewayGraph(db, "domain_ontology")
    with patch.object(
        graph,
        "properties",
        return_value={
            "edge_definitions": [
                {
                    "collection": "subclass_of",
                    "from": ["ontology_classes"],
                    "to": ["ontology_classes"],
                }
            ]
        },
    ):
        defs = graph.edge_definitions()
    assert defs[0]["edge_collection"] == "subclass_of"
    assert defs[0]["from_vertex_collections"] == ["ontology_classes"]


def test_create_edge_definition_posts_to_gharial():
    db = MagicMock()
    db.name = "AutoGraph_1"
    db._request.return_value = {"ok": True, "body": {"graph": {}}}
    graph = GatewayGraph(db, "domain_ontology")
    graph.create_edge_definition(
        "extracted_from",
        ["ontology_classes"],
        ["documents"],
    )
    db._request.assert_called_once()
    path = db._request.call_args[0][1]
    assert "/_api/gharial/domain_ontology/edge" in path
    body = db._request.call_args[1]["json_body"]
    assert body["collection"] == "extracted_from"


def test_has_edge_definition():
    db = MagicMock()
    graph = GatewayGraph(db, "g1")
    with patch.object(
        graph,
        "edge_definitions",
        return_value=[{"edge_collection": "has_chunk"}],
    ):
        assert graph.has_edge_definition("has_chunk")
        assert not graph.has_edge_definition("missing")
