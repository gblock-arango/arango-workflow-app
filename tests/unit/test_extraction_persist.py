"""Unit tests for finalize_extraction_run (graph persist bookend)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.extraction.extraction_persist import finalize_extraction_run


class TestFinalizeExtractionRun:
    @patch("app.services.extraction._auto_register_ontology", return_value="onto_1")
    @patch("app.services.extraction._materialize_to_graph")
    @patch("app.services.extraction._store_results")
    @patch("app.services.extraction._create_produced_by_edge")
    @patch("app.services.ontology_graphs.ensure_ontology_graph", return_value="ontology_onto_1")
    @patch("app.db.quality_history_repo.record_event_snapshot", side_effect=RuntimeError("boom"))
    def test_quality_snapshot_failure_does_not_fail_finalize(
        self,
        _mock_snapshot,
        _mock_graph,
        _mock_produced_by,
        _mock_store,
        _mock_materialize,
        _mock_register,
    ):
        consistency = MagicMock()
        consistency.classes = [MagicMock()]

        result = finalize_extraction_run(
            {
                "run_id": "run_1",
                "document_id": "doc_1",
                "consistency_result": consistency,
                "metadata": {"doc_ids": ["doc_1"]},
            },
            db=MagicMock(),
        )

        assert result["status"] == "completed"
        assert result["ontology_id"] == "onto_1"
