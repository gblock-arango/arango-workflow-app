"""GatewayCollection index helpers (parity with python-arango for migrations)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.db.gateway_database import (
    GatewayCollection,
    GatewayDatabase,
    _collection_create_body,
)


def test_create_collection_maps_edge_to_type_3():
    body = _collection_create_body("produced_by", edge=True)
    assert body == {"name": "produced_by", "type": 3}
    assert "edge" not in body


def test_create_collection_document_default():
    body = _collection_create_body("documents")
    assert body == {"name": "documents"}


def test_create_collection_edge_false_sets_document_type():
    body = _collection_create_body("documents", edge=False)
    assert body == {"name": "documents", "type": 2}


def test_create_collection_via_gateway_posts_type_not_edge():
    client = MagicMock()
    client.request.return_value = {"ok": True, "body": {"error": False, "name": "rdfs_domain"}}
    db = GatewayDatabase(client, "OntoExtract")
    db.create_collection("rdfs_domain", edge=True)

    _method, path, kwargs = (
        client.request.call_args[0][0],
        client.request.call_args[0][1],
        client.request.call_args[1],
    )
    assert _method == "POST"
    assert "/_api/collection" in path
    assert kwargs.get("json_body") == {"name": "rdfs_domain", "type": 3}


def test_add_ttl_index_posts_ttl_body():
    client = MagicMock()
    client.request.return_value = {"ok": True, "body": {"id": "idx/1"}}
    db = GatewayDatabase(client, "OntoExtract")
    col = GatewayCollection(db, "ontology_classes")

    col.add_ttl_index(
        fields=["ttlExpireAt"],
        expiry_time=0,
        name="idx_ontology_classes_ttl",
        in_background=True,
    )

    client.request.assert_called_once()
    _method, path, kwargs = client.request.call_args[0][0], client.request.call_args[0][1], client.request.call_args[1]
    assert _method == "POST"
    assert "OntoExtract" in path
    assert "ontology_classes" in path
    body = kwargs.get("json_body") or client.request.call_args.kwargs.get("json_body")
    assert body == {
        "type": "ttl",
        "fields": ["ttlExpireAt"],
        "expireAfter": 0,
        "name": "idx_ontology_classes_ttl",
        "inBackground": True,
    }


def test_update_return_new_wraps_document():
    client = MagicMock()
    client.request.return_value = {
        "ok": True,
        "body": {"_id": "documents/d1", "_key": "d1", "_rev": "1", "filename": "a.pdf"},
    }
    db = GatewayDatabase(client, "OntoExtract")
    col = GatewayCollection(db, "documents")

    result = col.update(
        {"_key": "d1", "metadata": {"volume_relative_path": "uploads/d1/a.pdf"}},
        return_new=True,
    )

    assert "new" in result
    assert result["new"]["_key"] == "d1"
    assert client.request.call_args[0][1].endswith("?returnNew=true")


def test_delete_index_uses_collection_and_handle_in_path():
    client = MagicMock()
    client.request.return_value = {"ok": True, "body": {"error": False}}
    db = GatewayDatabase(client, "OntoExtract")
    col = GatewayCollection(db, "chunks")

    col.delete_index("chunks/12345")

    client.request.assert_called_once()
    method, path = client.request.call_args[0][0], client.request.call_args[0][1]
    assert method == "DELETE"
    assert "/_api/index/chunks/12345" in path
