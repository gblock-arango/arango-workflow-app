"""Unit tests for JSON-LD @graph ontology materialization."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.jsonld_ontology_import import materialize_ontology_from_jsonld_document

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "datasets"
    / "fraud_cyber_ontology_arango_annotated.jsonld"
)


class TestMaterializeFromJsonldGraph:
    def test_materializes_six_classes_from_fraud_fixture(self):
        db = MagicMock()
        db.has_collection.return_value = True
        created_classes: list[dict] = []

        def fake_create_class(_db, *, ontology_id, data, created_by="import"):
            key = f"cls_{len(created_classes)}"
            doc = {"_key": key, "_id": f"ontology_classes/{key}", **data}
            created_classes.append(doc)
            return doc

        with patch(
            "app.services.jsonld_ontology_import.create_class",
            side_effect=fake_create_class,
        ), patch(
            "app.services.jsonld_ontology_import.create_property",
            return_value={"_id": "ontology_object_properties/p1", "_key": "p1"},
        ), patch(
            "app.services.jsonld_ontology_import.create_edge",
        ), patch(
            "app.services.jsonld_ontology_import.run_aql",
            return_value=iter([0]),
        ):
            payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
            stats = materialize_ontology_from_jsonld_document(
                db, payload, "fraud_ont_test"
            )

        assert stats["class_count"] == 6
        assert stats["object_property_count"] == 7
        assert len(created_classes) == 6
        labels = {c["label"] for c in created_classes}
        assert "Account" in labels
        assert "FraudSignal" in labels
