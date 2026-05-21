"""Materialize workspace ontology collections from JSON-LD ``@graph`` documents.

rdflib's JSON-LD parser often keeps compact ``@graph`` nodes out of the RDF graph
when the root document carries many top-level keys (common for Arango ontology
fixtures). The dashboard reads ``ontology_classes`` / property collections, so we
walk ``@graph`` explicitly and write those documents.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db.types import StandardDatabase

from app.db.ontology_repo import create_class, create_edge, create_property
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)

_CLASS_TYPES = frozenset({"Class", "rdfs:Class"})
_OBJECT_PROPERTY_TYPES = frozenset({"ObjectProperty", "owl:ObjectProperty"})
_DATATYPE_PROPERTY_TYPES = frozenset({"DatatypeProperty", "owl:DatatypeProperty"})


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


def _expand_jsonld_iri(term: str, context: dict[str, Any]) -> str:
    if not term:
        return term
    if term.startswith("http://") or term.startswith("https://"):
        return term
    if ":" not in term:
        return term
    prefix, local = term.split(":", 1)
    base = context.get(prefix)
    if isinstance(base, str):
        return base + local
    return term


def _node_type_name(node: dict[str, Any]) -> str:
    raw = node.get("@type")
    if isinstance(raw, list):
        return str(raw[0]) if raw else ""
    return str(raw or "")


def _node_label(node: dict[str, Any], fallback_iri: str) -> str:
    for key in ("label", "name", "rdfs:label"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    if ":" in fallback_iri:
        return fallback_iri.rsplit(":", 1)[-1].split("/")[-1]
    return fallback_iri.split("/")[-1] or fallback_iri


def _node_description(node: dict[str, Any]) -> str:
    for key in ("description", "schema:description", "rdfs:comment", "comment"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def materialize_ontology_from_jsonld_document(
    db: StandardDatabase,
    payload: dict[str, Any],
    ontology_id: str,
    *,
    ontology_uri_prefix: str | None = None,
) -> dict[str, int]:
    """Import classes and properties from a JSON-LD document's ``@graph`` array."""
    graph = payload.get("@graph")
    if not isinstance(graph, list) or not graph:
        return {"class_count": 0, "object_property_count": 0, "datatype_property_count": 0}

    if _count_live_workspace_classes(db, ontology_id) > 0:
        return {
            "class_count": _count_live_workspace_classes(db, ontology_id),
            "object_property_count": 0,
            "datatype_property_count": 0,
        }

    context = payload.get("@context", {})
    if not isinstance(context, dict):
        context = {}

    class_ids: dict[str, str] = {}
    class_count = 0
    object_property_count = 0
    datatype_property_count = 0
    property_meta: list[dict[str, Any]] = []

    for raw_node in graph:
        if not isinstance(raw_node, dict):
            continue
        node_id = raw_node.get("@id")
        if not isinstance(node_id, str) or not node_id:
            continue
        iri = _expand_jsonld_iri(node_id, context)
        if ontology_uri_prefix and not iri.startswith(ontology_uri_prefix):
            pass  # still import — prefix filter is advisory only

        type_name = _node_type_name(raw_node)
        if type_name in _CLASS_TYPES:
            extra: dict[str, Any] = {}
            if isinstance(raw_node.get("collection"), str):
                extra["graph_collection"] = raw_node["collection"]
            if raw_node.get("documentCount") is not None:
                extra["document_count"] = raw_node["documentCount"]

            doc = create_class(
                db,
                ontology_id=ontology_id,
                data={
                    "uri": iri,
                    "label": _node_label(raw_node, iri),
                    "description": _node_description(raw_node),
                    "status": "approved",
                    "tier": "domain",
                    "rdf_type": "rdfs:Class",
                    **extra,
                },
                created_by="import",
            )
            class_ids[iri] = doc["_id"]
            class_ids[node_id] = doc["_id"]
            class_count += 1
            continue

        if type_name in _OBJECT_PROPERTY_TYPES:
            domain_raw = raw_node.get("domain")
            range_raw = raw_node.get("range")
            prop_data: dict[str, Any] = {
                "uri": iri,
                "label": _node_label(raw_node, iri),
                "description": _node_description(raw_node),
                "property_type": "object",
                "rdf_type": "owl:ObjectProperty",
                "status": "approved",
            }
            if isinstance(domain_raw, str):
                prop_data["domain"] = _expand_jsonld_iri(domain_raw, context)
            if isinstance(range_raw, str):
                prop_data["range"] = _expand_jsonld_iri(range_raw, context)
            if isinstance(raw_node.get("edgeCollection"), str):
                prop_data["edge_collection"] = raw_node["edgeCollection"]

            doc = create_property(
                db,
                ontology_id=ontology_id,
                data=prop_data,
                created_by="import",
                collection="ontology_object_properties",
            )
            property_meta.append(
                {
                    "prop_id": doc["_id"],
                    "domain": prop_data.get("domain"),
                    "range": prop_data.get("range"),
                    "kind": "object",
                }
            )
            object_property_count += 1
            continue

        if type_name in _DATATYPE_PROPERTY_TYPES:
            range_raw = raw_node.get("range")
            prop_data = {
                "uri": iri,
                "label": _node_label(raw_node, iri),
                "description": _node_description(raw_node),
                "property_type": "datatype",
                "rdf_type": "owl:DatatypeProperty",
                "status": "approved",
            }
            domain_raw = raw_node.get("domain")
            if isinstance(domain_raw, str):
                prop_data["domain"] = _expand_jsonld_iri(domain_raw, context)
            if isinstance(range_raw, str):
                prop_data["range_datatype"] = _expand_jsonld_iri(range_raw, context)
                prop_data["range"] = prop_data["range_datatype"]

            create_property(
                db,
                ontology_id=ontology_id,
                data=prop_data,
                created_by="import",
                collection="ontology_datatype_properties",
            )
            property_meta.append(
                {
                    "prop_id": None,
                    "domain": prop_data.get("domain"),
                    "range": None,
                    "kind": "datatype",
                    "uri": iri,
                }
            )
            datatype_property_count += 1

    for meta in property_meta:
        if meta["kind"] != "object":
            continue
        prop_id = meta["prop_id"]
        domain_iri = meta.get("domain")
        range_iri = meta.get("range")
        if not prop_id or not isinstance(domain_iri, str):
            continue
        domain_id = class_ids.get(domain_iri) or class_ids.get(
            _expand_jsonld_iri(domain_iri, context)
        )
        if domain_id:
            create_edge(
                db,
                edge_collection="rdfs_domain",
                from_id=prop_id,
                to_id=domain_id,
                data={"ontology_id": ontology_id},
            )
        if isinstance(range_iri, str):
            range_id = class_ids.get(range_iri) or class_ids.get(
                _expand_jsonld_iri(range_iri, context)
            )
            if range_id:
                create_edge(
                    db,
                    edge_collection="rdfs_range_class",
                    from_id=prop_id,
                    to_id=range_id,
                    data={"ontology_id": ontology_id},
                )

    log.info(
        "JSON-LD @graph materialized into workspace collections",
        extra={
            "ontology_id": ontology_id,
            "class_count": class_count,
            "object_property_count": object_property_count,
            "datatype_property_count": datatype_property_count,
        },
    )
    return {
        "class_count": class_count,
        "object_property_count": object_property_count,
        "datatype_property_count": datatype_property_count,
    }
