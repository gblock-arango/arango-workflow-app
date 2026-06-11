"""Unit tests for prepare_arango and finalize_graph pipeline nodes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.extraction.agents.finalize_graph import finalize_graph_node
from app.extraction.agents.prepare_arango import prepare_arango_node


class TestPrepareArangoNode:
    @patch("app.extraction.agents.prepare_arango.run_prepare_arango_workflow")
    def test_delegates_to_workflow(self, mock_workflow):
        mock_workflow.return_value = {
            "status": "completed",
            "chunks": [{"text": "hello", "doc_id": "d1"}],
            "chunk_count": 1,
            "migrations_applied": [],
            "migration_count": 0,
            "missing_collections": [],
            "errors": [],
        }

        result = prepare_arango_node(
            {
                "run_id": "run_test",
                "document_id": "d1",
                "metadata": {"doc_ids": ["d1"]},
            }
        )
        assert result["prepare_arango_result"]["status"] == "completed"
        assert len(result["document_chunks"]) == 1
        mock_workflow.assert_called_once()

    @patch("app.extraction.agents.prepare_arango.run_prepare_arango_workflow")
    def test_surfaces_workflow_failure(self, mock_workflow):
        mock_workflow.return_value = {
            "status": "failed",
            "chunks": [],
            "chunk_count": 0,
            "errors": ["No document chunks available for extraction"],
        }

        result = prepare_arango_node({"run_id": "run_test", "metadata": {"doc_ids": ["d1"]}})
        assert result["prepare_arango_result"]["status"] == "failed"
        assert result["errors"]


class TestFinalizeGraphNode:
    def test_skips_without_consistency_result(self):
        result = finalize_graph_node({"run_id": "run_test"})
        assert result["finalize_graph_result"]["status"] == "skipped"

    @patch("app.extraction.agents.finalize_graph.finalize_extraction_run")
    def test_persists_when_consistency_present(self, mock_finalize):
        mock_finalize.return_value = {
            "status": "completed",
            "ontology_id": "onto_1",
            "graph_name": "ontology_my_onto",
            "classes_written": 3,
        }
        consistency = MagicMock()
        consistency.classes = [MagicMock(), MagicMock(), MagicMock()]

        result = finalize_graph_node(
            {
                "run_id": "run_test",
                "consistency_result": consistency,
                "metadata": {"doc_ids": ["d1"]},
            }
        )
        assert result["finalize_graph_result"]["ontology_id"] == "onto_1"
        assert result["metadata"]["ontology_id"] == "onto_1"
        mock_finalize.assert_called_once()
