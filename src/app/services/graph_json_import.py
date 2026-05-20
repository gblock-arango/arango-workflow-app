"""Import property-graph JSON fixtures into ArangoDB.

Supports the fraud/cyber dataset layout under ``datasets/``:

- ``combined_graph.json`` — object with vertex arrays + ``edges``
- ``edges.json`` — edge array only (vertices must already exist)
- ``accounts.json`` (etc.) — single vertex collection array

Writes use batched AQL ``INSERT`` via :func:`app.db.utils.run_aql` (see
:func:`_bulk_insert_documents`). Ontology JSON-LD (``.json`` / ``.jsonld`` with
``@context``) is handled by :mod:`app.services.arangordf_bridge` instead.
"""

from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.ontology_repo import create_class, create_edge
from app.db.registry_repo import create_registry_entry, update_registry_entry
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)

_METADATA_KEYS = frozenset({"metadata", "meta"})
_DEFAULT_VERTEX_COLLECTIONS = frozenset(
    {
        "accounts",
        "transactions",
        "devices",
        "ips",
        "attack_patterns",
        "fraud_signals",
    }
)
_DEFAULT_EDGE_COLLECTION = "edges"
_INSERT_BATCH_SIZE = 500


def is_rdf_json_ld_payload(data: Any) -> bool:
    """True when JSON should be parsed as RDF/JSON-LD (ontology import)."""
    if isinstance(data, dict):
        if "@context" in data or "@graph" in data:
            return True
        if any(k.startswith("@") for k in data):
            return True
    return False


def is_graph_dataset_payload(data: Any) -> bool:
    """True when JSON describes an Arango-style property graph."""
    if isinstance(data, list):
        if not data:
            return False
        sample = data[0]
        if isinstance(sample, dict) and "_from" in sample and "_to" in sample:
            return True
        if isinstance(sample, dict) and "_key" in sample:
            return True
        return False

    if not isinstance(data, dict):
        return False

    if is_rdf_json_ld_payload(data):
        return False

    if "edges" in data and isinstance(data["edges"], list):
        return True

    vertex_keys = _vertex_keys_in_payload(data)
    return bool(vertex_keys)


def _vertex_keys_in_payload(data: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for key, value in data.items():
        if key in _METADATA_KEYS:
            continue
        if key == _DEFAULT_EDGE_COLLECTION:
            continue
        if isinstance(value, list) and value and isinstance(value[0], dict):
            keys.append(key)
    return keys


def _collection_name_from_filename(filename: str) -> str:
    stem = PurePosixPath(filename).stem
    return stem.replace("-", "_").lower()


def _ensure_vertex_collection(db: StandardDatabase, name: str) -> None:
    if not db.has_collection(name):
        db.create_collection(name)
        return
    props = db.collection(name).properties()
    if props.get("type") in (3, "edge", "EDGES"):
        raise ValueError(f"Collection {name!r} exists but is an edge collection")


def _ensure_edge_collection(db: StandardDatabase, name: str) -> None:
    if not db.has_collection(name):
        db.create_collection(name, edge=True)
        return
    props = db.collection(name).properties()
    if props.get("type") not in (3, "edge", "EDGES"):
        raise ValueError(f"Collection {name!r} exists but is not an edge collection")


def _tag_documents(
    docs: list[dict[str, Any]],
    *,
    dataset_id: str,
    source_filename: str,
) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        row = dict(doc)
        row.setdefault("dataset_id", dataset_id)
        row.setdefault("source_filename", source_filename)
        tagged.append(row)
    return tagged


def _bulk_insert_documents(
    db: StandardDatabase,
    collection: str,
    documents: list[dict[str, Any]],
) -> int:
    """Insert documents with batched AQL INSERT (Arango's document write API).

    Example shape executed per batch::

        FOR doc IN @docs
          INSERT doc INTO @@col
          OPTIONS { overwriteMode: "replace" }

    Returns the number of documents written.
    """
    if not documents:
        return 0

    if collection == _DEFAULT_EDGE_COLLECTION:
        _ensure_edge_collection(db, collection)
        is_edge = True
    else:
        _ensure_vertex_collection(db, collection)
        is_edge = False

    written = 0

    for offset in range(0, len(documents), _INSERT_BATCH_SIZE):
        batch = documents[offset : offset + _INSERT_BATCH_SIZE]
        if is_edge:
            run_aql(
                db,
                """
                FOR doc IN @docs
                  INSERT MERGE({ _from: doc._from, _to: doc._to }, doc) INTO @@col
                  OPTIONS { overwriteMode: "replace" }
                """,
                bind_vars={"docs": batch, "@col": collection},
            )
        else:
            run_aql(
                db,
                """
                FOR doc IN @docs
                  INSERT doc INTO @@col
                  OPTIONS { overwriteMode: "replace" }
                """,
                bind_vars={"docs": batch, "@col": collection},
            )
        written += len(batch)

    return written


def _normalize_edge_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return dict(doc)


def _count_live_workspace_classes(db: StandardDatabase, ontology_id: str) -> int:
    if not db.has_collection("ontology_classes"):
        return 0
    rows = list(
        run_aql(
            db,
            "FOR c IN ontology_classes FILTER c.ontology_id == @oid "
            "AND (c.expired == @never OR c.expired == null) "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )
    return int(rows[0]) if rows else 0


def _collection_from_arango_ref(ref: str) -> str:
    if not isinstance(ref, str) or "/" not in ref:
        return ""
    return ref.split("/", 1)[0]


def _humanize_collection(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").strip().title()


def materialize_graph_schema_for_workspace(
    db: StandardDatabase,
    *,
    ontology_id: str,
    payload: dict[str, Any] | list[Any],
    vertex_collections: list[str],
) -> int:
    """Create ontology_classes + related_to edges so the dashboard can render graph imports."""
    if _count_live_workspace_classes(db, ontology_id) > 0:
        return _count_live_workspace_classes(db, ontology_id)

    class_by_collection: dict[str, str] = {}
    for vcol in vertex_collections:
        sample: dict[str, Any] = {}
        if isinstance(payload, dict):
            raw = payload.get(vcol, [])
            if isinstance(raw, list) and raw and isinstance(raw[0], dict):
                sample = raw[0]
        label = _humanize_collection(vcol)
        if isinstance(sample.get("@type"), str):
            label = sample["@type"].split(":")[-1] or label
        doc = create_class(
            db,
            ontology_id=ontology_id,
            data={
                "uri": f"graph://{ontology_id}/{vcol}",
                "label": label,
                "description": f"Imported vertex collection `{vcol}`",
                "status": "approved",
                "tier": "local",
                "graph_collection": vcol,
                "rdf_type": "graph:VertexCollection",
            },
            created_by="import",
        )
        class_by_collection[vcol] = doc["_id"]

    edge_rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        raw_edges = payload.get("edges", [])
        if isinstance(raw_edges, list):
            edge_rows = [e for e in raw_edges if isinstance(e, dict)]
    elif isinstance(payload, list) and payload and isinstance(payload[0], dict):
        if "_from" in payload[0] and "_to" in payload[0]:
            edge_rows = [e for e in payload if isinstance(e, dict)]

    seen_rels: set[tuple[str, str, str]] = set()
    for edge in edge_rows:
        from_col = _collection_from_arango_ref(str(edge.get("_from", "")))
        to_col = _collection_from_arango_ref(str(edge.get("_to", "")))
        if not from_col or not to_col:
            continue
        predicate = str(edge.get("predicate") or edge.get("label") or "related")
        rel_key = (from_col, to_col, predicate)
        if rel_key in seen_rels:
            continue
        seen_rels.add(rel_key)
        from_id = class_by_collection.get(from_col)
        to_id = class_by_collection.get(to_col)
        if from_id and to_id:
            create_edge(
                db,
                edge_collection="related_to",
                from_id=from_id,
                to_id=to_id,
                data={
                    "ontology_id": ontology_id,
                    "label": predicate,
                    "predicate": predicate,
                    "source": "graph_json_import",
                },
            )

    return len(class_by_collection)


def import_graph_from_json(
    file_content: bytes,
    filename: str,
    dataset_id: str,
    *,
    db: StandardDatabase | None = None,
    dataset_label: str | None = None,
) -> dict[str, Any]:
    """Load a property-graph JSON file into native Arango collections."""
    if db is None:
        db = get_db()

    try:
        payload = json.loads(file_content.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {filename!r}: {exc}") from exc

    if is_rdf_json_ld_payload(payload):
        raise ValueError(
            f"{filename!r} looks like JSON-LD ontology data. "
            "Use the ontology import path (ArangoRDF) instead of graph JSON import."
        )

    if not is_graph_dataset_payload(payload):
        raise ValueError(
            f"{filename!r} is not a recognized graph dataset JSON layout. "
            "Expected combined_graph.json shape or an array of vertices/edges."
        )

    vertex_counts: dict[str, int] = {}
    edge_count = 0
    edge_collection = _DEFAULT_EDGE_COLLECTION

    if isinstance(payload, list):
        sample = payload[0] if payload else {}
        if isinstance(sample, dict) and "_from" in sample and "_to" in sample:
            edges = [_normalize_edge_doc(d) for d in payload if isinstance(d, dict)]
            edges = _tag_documents(edges, dataset_id=dataset_id, source_filename=filename)
            edge_count = _bulk_insert_documents(db, edge_collection, edges)
        else:
            collection = _collection_name_from_filename(filename)
            vertices = _tag_documents(
                [d for d in payload if isinstance(d, dict)],
                dataset_id=dataset_id,
                source_filename=filename,
            )
            vertex_counts[collection] = _bulk_insert_documents(db, collection, vertices)
    else:
        assert isinstance(payload, dict)
        vertex_keys = _vertex_keys_in_payload(payload)
        if not vertex_keys and "edges" not in payload:
            raise ValueError("Graph JSON object contains no vertex collections or edges")

        for vcol in vertex_keys:
            raw_vertices = payload.get(vcol, [])
            if not isinstance(raw_vertices, list):
                continue
            vertices = _tag_documents(
                [d for d in raw_vertices if isinstance(d, dict)],
                dataset_id=dataset_id,
                source_filename=filename,
            )
            vertex_counts[vcol] = _bulk_insert_documents(db, vcol, vertices)

        raw_edges = payload.get("edges", [])
        if isinstance(raw_edges, list) and raw_edges:
            edges = _tag_documents(
                [_normalize_edge_doc(d) for d in raw_edges if isinstance(d, dict)],
                dataset_id=dataset_id,
                source_filename=filename,
            )
            edge_count = _bulk_insert_documents(db, edge_collection, edges)

    vertex_total = sum(vertex_counts.values())
    display_name = (dataset_label or "").strip() or _human_title_from_filename(filename) or dataset_id

    workspace_class_count = materialize_graph_schema_for_workspace(
        db,
        ontology_id=dataset_id,
        payload=payload,
        vertex_collections=sorted(vertex_counts.keys()),
    )

    registry_entry = create_registry_entry(
        {
            "_key": dataset_id,
            "name": display_name,
            "label": display_name,
            "description": f"Graph dataset imported from {filename}",
            "tier": "local",
            "source": "graph_json_import",
            "source_filename": filename,
            "format": "graph-json",
            "graph_vertex_collections": sorted(vertex_counts.keys()),
            "graph_edge_collection": edge_collection,
            "vertex_count": vertex_total,
            "edge_count": edge_count,
            "class_count": workspace_class_count,
            "property_count": 0,
        },
        db=db,
    )

    stats = {
        "dataset_id": dataset_id,
        "registry_key": registry_entry["_key"],
        "name": display_name,
        "filename": filename,
        "format": "graph-json",
        "vertex_collections": vertex_counts,
        "edge_collection": edge_collection,
        "vertex_count": vertex_total,
        "edge_count": edge_count,
        "class_count": workspace_class_count,
        "imported": True,
        "source": "graph_json_import",
    }
    try:
        update_registry_entry(
            dataset_id,
            {
                "class_count": workspace_class_count,
                "vertex_count": vertex_total,
                "edge_count": edge_count,
            },
            db=db,
        )
    except Exception:
        log.warning("Could not update registry counts after graph import", exc_info=True)
    log.info("graph JSON import completed", extra=stats)
    return stats


def _human_title_from_filename(filename: str) -> str:
    stem = PurePosixPath(filename).stem
    if not stem:
        return ""
    return stem.replace("-", " ").replace("_", " ").strip().title()
