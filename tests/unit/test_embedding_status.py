"""Unit tests for UC embedding_status table helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.errors import ConflictError, ValidationError
from app.services.embedding_status import (
    assert_stage_allowed,
    find_by_file_hash,
    list_embedding_status,
    pipeline_flags,
    register_staged_document,
)


class TestPipelineFlags:
    def test_staged_defaults(self):
        flags = pipeline_flags({"status": "staged", "parsed": False, "chunked": False})
        assert flags == {"parsed": False, "chunked": False, "embedded": False}

    def test_ready(self):
        flags = pipeline_flags({"status": "ready", "embedded": True})
        assert flags["embedded"] is True


class TestAssertStageAllowed:
    def test_parse_rejects_ready(self):
        with pytest.raises(ValidationError):
            assert_stage_allowed({"status": "ready"}, "parse")

    def test_chunk_requires_parse(self):
        with pytest.raises(ValidationError):
            assert_stage_allowed({"status": "staged", "parsed": False}, "chunk")


class TestRegisterStagedDocument:
    @patch("app.services.embedding_status.execute_sql")
    @patch("app.services.embedding_status.ensure_embedding_status_table")
    @patch("app.services.embedding_status.get_embedding_status")
    def test_merge_called(self, mock_get, _mock_ensure, mock_sql):
        mock_get.return_value = {"doc_id": "abc", "status": "staged"}
        row = register_staged_document(
            doc_id="abc",
            filename="doc.md",
            mime_type="text/markdown",
            volume_relative_path="uploads/abc/doc.md",
            file_size_bytes=10,
            file_hash="hash1",
        )
        assert row["doc_id"] == "abc"
        assert mock_sql.call_count >= 1


class TestFindByHash:
    @patch("app.services.embedding_status.execute_sql")
    @patch("app.services.embedding_status.ensure_embedding_status_table")
    def test_returns_none_when_empty(self, _mock_ensure, mock_sql):
        mock_sql.return_value = {"rows": []}
        assert find_by_file_hash("nope") is None


class TestListEmbeddingStatus:
    @patch("app.services.embedding_status.execute_sql")
    @patch("app.services.embedding_status.ensure_embedding_status_table")
    def test_maps_rows(self, _mock_ensure, mock_sql):
        mock_sql.return_value = {
            "rows": [
                {
                    "doc_id": "x",
                    "filename": "a.md",
                    "mime_type": "text/markdown",
                    "volume_relative_path": "uploads/x/a.md",
                    "file_size_bytes": 5,
                    "file_hash": "h",
                    "status": "staged",
                    "parsed": False,
                    "chunked": False,
                    "embedded": False,
                    "chunk_count": 0,
                    "error_message": None,
                }
            ]
        }
        rows = list_embedding_status(limit=10)
        assert len(rows) == 1
        assert rows[0]["doc_id"] == "x"


class TestDuplicateConflict:
    @patch("app.services.embedding_status.delete_embedding_status")
    @patch("app.services.embedding_status.find_by_file_hash")
    def test_ready_raises(self, mock_find, _mock_del):
        from app.api.documents import _resolve_duplicate_hash_embedding

        mock_find.return_value = {"doc_id": "d1", "status": "ready"}
        with pytest.raises(ConflictError):
            _resolve_duplicate_hash_embedding("hash")
