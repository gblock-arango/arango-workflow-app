"""Unit tests for ontology schema bootstrap before chunking."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.schema_bootstrap import ensure_ontology_schema, ensure_staging_schema


class TestEnsureStagingSchema:
    def test_creates_documents_and_chunks_when_missing(self):
        mock_db = MagicMock()
        mock_db.has_collection.side_effect = lambda name: name == "documents"

        with patch("app.services.schema_bootstrap.get_db", return_value=mock_db):
            result = ensure_staging_schema(db=mock_db)

        assert result["ok"] is True
        assert result["collections_created"] == ["chunks"]
        mock_db.create_collection.assert_called_once_with("chunks")


class TestEnsureOntologySchema:
    def test_returns_applied_migration_names(self):
        mock_db = MagicMock()
        with patch("app.services.schema_bootstrap.init_schema", return_value=["001_initial_collections"]):
            result = ensure_ontology_schema(db=mock_db)

        assert result["ok"] is True
        assert result["migrations_applied"] == ["001_initial_collections"]
        assert result["migration_count"] == 1

    def test_empty_when_already_up_to_date(self):
        with patch("app.services.schema_bootstrap.init_schema", return_value=[]):
            result = ensure_ontology_schema(db=MagicMock())

        assert result["ok"] is True
        assert result["migrations_applied"] == []
        assert result["migration_count"] == 0
