"""Materialize UC embedding pipeline artifacts into Arango for extraction only."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.db import documents_repo
from app.db.chunk_keys import chunk_document_key
from app.models.documents import DocumentStatus
from app.services import embedding_artifacts
from app.services import embedding_status as emb_status_svc
from app.services.schema_bootstrap import ensure_staging_schema

log = logging.getLogger(__name__)

MaterializeProgressFn = Callable[[str, dict[str, Any] | None], None]


def validate_embedding_documents_ready(doc_ids: list[str]) -> None:
    """Ensure each doc_id exists in embedding_status with status ``ready``."""
    missing: list[str] = []
    not_ready: list[tuple[str, str]] = []
    for doc_id in doc_ids:
        row = emb_status_svc.get_embedding_status(doc_id)
        if not row:
            missing.append(doc_id)
            continue
        status = str(row.get("status") or "")
        if status != "ready":
            not_ready.append((doc_id, status))
    if missing:
        raise ValueError(f"Document(s) not found in embedding_status: {', '.join(missing)}")
    if not_ready:
        parts = [f"{did} ({status})" for did, status in not_ready]
        raise ValueError(
            "Document(s) not ready for extraction — complete Parse & Chunk first: "
            + ", ".join(parts)
        )


def _require_ready_embedding_row(doc_id: str) -> dict[str, Any]:
    row = emb_status_svc.get_embedding_status(doc_id)
    if not row:
        raise ValueError(f"Document {doc_id} not found in embedding_status")
    if str(row.get("status") or "") != "ready":
        raise ValueError(f"Document {doc_id} is not ready (status={row.get('status')})")
    return row


def _read_uc_chunk_rows(doc_id: str) -> tuple[list[dict[str, Any]], dict[int, list[float]]]:
    chunk_rows = embedding_artifacts.read_chunks(doc_id)
    if not chunk_rows:
        raise ValueError(f"No UC chunks for document {doc_id}")

    emb_by_index: dict[int, list[float]] = {}
    for item in embedding_artifacts.read_embeddings(doc_id):
        idx = int(item.get("chunk_index") or 0)
        emb = item.get("embedding")
        if isinstance(emb, list):
            emb_by_index[idx] = emb
    return chunk_rows, emb_by_index


def _build_chunk_dicts(
    doc_id: str,
    chunk_rows: list[dict[str, Any]],
    emb_by_index: dict[int, list[float]],
) -> list[dict[str, Any]]:
    chunk_dicts: list[dict[str, Any]] = []
    for cr in chunk_rows:
        idx = int(cr.get("chunk_index") or 0)
        chunk_key = str(cr.get("chunk_key") or chunk_document_key(doc_id, idx))
        entry: dict[str, Any] = {
            "_key": chunk_key,
            "chunk_key": chunk_key,
            "doc_id": doc_id,
            "text": str(cr.get("text") or ""),
            "chunk_index": idx,
            "source_page": cr.get("source_page"),
            "section_heading": cr.get("section_heading"),
            "token_count": cr.get("token_count"),
        }
        if idx in emb_by_index:
            entry["embedding"] = emb_by_index[idx]
        chunk_dicts.append(entry)
    return chunk_dicts


def group_chunks_by_doc_id(chunks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Partition a flat in-memory chunk list by ``doc_id``."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        doc_id = str(chunk.get("doc_id") or "")
        if not doc_id:
            continue
        grouped.setdefault(doc_id, []).append(chunk)
    return grouped


def load_chunks_for_extraction(
    doc_id: str,
    *,
    on_progress: MaterializeProgressFn | None = None,
) -> list[dict[str, Any]]:
    """Load chunk text + embeddings from UC volume for in-memory agent use.

    Does not touch Arango. Used on the hot path before the LangGraph pipeline.
    """

    def report(message: str, progress: dict[str, Any] | None = None) -> None:
        if on_progress:
            on_progress(message, progress)

    _require_ready_embedding_row(doc_id)
    report(
        "Reading chunks from UC volume…",
        {"phase": "read_uc", "status": "reading"},
    )
    chunk_rows, emb_by_index = _read_uc_chunk_rows(doc_id)
    report(
        f"Loaded {len(chunk_rows)} chunks from UC volume ({len(emb_by_index)} embeddings)",
        {
            "phase": "read_uc",
            "chunk_count": len(chunk_rows),
            "embedding_count": len(emb_by_index),
        },
    )
    return _build_chunk_dicts(doc_id, chunk_rows, emb_by_index)


def _persist_document_chunks_to_arango(
    doc_id: str,
    row: dict[str, Any],
    chunk_dicts: list[dict[str, Any]],
    *,
    on_progress: MaterializeProgressFn | None = None,
) -> dict[str, Any]:
    """Write pre-built chunk dicts and document metadata into Arango."""

    def report(message: str, progress: dict[str, Any] | None = None) -> None:
        if on_progress:
            on_progress(message, progress)

    if not chunk_dicts:
        raise ValueError(f"No chunks to materialize for document {doc_id}")

    embedding_count = sum(1 for c in chunk_dicts if isinstance(c.get("embedding"), list))

    report(
        "Ensuring documents/chunks collections exist in Arango…",
        {"phase": "staging_schema"},
    )
    staging = ensure_staging_schema()
    if staging.get("collections_created"):
        report(
            f"Created staging collections: {', '.join(staging['collections_created'])}",
            {"phase": "staging_schema", "collections_created": staging["collections_created"]},
        )

    volume_meta = {
        "volume_relative_path": row["volume_relative_path"],
        "volume_source": "upload",
    }
    report(
        f"Upserting document record ({embedding_count} embeddings)…",
        {
            "phase": "document_upsert",
            "chunk_count": len(chunk_dicts),
            "embedding_count": embedding_count,
        },
    )
    existing = documents_repo.get_document(doc_id)
    if existing:
        documents_repo.update_document_metadata(
            doc_id,
            filename=row["filename"],
            mime_type=row["mime_type"],
            file_hash=row.get("file_hash") or "",
            chunk_count=len(chunk_dicts),
            metadata=volume_meta,
        )
        documents_repo.update_document_status(doc_id, DocumentStatus.READY)
    else:
        documents_repo.create_document(
            doc_id=doc_id,
            filename=row["filename"],
            mime_type=row["mime_type"],
            file_hash=row.get("file_hash") or "",
            status=DocumentStatus.READY,
            metadata=volume_meta,
        )
        documents_repo.update_document_chunk_count(doc_id, len(chunk_dicts))

    documents_repo.delete_chunks_for_document(doc_id)

    def _on_batch_progress(inserted: int, total: int, batch_size: int) -> None:
        report(
            f"Arango bulk insert {inserted}/{total} chunks (batch size {batch_size})",
            {
                "phase": "arango_insert",
                "inserted": inserted,
                "total": total,
                "batch_size": batch_size,
            },
        )

    report(
        f"Inserting {len(chunk_dicts)} chunks into Arango",
        {"phase": "arango_insert", "inserted": 0, "total": len(chunk_dicts)},
    )
    stored = documents_repo.create_chunks(
        chunk_dicts,
        on_batch_progress=_on_batch_progress,
    )
    if not stored:
        raise RuntimeError(f"Failed to materialize chunks for document {doc_id} in Arango")
    documents_repo.update_document_chunk_count(doc_id, len(stored))
    log.info(
        "materialized doc_id=%s for extraction (%d chunks, %d embeddings)",
        doc_id,
        len(stored),
        embedding_count,
    )
    doc = documents_repo.get_document(doc_id)
    return doc or {"_key": doc_id, "filename": row["filename"]}


def materialize_embedding_document_for_extraction(
    doc_id: str,
    *,
    chunk_dicts: list[dict[str, Any]] | None = None,
    on_progress: MaterializeProgressFn | None = None,
) -> dict[str, Any]:
    """
    Copy embedding_status + chunks/embeddings into Arango ``documents``/``chunks``.

    When ``chunk_dicts`` is supplied (from the in-memory prepare path), UC volume
    is not read again.
    """

    def report(message: str, progress: dict[str, Any] | None = None) -> None:
        if on_progress:
            on_progress(message, progress)

    row = _require_ready_embedding_row(doc_id)

    if chunk_dicts is None:
        report(
            "Reading chunks from UC volume…",
            {"phase": "read_uc", "status": "reading"},
        )
        chunk_rows, emb_by_index = _read_uc_chunk_rows(doc_id)
        report(
            f"Loaded {len(chunk_rows)} chunks from UC volume",
            {"phase": "read_uc", "chunk_count": len(chunk_rows)},
        )
        chunk_dicts = _build_chunk_dicts(doc_id, chunk_rows, emb_by_index)
    else:
        report(
            f"Using {len(chunk_dicts)} in-memory chunks for lineage materialize",
            {"phase": "memory_chunks", "chunk_count": len(chunk_dicts)},
        )

    return _persist_document_chunks_to_arango(
        doc_id,
        row,
        chunk_dicts,
        on_progress=on_progress,
    )


def materialize_embedding_documents_for_lineage(
    doc_ids: list[str],
    *,
    preloaded_chunks: list[dict[str, Any]] | None = None,
    on_progress: MaterializeProgressFn | None = None,
) -> None:
    """Persist chunks into Arango for ``has_chunk`` lineage after agent extraction."""
    chunks_by_doc = group_chunks_by_doc_id(preloaded_chunks) if preloaded_chunks else {}

    for doc_id in doc_ids:
        materialize_embedding_document_for_extraction(
            doc_id,
            chunk_dicts=chunks_by_doc.get(doc_id),
            on_progress=on_progress,
        )
