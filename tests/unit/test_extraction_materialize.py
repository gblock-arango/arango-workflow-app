"""Unit tests for UC → Arango materialization at extraction time."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.extraction_materialize import (
    group_chunks_by_doc_id,
    load_chunks_for_extraction,
    materialize_embedding_document_for_extraction,
    materialize_embedding_documents_for_lineage,
    validate_embedding_documents_ready,
)


class TestValidateEmbeddingDocumentsReady:
    def test_missing_raises(self):
        with patch(
            "app.services.extraction_materialize.emb_status_svc.get_embedding_status",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="not found"):
                validate_embedding_documents_ready(["d1"])

    def test_not_ready_raises(self):
        with patch(
            "app.services.extraction_materialize.emb_status_svc.get_embedding_status",
            return_value={"doc_id": "d1", "status": "staged"},
        ):
            with pytest.raises(ValueError, match="not ready"):
                validate_embedding_documents_ready(["d1"])


class TestLoadChunksForExtraction:
    def test_load_chunks_without_arango(self):
        row = {
            "doc_id": "d1",
            "filename": "a.pdf",
            "mime_type": "application/pdf",
            "file_hash": "h1",
            "status": "ready",
            "volume_relative_path": "uploads/d1/a.pdf",
        }
        chunks = [{"chunk_index": 0, "text": "hello", "token_count": 1}]
        embs = [{"chunk_index": 0, "embedding": [0.1, 0.2]}]

        with (
            patch(
                "app.services.extraction_materialize.emb_status_svc.get_embedding_status",
                return_value=row,
            ),
            patch(
                "app.services.extraction_materialize.embedding_artifacts.read_chunks",
                return_value=chunks,
            ),
            patch(
                "app.services.extraction_materialize.embedding_artifacts.read_embeddings",
                return_value=embs,
            ),
        ):
            loaded = load_chunks_for_extraction("d1")

        assert len(loaded) == 1
        assert loaded[0]["doc_id"] == "d1"
        assert loaded[0]["embedding"] == [0.1, 0.2]


class TestMaterializeEmbeddingDocument:
    def test_materialize_creates_doc_and_chunks(self):
        row = {
            "doc_id": "d1",
            "filename": "a.pdf",
            "mime_type": "application/pdf",
            "file_hash": "h1",
            "status": "ready",
            "volume_relative_path": "uploads/d1/a.pdf",
        }
        chunks = [{"chunk_index": 0, "text": "hello", "token_count": 1}]
        embs = [{"chunk_index": 0, "embedding": [0.1, 0.2]}]

        with (
            patch(
                "app.services.extraction_materialize.emb_status_svc.get_embedding_status",
                return_value=row,
            ),
            patch(
                "app.services.extraction_materialize.ensure_staging_schema",
                return_value={"ok": True, "collections_created": []},
            ),
            patch(
                "app.services.extraction_materialize.embedding_artifacts.read_chunks",
                return_value=chunks,
            ),
            patch(
                "app.services.extraction_materialize.embedding_artifacts.read_embeddings",
                return_value=embs,
            ),
            patch(
                "app.services.extraction_materialize.documents_repo.get_document",
                side_effect=[None, {"_key": "d1", "filename": "a.pdf"}],
            ),
            patch(
                "app.services.extraction_materialize.documents_repo.create_document",
            ) as mock_create,
            patch(
                "app.services.extraction_materialize.documents_repo.delete_chunks_for_document",
            ),
            patch(
                "app.services.extraction_materialize.documents_repo.create_chunks",
                return_value=[{"_key": "c0"}],
            ) as mock_insert_chunks,
            patch(
                "app.services.extraction_materialize.documents_repo.update_document_chunk_count",
            ),
        ):
            out = materialize_embedding_document_for_extraction("d1")

        mock_create.assert_called_once()
        mock_insert_chunks.assert_called_once()
        inserted = mock_insert_chunks.call_args[0][0]
        assert inserted[0]["embedding"] == [0.1, 0.2]
        assert out["_key"] == "d1"

    def test_materialize_uses_in_memory_chunks_without_uc_read(self):
        row = {
            "doc_id": "d1",
            "filename": "a.pdf",
            "mime_type": "application/pdf",
            "file_hash": "h1",
            "status": "ready",
            "volume_relative_path": "uploads/d1/a.pdf",
        }
        in_memory = [
            {
                "doc_id": "d1",
                "chunk_index": 0,
                "text": "hello",
                "embedding": [0.1, 0.2],
            }
        ]

        with (
            patch(
                "app.services.extraction_materialize.emb_status_svc.get_embedding_status",
                return_value=row,
            ),
            patch(
                "app.services.extraction_materialize.ensure_staging_schema",
                return_value={"ok": True, "collections_created": []},
            ),
            patch(
                "app.services.extraction_materialize.embedding_artifacts.read_chunks",
            ) as mock_read_chunks,
            patch(
                "app.services.extraction_materialize.documents_repo.get_document",
                side_effect=[None, {"_key": "d1", "filename": "a.pdf"}],
            ),
            patch("app.services.extraction_materialize.documents_repo.create_document"),
            patch(
                "app.services.extraction_materialize.documents_repo.delete_chunks_for_document",
            ),
            patch(
                "app.services.extraction_materialize.documents_repo.create_chunks",
                return_value=[{"_key": "c0"}],
            ) as mock_insert_chunks,
            patch(
                "app.services.extraction_materialize.documents_repo.update_document_chunk_count",
            ),
        ):
            materialize_embedding_document_for_extraction("d1", chunk_dicts=in_memory)

        mock_read_chunks.assert_not_called()
        inserted = mock_insert_chunks.call_args[0][0]
        assert inserted == in_memory


class TestMaterializeDocumentsForLineage:
    def test_passes_grouped_preloaded_chunks(self):
        row = {
            "doc_id": "d1",
            "filename": "a.pdf",
            "mime_type": "application/pdf",
            "file_hash": "h1",
            "status": "ready",
            "volume_relative_path": "uploads/d1/a.pdf",
        }
        preloaded = [
            {"doc_id": "d1", "chunk_index": 0, "text": "one", "embedding": [1.0]},
            {"doc_id": "d2", "chunk_index": 0, "text": "two"},
        ]

        with patch(
            "app.services.extraction_materialize.materialize_embedding_document_for_extraction",
        ) as mock_mat:
            materialize_embedding_documents_for_lineage(
                ["d1", "d2"],
                preloaded_chunks=preloaded,
            )

        assert mock_mat.call_count == 2
        d1_call = mock_mat.call_args_list[0]
        d2_call = mock_mat.call_args_list[1]
        assert d1_call.args[0] == "d1"
        assert d1_call.kwargs["chunk_dicts"] == [preloaded[0]]
        assert d2_call.args[0] == "d2"
        assert d2_call.kwargs["chunk_dicts"] == [preloaded[1]]


class TestGroupChunksByDocId:
    def test_groups_flat_list(self):
        chunks = [
            {"doc_id": "a", "text": "1"},
            {"doc_id": "b", "text": "2"},
            {"doc_id": "a", "text": "3"},
        ]
        grouped = group_chunks_by_doc_id(chunks)
        assert len(grouped["a"]) == 2
        assert len(grouped["b"]) == 1
