"""Unit tests for stable chunk document keys."""

from __future__ import annotations

from app.db.chunk_keys import (
    chunk_document_key,
    normalize_chunk_for_insert,
    resolve_chunk_source_id,
)


class TestChunkDocumentKey:
    def test_stable_key_from_doc_and_index(self):
        assert chunk_document_key("doc-abc", 0) == "doc-abc_0"
        assert chunk_document_key("doc-abc", 12) == "doc-abc_12"

    def test_sanitizes_unsafe_characters(self):
        assert chunk_document_key("doc/with spaces", 1) == "doc_with_spaces_1"


class TestResolveChunkSourceId:
    def test_prefers_key_fields(self):
        assert resolve_chunk_source_id({"_key": "k1"}) == "k1"
        assert resolve_chunk_source_id({"chunk_key": "k2"}) == "k2"

    def test_derives_from_doc_id_and_index(self):
        assert resolve_chunk_source_id({"doc_id": "d1", "chunk_index": 3}) == "d1_3"


class TestNormalizeChunkForInsert:
    def test_assigns_key_before_insert(self):
        doc = normalize_chunk_for_insert({"doc_id": "d1", "chunk_index": 2, "text": "hi"})
        assert doc["_key"] == "d1_2"
        assert doc["chunk_key"] == "d1_2"

    def test_preserves_existing_key(self):
        doc = normalize_chunk_for_insert(
            {"doc_id": "d1", "chunk_index": 2, "_key": "custom", "text": "hi"}
        )
        assert doc["_key"] == "custom"
