"""Unit tests for batched Arango writes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db import bulk_write


class TestBulkInsertDocuments:
    def test_empty_returns_zero(self):
        db = MagicMock()
        assert bulk_write.bulk_insert_documents(db, "chunks", []) == 0

    def test_vertex_batches_use_aql(self, monkeypatch):
        db = MagicMock()
        calls: list[tuple] = []

        def fake_run_aql(_db, query, bind_vars=None, **_kw):
            calls.append((query, bind_vars))
            return iter([])

        monkeypatch.setattr(bulk_write, "run_aql", fake_run_aql)

        docs = [{"_key": f"c{i}", "text": f"t{i}"} for i in range(3)]
        written = bulk_write.bulk_insert_documents(
            db,
            "chunks",
            docs,
            batch_size=2,
            overwrite_mode="replace",
        )

        assert written == 3
        assert len(calls) == 2
        assert calls[0][1]["@col"] == "chunks"
        assert len(calls[0][1]["docs"]) == 2
        assert len(calls[1][1]["docs"]) == 1

    def test_edge_batches_merge_from_to(self, monkeypatch):
        db = MagicMock()
        calls: list[tuple] = []

        def fake_run_aql(_db, query, bind_vars=None, **_kw):
            calls.append((query, bind_vars))
            return iter([])

        monkeypatch.setattr(bulk_write, "run_aql", fake_run_aql)

        edges = [
            {"_from": "documents/d1", "_to": "chunks/c0", "ontology_id": "o1"},
        ]
        bulk_write.bulk_insert_documents(
            db,
            "has_chunk",
            edges,
            is_edge=True,
            overwrite_mode="replace",
        )

        assert "MERGE({ _from: doc._from, _to: doc._to }" in calls[0][0]


class TestBulkInsertTemporalEdgesIfAbsent:
    def test_batches_idempotent_insert(self, monkeypatch):
        db = MagicMock()
        calls: list[dict] = []

        def fake_run_aql(_db, query, bind_vars=None, **_kw):
            calls.append(bind_vars or {})
            return iter([])

        monkeypatch.setattr(bulk_write, "run_aql", fake_run_aql)

        edges = [
            {
                "_from": "ontology_datatype_properties/p1",
                "_to": "ontology_classes/c1",
                "ontology_id": "ont-1",
                "created": 1.0,
                "expired": bulk_write.NEVER_EXPIRES,
            }
        ]
        count = bulk_write.bulk_insert_temporal_edges_if_absent(db, "rdfs_domain", edges)

        assert count == 1
        assert calls[0]["@col"] == "rdfs_domain"
        assert calls[0]["edges"] == edges


class TestInsertManyViaHttpBatch:
    def test_returns_none_for_single_batch(self):
        from app.db.gateway_database import GatewayDatabase

        client = MagicMock()
        db = GatewayDatabase(client, "OntoExtract")

        result = bulk_write.insert_many_via_http_batch(
            db,
            "chunks",
            [{"text": "a"}],
            batch_size=50,
        )

        assert result is None

    def test_packs_multiple_batches_into_one_gateway_call(self):
        from app.db.gateway_database import GatewayDatabase

        client = MagicMock()
        db = GatewayDatabase(client, "OntoExtract")

        client.request_batch.return_value = {
            "ok": True,
            "results": [
                {"ok": True, "body": [{"_key": "c0"}, {"_key": "c1"}]},
                {"ok": True, "body": [{"_key": "c2"}]},
            ],
        }

        docs = [{"text": f"t{i}"} for i in range(3)]
        with patch.object(bulk_write, "http_batch_writes_enabled", return_value=True):
            inserted = bulk_write.insert_many_via_http_batch(
                db,
                "chunks",
                docs,
                batch_size=2,
            )

        assert inserted is not None
        assert len(inserted) == 3
        assert client.request_batch.call_count == 1
        requests = client.request_batch.call_args[0][0]
        assert len(requests) == 2
