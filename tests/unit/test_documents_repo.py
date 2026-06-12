"""Unit tests for document repository delete flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db import documents_repo


def _db_with_collections(*names: str) -> MagicMock:
    db = MagicMock()
    available = set(names)
    db.has_collection.side_effect = lambda name: name in available
    return db


class TestDeleteDocumentRepo:
    def test_delete_document_preview_returns_affected_ontologies(self):
        db = _db_with_collections("extracted_from", "ontology_registry")

        with patch(
            "app.db.documents_repo.run_aql",
            side_effect=[
                ["onto1"],
                [{"_key": "onto1", "name": "Ontology 1", "status": "active"}],
            ],
        ) as mock_run_aql:
            result = documents_repo.delete_document("d1", confirm=False, db=db)

        assert result == {
            "doc_id": "d1",
            "status": "pending_confirmation",
            "affected_ontologies": [{"_key": "onto1", "name": "Ontology 1", "status": "active"}],
            "message": "Pass ?confirm=true to proceed with deletion.",
        }
        assert mock_run_aql.call_count == 2

    def test_delete_document_confirm_expires_edges_and_deletes_document(self):
        db = _db_with_collections("extracted_from", "ontology_registry")

        with (
            patch(
                "app.db.documents_repo.run_aql",
                side_effect=[
                    ["onto1"],
                    [{"_key": "onto1", "name": "Ontology 1", "status": "active"}],
                    ["edge1", "edge2"],
                ],
            ) as mock_run_aql,
            patch(
                "app.db.documents_repo.delete_chunks_for_document", return_value=3
            ) as mock_delete_chunks,
            patch("app.db.documents_repo.hard_delete_document", return_value=True) as mock_delete,
        ):
            result = documents_repo.delete_document("d1", confirm=True, db=db)

        assert result == {
            "doc_id": "d1",
            "status": "deleted",
            "chunks_removed": 3,
            "affected_ontologies": [{"_key": "onto1", "name": "Ontology 1", "status": "active"}],
        }
        assert mock_run_aql.call_count == 3
        mock_delete_chunks.assert_called_once_with("d1", db=db)
        mock_delete.assert_called_once_with("d1", db=db)


class TestCreateChunks:
    def _chunks(self, n: int) -> list[dict]:
        return [{"doc_id": "d1", "chunk_index": i, "text": f"t{i}"} for i in range(n)]

    def test_create_chunks_empty(self):
        db = _db_with_collections("chunks")
        assert documents_repo.create_chunks([], db=db) == []

    def test_create_chunks_uses_insert_many_in_batches(self):
        db = _db_with_collections("chunks")
        col = MagicMock()
        db.collection.return_value = col
        col.insert_many.side_effect = [
            [{"_key": f"c{i}", "_id": f"chunks/c{i}"} for i in range(50)],
            [{"_key": f"c{i}", "_id": f"chunks/c{i}"} for i in range(50, 100)],
            [{"_key": f"c{i}", "_id": f"chunks/c{i}"} for i in range(100, 125)],
        ]

        result = documents_repo.create_chunks(self._chunks(125), db=db, batch_size=50)

        assert len(result) == 125
        assert col.insert_many.call_count == 3
        assert len(col.insert_many.call_args_list[0].args[0]) == 50
        assert len(col.insert_many.call_args_list[1].args[0]) == 50
        assert len(col.insert_many.call_args_list[2].args[0]) == 25
        assert result[0]["text"] == "t0"
        assert result[0]["_key"] == "c0"

    def test_create_chunks_reports_batch_progress(self):
        db = _db_with_collections("chunks")
        col = MagicMock()
        db.collection.return_value = col
        col.insert_many.side_effect = [
            [{"_key": "c0"}, {"_key": "c1"}],
            [{"_key": "c2"}],
        ]
        seen: list[tuple[int, int, int]] = []

        documents_repo.create_chunks(
            self._chunks(3),
            db=db,
            batch_size=2,
            on_batch_progress=lambda inserted, total, size: seen.append(
                (inserted, total, size),
            ),
        )

        assert seen == [(2, 3, 2), (3, 3, 2)]

    def test_create_chunks_uses_gateway_http_batch_when_available(self):
        db = _db_with_collections("chunks")
        col = MagicMock()
        db.collection.return_value = col
        db._client = MagicMock()
        db.name = "OntoExtract"

        gateway_rows = [
            {"_key": f"c{i}", "_id": f"chunks/c{i}"} for i in range(50)
        ] + [{"_key": f"c{i}", "_id": f"chunks/c{i}"} for i in range(50, 100)]

        with patch(
            "app.db.documents_repo.insert_many_via_http_batch",
            return_value=gateway_rows,
        ) as mock_gateway_batch:
            result = documents_repo.create_chunks(self._chunks(100), db=db, batch_size=50)

        assert len(result) == 100
        mock_gateway_batch.assert_called_once()
        col.insert_many.assert_not_called()

    def test_create_chunks_respects_settings_default_batch_size(self):
        db = _db_with_collections("chunks")
        col = MagicMock()
        db.collection.return_value = col
        col.insert_many.return_value = [{"_key": "c0"}]

        with patch.object(documents_repo.settings, "arango_chunk_insert_batch_size", 10):
            documents_repo.create_chunks(self._chunks(15), db=db)

        assert col.insert_many.call_count == 2
        assert len(col.insert_many.call_args_list[0].args[0]) == 10
        assert len(col.insert_many.call_args_list[1].args[0]) == 5

    def test_create_chunks_raises_when_all_batches_fail(self):
        db = _db_with_collections("chunks")
        col = MagicMock()
        db.collection.return_value = col
        col.insert_many.side_effect = RuntimeError("gateway down")

        try:
            documents_repo.create_chunks(self._chunks(3), db=db, batch_size=2)
        except RuntimeError as exc:
            assert "gateway down" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")

    def test_create_chunks_falls_back_to_single_insert_without_insert_many(self):
        db = _db_with_collections("chunks")

        class _ColWithoutBulk:
            def insert(self, document: dict, **kwargs: object) -> dict:
                return {"new": {"_key": "c0", **document}}

        db.collection.return_value = _ColWithoutBulk()

        result = documents_repo.create_chunks([{"text": "t0"}], db=db)

        assert result == [{"_key": "c0", "text": "t0"}]
