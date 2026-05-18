"""Unit tests for app.services.ontology_graphs -- per-ontology named graph management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.ontology_graphs import (
    PER_ONTOLOGY_EDGE_DEFINITIONS,
    _safe_graph_name,
    delete_ontology_graph,
    ensure_ontology_graph,
    list_ontology_graphs,
)

# ---------------------------------------------------------------------------
# _safe_graph_name
# ---------------------------------------------------------------------------


class TestSafeGraphName:
    def test_simple_name(self):
        assert _safe_graph_name("MyOntology") == "ontology_myontology"

    def test_spaces_replaced(self):
        assert _safe_graph_name("My Ontology") == "ontology_my_ontology"

    def test_special_chars_replaced(self):
        assert _safe_graph_name("my-onto!@#") == "ontology_my_onto"

    def test_consecutive_underscores_collapsed(self):
        assert _safe_graph_name("a   b___c") == "ontology_a_b_c"

    def test_leading_trailing_whitespace_stripped(self):
        assert _safe_graph_name("  test  ") == "ontology_test"

    def test_mixed_case_lowered(self):
        assert _safe_graph_name("CamelCase") == "ontology_camelcase"


# ---------------------------------------------------------------------------
# ensure_ontology_graph
# ---------------------------------------------------------------------------


class TestEnsureOntologyGraph:
    @patch("app.services.ontology_graphs.doc_get")
    def test_creates_graph_when_not_exists(self, mock_doc_get):
        db = MagicMock()
        db.has_graph.return_value = False
        db.has_collection.return_value = True
        db.collections.return_value = [
            {"name": col, "system": False}
            for col in [
                "ontology_classes",
                "ontology_object_properties",
                "ontology_datatype_properties",
                "subclass_of",
                "rdfs_domain",
                "rdfs_range_class",
                "extracted_from",
                "documents",
            ]
        ]

        col = MagicMock()
        col.has.return_value = True
        mock_doc_get.return_value = {"name": "My Ontology"}
        db.collection.return_value = col

        result = ensure_ontology_graph("onto1", db=db, ontology_name="My Ontology")

        assert result == "ontology_my_ontology"
        db.create_graph.assert_called_once_with(
            "ontology_my_ontology",
            edge_definitions=PER_ONTOLOGY_EDGE_DEFINITIONS,
        )

    def test_skips_creation_when_exists(self):
        db = MagicMock()
        db.has_graph.return_value = True

        result = ensure_ontology_graph("onto1", db=db, ontology_name="My Ontology")

        assert result == "ontology_my_ontology"
        db.create_graph.assert_not_called()

    @patch("app.services.ontology_graphs.doc_get")
    def test_resolves_name_from_registry(self, mock_doc_get):
        db = MagicMock()
        db.has_graph.return_value = False
        db.has_collection.return_value = True

        col = MagicMock()
        col.has.return_value = True
        mock_doc_get.return_value = {"name": "Registry Name"}
        db.collection.return_value = col

        result = ensure_ontology_graph("onto1", db=db)

        assert result == "ontology_registry_name"

    @patch("app.services.ontology_graphs.doc_get")
    def test_falls_back_to_id_when_registry_missing(self, mock_doc_get):
        db = MagicMock()
        db.has_graph.return_value = False
        db.has_collection.return_value = False

        result = ensure_ontology_graph("onto1", db=db)

        assert result == "ontology_onto1"
        mock_doc_get.assert_not_called()


# ---------------------------------------------------------------------------
# list_ontology_graphs
# ---------------------------------------------------------------------------


class TestListOntologyGraphs:
    def test_filters_ontology_prefixed_graphs(self):
        db = MagicMock()
        db.graphs.return_value = [
            {"name": "ontology_my_onto"},
            {"name": "ontology_other"},
            {"name": "staging_run1"},
            {"name": "system_graph"},
        ]

        result = list_ontology_graphs(db=db)

        assert len(result) == 2
        assert result[0] == {"graph_name": "ontology_my_onto", "ontology_id": "my_onto"}
        assert result[1] == {"graph_name": "ontology_other", "ontology_id": "other"}

    def test_empty_when_no_ontology_graphs(self):
        db = MagicMock()
        db.graphs.return_value = [{"name": "staging_graph"}]

        result = list_ontology_graphs(db=db)
        assert result == []


# ---------------------------------------------------------------------------
# delete_ontology_graph
# ---------------------------------------------------------------------------


class TestDeleteOntologyGraph:
    def test_deletes_existing_graph(self):
        db = MagicMock()
        db.has_graph.return_value = True
        db.has_collection.return_value = False

        result = delete_ontology_graph("onto1", db=db, ontology_name="My Ontology")

        assert result is True
        db.delete_graph.assert_called_once_with("ontology_my_ontology", drop_collections=False)

    def test_returns_false_when_graph_missing(self):
        db = MagicMock()
        db.has_graph.return_value = False
        db.has_collection.return_value = False

        result = delete_ontology_graph("onto1", db=db, ontology_name="My Ontology")

        assert result is False
        db.delete_graph.assert_not_called()
