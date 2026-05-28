"""Unit tests for UC → Arango materialization at extraction time."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.extraction_materialize import (
    materialize_embedding_document_for_extraction,
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
            ),
            patch(
                "app.services.extraction_materialize.ensure_ontology_schema",
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
