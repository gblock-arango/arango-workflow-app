"""Single-pass schema bootstrap for fresh extraction databases.

On a new ``AutoGraph_*`` database the sequential migration runner issues
hundreds of gateway round trips (``has_collection`` + ``create`` + ``indexes``
+ ``add_index`` per migration). This module applies the same end-state DDL in
one batched pass:

* one ``collections()`` listing
* one ``graphs()`` listing
* one ``views()`` listing
* index creation without pre-listing on empty collections
* skips data/repair migrations (018, 019, 020, 023) when there is no ontology data

Used automatically by :func:`migrations.runner.apply_all` when no migrations
have been applied yet.
"""

from __future__ import annotations

import importlib
import logging
import time
from collections.abc import Callable
from typing import Any

from app.db.types import GatewayAPIError, StandardDatabase

log = logging.getLogger(__name__)

MigrationProgressFn = Callable[[str, dict[str, Any] | None], None]

_OLD_CHUNKS_INDEX = "idx_chunks_embedding_hnsw"

# Import collection/graph/view definitions from numbered migrations to avoid drift.
_m001 = importlib.import_module("migrations.001_initial_collections")
_m002 = importlib.import_module("migrations.002_versioned_vertices")
_m003 = importlib.import_module("migrations.003_edge_collections")
_m004 = importlib.import_module("migrations.004_named_graphs")
_m006 = importlib.import_module("migrations.006_ttl_indexes")
_m007 = importlib.import_module("migrations.007_arangosearch_views")
_m009 = importlib.import_module("migrations.009_er_collections")
_m010 = importlib.import_module("migrations.010_process_graph")
_m015 = importlib.import_module("migrations.015_library_search")
_m017 = importlib.import_module("migrations.017_pgt_collections")

DOCUMENT_COLLECTIONS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            *_m001.NON_TEMPORAL_COLLECTIONS,
            *_m002.VERSIONED_VERTEX_COLLECTIONS,
            *_m009.DOCUMENT_COLLECTIONS,
            *_m017.PGT_VERTEX_COLLECTIONS,
            "ontology_releases",
            "quality_history",
            "revision_meta",
        ]
    )
)

EDGE_COLLECTIONS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            *_m003.EDGE_COLLECTIONS,
            *_m009.EDGE_COLLECTIONS,
            *_m017.PGT_EDGE_COLLECTIONS,
            "has_chunk",
            "produced_by",
        ]
    )
)

MDI_TEMPORAL_COLLECTIONS: tuple[str, ...] = (
    "ontology_classes",
    "ontology_properties",
    "ontology_constraints",
    "ontology_object_properties",
    "ontology_datatype_properties",
    "subclass_of",
    "equivalent_class",
    "has_property",
    "extends_domain",
    "extracted_from",
    "related_to",
    "merge_candidate",
    "imports",
    "rdfs_domain",
    "rdfs_range_class",
    "has_chunk",
    "produced_by",
)

DOMAIN_ONTOLOGY_EDGES = [
    *_m004.DOMAIN_ONTOLOGY_EDGE_DEFINITIONS,
    {
        "edge_collection": "extracted_from",
        "from_vertex_collections": ["ontology_classes"],
        "to_vertex_collections": ["documents"],
    },
]


class _BootstrapContext:
    """In-memory catalog caches to avoid per-entity existence probes."""

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self._collection_names = _collection_name_set(db)
        self._graph_names = {g["name"] for g in db.graphs()}
        self._view_names = {v["name"] for v in db.views()}

    def ensure_document_collection(self, name: str) -> bool:
        if name in self._collection_names:
            return False
        self.db.create_collection(name)
        self._collection_names.add(name)
        log.info("batch bootstrap: created collection %s", name)
        return True

    def ensure_edge_collection(self, name: str) -> bool:
        if name in self._collection_names:
            return False
        self.db.create_collection(name, edge=True)
        self._collection_names.add(name)
        log.info("batch bootstrap: created edge collection %s", name)
        return True

    def ensure_graph(self, name: str, edge_definitions: list[dict[str, Any]]) -> bool:
        if name in self._graph_names:
            return False
        self.db.create_graph(name, edge_definitions=edge_definitions)
        self._graph_names.add(name)
        log.info("batch bootstrap: created graph %s", name)
        return True

    def ensure_arangosearch_view(self, name: str, properties: dict[str, Any]) -> bool:
        if name in self._view_names:
            return False
        self.db.create_arangosearch_view(name, properties=properties)
        self._view_names.add(name)
        log.info("batch bootstrap: created view %s", name)
        return True


def _collection_name_set(db: StandardDatabase) -> set[str]:
    names: set[str] = set()
    for item in db.collections():
        if isinstance(item, dict):
            name = item.get("name") or item.get("_key")
        else:
            name = getattr(item, "name", None)
        if name:
            names.add(str(name))
    return names


def can_bootstrap_fresh(applied_names: set[str]) -> bool:
    """True when the database has never had migrations applied."""
    return len(applied_names) == 0


def core_collections_present(db: StandardDatabase) -> bool:
    """True when the batched collection DDL already exists (recovery / idempotent re-run)."""
    names = _collection_name_set(db)
    return set(DOCUMENT_COLLECTIONS).issubset(names) and set(EDGE_COLLECTIONS).issubset(names)


def should_use_batch_bootstrap(
    db: StandardDatabase,
    applied_names: set[str],
    pending: list[str],
) -> bool:
    """Prefer batch when fresh or when collections exist but schema never finished."""
    if not pending:
        return False
    if can_bootstrap_fresh(applied_names):
        return True
    return core_collections_present(db)


def _report(
    on_progress: MigrationProgressFn | None,
    message: str,
    progress: dict[str, Any] | None = None,
) -> None:
    if on_progress:
        on_progress(message, progress)


def _add_mdi_index(db: StandardDatabase, collection_name: str) -> None:
    idx_name = f"idx_{collection_name}_mdi_temporal"
    col = db.collection(collection_name)
    body = {
        "type": "mdi-prefixed",
        "fields": ["created", "expired"],
        "fieldValueTypes": "double",
        "prefixFields": ["ontology_id"],
        "sparse": False,
        "name": idx_name,
    }
    try:
        col.add_index(body)
        log.info("batch bootstrap: mdi index %s on %s", idx_name, collection_name)
        return
    except Exception as exc:
        log.warning(
            "batch bootstrap: mdi index failed on %s (%s) — trying persistent fallback",
            collection_name,
            exc,
        )
    try:
        col.add_persistent_index(
            fields=["ontology_id", "created", "expired"],
            name=idx_name,
        )
    except GatewayAPIError:
        log.debug("batch bootstrap: index %s already exists on %s", idx_name, collection_name)


def _add_ttl_index(db: StandardDatabase, collection_name: str) -> None:
    idx_name = f"idx_{collection_name}_ttl"
    col = db.collection(collection_name)
    try:
        col.add_ttl_index(
            fields=["ttlExpireAt"],
            expiry_time=0,
            name=idx_name,
            in_background=True,
        )
        log.info("batch bootstrap: ttl index %s on %s", idx_name, collection_name)
    except GatewayAPIError:
        log.debug("batch bootstrap: ttl index %s already exists on %s", idx_name, collection_name)


def _add_persistent_index(
    db: StandardDatabase,
    collection_name: str,
    *,
    fields: list[str],
    name: str,
    unique: bool = False,
    sparse: bool = False,
) -> None:
    col = db.collection(collection_name)
    body: dict[str, Any] = {"type": "persistent", "fields": fields, "name": name}
    if unique:
        body["unique"] = True
    if sparse:
        body["sparse"] = True
    try:
        col.add_index(body)
        log.info("batch bootstrap: persistent index %s on %s", name, collection_name)
    except GatewayAPIError:
        log.debug("batch bootstrap: index %s already exists on %s", name, collection_name)


def _cleanup_chunks_index(ctx: _BootstrapContext) -> None:
    if "chunks" not in ctx._collection_names:
        return
    col = ctx.db.collection("chunks")
    for idx in col.indexes():
        if idx.get("name") == _OLD_CHUNKS_INDEX:
            col.delete_index(idx["id"])
            log.info("batch bootstrap: dropped legacy index %s from chunks", _OLD_CHUNKS_INDEX)
            return


def _remove_legacy_all_ontologies_graph(ctx: _BootstrapContext) -> None:
    if "all_ontologies" not in ctx._graph_names:
        return
    ctx.db.delete_graph("all_ontologies", drop_collections=False)
    ctx._graph_names.discard("all_ontologies")
    log.info("batch bootstrap: removed legacy graph all_ontologies")


def bootstrap_fresh_schema(
    db: StandardDatabase,
    *,
    on_progress: MigrationProgressFn | None = None,
) -> None:
    """Apply full ontology DDL for a fresh database in a single batched pass."""
    started = time.perf_counter()
    ctx = _BootstrapContext(db)

    _report(
        on_progress,
        f"Batch schema bootstrap: ensuring {len(DOCUMENT_COLLECTIONS)} document collections…",
        {"phase": "schema_migration", "bootstrap_phase": "collections"},
    )
    created_docs = 0
    for name in DOCUMENT_COLLECTIONS:
        if ctx.ensure_document_collection(name):
            created_docs += 1

    _report(
        on_progress,
        f"Batch schema bootstrap: ensuring {len(EDGE_COLLECTIONS)} edge collections…",
        {
            "phase": "schema_migration",
            "bootstrap_phase": "edge_collections",
            "collections_created": created_docs,
        },
    )
    created_edges = 0
    for name in EDGE_COLLECTIONS:
        if ctx.ensure_edge_collection(name):
            created_edges += 1

    _report(
        on_progress,
        "Batch schema bootstrap: creating named graphs…",
        {"phase": "schema_migration", "bootstrap_phase": "graphs"},
    )
    ctx.ensure_graph("domain_ontology", DOMAIN_ONTOLOGY_EDGES)
    ctx.ensure_graph("aoe_process", _m010.AOE_PROCESS_EDGE_DEFINITIONS)
    _remove_legacy_all_ontologies_graph(ctx)

    _report(
        on_progress,
        "Batch schema bootstrap: creating temporal and lookup indexes…",
        {"phase": "schema_migration", "bootstrap_phase": "indexes"},
    )
    mdi_names = [n for n in MDI_TEMPORAL_COLLECTIONS if n in ctx._collection_names]
    for i, name in enumerate(mdi_names, start=1):
        _add_mdi_index(db, name)
        if i == 1 or i == len(mdi_names) or i % 4 == 0:
            _report(
                on_progress,
                f"Batch schema bootstrap: MDI temporal indexes ({i}/{len(mdi_names)})…",
                {
                    "phase": "schema_migration",
                    "bootstrap_phase": "indexes",
                    "index_step": "mdi",
                    "index_done": i,
                    "index_total": len(mdi_names),
                },
            )
    for name in _m006.VERSIONED_COLLECTIONS:
        if name in ctx._collection_names:
            _add_ttl_index(db, name)
    _add_persistent_index(
        db,
        "ontology_releases",
        fields=["ontology_id", "version"],
        name="idx_ontology_releases_ontology_version",
        unique=True,
    )
    _add_persistent_index(
        db,
        "quality_history",
        fields=["ontology_id", "timestamp"],
        name="idx_quality_history_ontology_timestamp",
    )
    for name, fields, sparse in (
        ("idx_revision_meta_ontology_created", ["ontology_id", "created"], False),
        ("idx_revision_meta_inbox", ["ontology_id", "action", "status"], False),
        ("idx_revision_meta_entity", ["existing_entity_id"], False),
        ("idx_revision_meta_doc", ["triggering_doc_id"], True),
    ):
        _add_persistent_index(db, "revision_meta", fields=fields, name=name, sparse=sparse)

    _cleanup_chunks_index(ctx)

    _report(
        on_progress,
        "Batch schema bootstrap: creating ArangoSearch views…",
        {"phase": "schema_migration", "bootstrap_phase": "views"},
    )
    ctx.ensure_arangosearch_view(_m007.VIEW_NAME, _m007.VIEW_PROPERTIES)
    ctx.ensure_arangosearch_view(_m015.VIEW_NAME, _m015.VIEW_PROPERTIES)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    from app.services.extraction_gateway_checkpoints import format_duration_ms

    elapsed = format_duration_ms(elapsed_ms)
    _report(
        on_progress,
        (
            f"Batch schema bootstrap complete "
            f"({created_docs} doc + {created_edges} edge collections, {elapsed})"
        ),
        {
            "phase": "schema_migration",
            "bootstrap_phase": "complete",
            "bootstrap_elapsed_ms": elapsed_ms,
            "collections_created": created_docs + created_edges,
            "migration_ok": True,
        },
    )
