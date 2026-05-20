"""Unit tests for graph JSON dataset import."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services import graph_json_import

_DATASET_DIR = (
    Path(__file__).resolve().parents[2] / "datasets" / "fraud_cyber_graph_dataset"
)


class TestPayloadDetection:
    def test_combined_graph_is_graph_payload(self):
        payload = json.loads((_DATASET_DIR / "combined_graph.json").read_text(encoding="utf-8"))
        assert graph_json_import.is_graph_dataset_payload(payload)
        assert not graph_json_import.is_rdf_json_ld_payload(payload)

    def test_edges_array_is_graph_payload(self):
        payload = json.loads((_DATASET_DIR / "edges.json").read_text(encoding="utf-8"))
        assert graph_json_import.is_graph_dataset_payload(payload)

    def test_json_ld_ontology_is_not_graph_payload(self):
        path = Path(__file__).resolve().parents[2] / "datasets" / "fraud_cyber_ontology_arango.jsonld"
        if not path.exists():
            pytest.skip("ontology fixture not present")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert graph_json_import.is_rdf_json_ld_payload(payload)
        assert not graph_json_import.is_graph_dataset_payload(payload)


class TestImportGraphFromJson:
    def test_import_combined_graph_batches_aql(self):
        db = MagicMock()
        db.has_collection.return_value = False
        db.create_collection = MagicMock()
        col = MagicMock()
        col.properties.return_value = {"type": 2}
        db.collection.return_value = col

        content = (_DATASET_DIR / "combined_graph.json").read_bytes()
        aql_calls: list[tuple[str, dict]] = []

        def fake_run_aql(_db, query, bind_vars=None, **_kwargs):
            aql_calls.append((query, bind_vars or {}))
            return iter([])

        class_keys = iter(f"cls_{i}" for i in range(12))

        def fake_create_class(_db, *, ontology_id, data, created_by="import"):
            key = next(class_keys)
            return {"_key": key, "_id": f"ontology_classes/{key}", **data}

        with (
            patch("app.services.graph_json_import.run_aql", side_effect=fake_run_aql),
            patch("app.services.graph_json_import.create_class", side_effect=fake_create_class),
            patch("app.services.graph_json_import.create_edge"),
            patch(
                "app.services.graph_json_import.create_registry_entry",
                return_value={"_key": "ds_test"},
            ),
            patch("app.services.graph_json_import.update_registry_entry"),
        ):
            stats = graph_json_import.import_graph_from_json(
                content,
                "combined_graph.json",
                "ds_test",
                db=db,
                dataset_label="Fraud Cyber Graph",
            )

        assert stats["format"] == "graph-json"
        assert stats["vertex_count"] > 0
        assert stats["edge_count"] > 0
        assert stats["class_count"] == 6
        assert any("INSERT doc INTO @@col" in q for q, _ in aql_calls)
        assert any("INSERT MERGE" in q and "_from" in q for q, _ in aql_calls)

    def test_rejects_json_ld(self):
        payload = {"@context": {"ex": "http://example.org/"}, "@graph": []}
        content = json.dumps(payload).encode()
        with pytest.raises(ValueError, match="JSON-LD"):
            graph_json_import.import_graph_from_json(
                content,
                "ontology.json",
                "ont_x",
                db=MagicMock(),
            )


class TestArangordfBridgeGraphBranch:
    def test_import_from_file_routes_graph_json(self):
        from app.services.arangordf_bridge import import_from_file

        content = json.dumps(
            {
                "accounts": [{"_key": "A1", "name": "acct"}],
                "edges": [{"_key": "E1", "_from": "accounts/A1", "_to": "accounts/A1"}],
            }
        ).encode()

        with patch(
            "app.services.arangordf_bridge.graph_json_import.import_graph_from_json",
            return_value={"imported": True, "vertex_count": 1},
        ) as mock_import:
            out = import_from_file(content, "graph.json", "ds_1", db=MagicMock())

        mock_import.assert_called_once()
        assert out["imported"] is True
