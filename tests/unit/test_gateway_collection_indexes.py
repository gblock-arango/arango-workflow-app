"""GatewayCollection index helpers (parity with python-arango for migrations)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.db.gateway_database import GatewayCollection, GatewayDatabase


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
