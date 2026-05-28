"""Materialize UC embedding pipeline artifacts into Arango for extraction only."""

from __future__ import annotations

import logging
from typing import Any

from app.db import documents_repo
from app.models.documents import DocumentStatus
from app.services import embedding_artifacts
from app.services import embedding_status as emb_status_svc
from app.services.schema_bootstrap import ensure_ontology_schema, ensure_staging_schema

log = logging.getLogger(__name__)


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


def materialize_embedding_document_for_extraction(doc_id: str) -> dict[str, Any]:
    """
    Copy embedding_status + UC volume chunks/embeddings into Arango ``documents``/``chunks``.

    Called at extraction start; upload/parse/chunk/embed never touch Arango.
    """
    row = emb_status_svc.get_embedding_status(doc_id)
    if not row:
        raise ValueError(f"Document {doc_id} not found in embedding_status")
    if str(row.get("status") or "") != "ready":
        raise ValueError(f"Document {doc_id} is not ready (status={row.get('status')})")

    ensure_staging_schema()
    ensure_ontology_schema()

    chunk_rows = embedding_artifacts.read_chunks(doc_id)
    if not chunk_rows:
        raise ValueError(f"No UC chunks for document {doc_id}")

    emb_by_index: dict[int, list[float]] = {}
    for item in embedding_artifacts.read_embeddings(doc_id):
        idx = int(item.get("chunk_index") or 0)
        emb = item.get("embedding")
        if isinstance(emb, list):
            emb_by_index[idx] = emb

    volume_meta = {
        "volume_relative_path": row["volume_relative_path"],
        "volume_source": "upload",
    }
    existing = documents_repo.get_document(doc_id)
    if existing:
        documents_repo.update_document_metadata(
            doc_id,
            filename=row["filename"],
            mime_type=row["mime_type"],
            file_hash=row.get("file_hash") or "",
            chunk_count=len(chunk_rows),
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
        documents_repo.update_document_chunk_count(doc_id, len(chunk_rows))

    documents_repo.delete_chunks_for_document(doc_id)
    chunk_dicts: list[dict[str, Any]] = []
    for cr in chunk_rows:
        idx = int(cr.get("chunk_index") or 0)
        entry: dict[str, Any] = {
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

    stored = documents_repo.create_chunks(chunk_dicts)
    if not stored:
        raise RuntimeError(f"Failed to materialize chunks for document {doc_id} in Arango")
    documents_repo.update_document_chunk_count(doc_id, len(stored))
    log.info(
        "materialized doc_id=%s for extraction (%d chunks, %d embeddings)",
        doc_id,
        len(stored),
        len(emb_by_index),
    )
    doc = documents_repo.get_document(doc_id)
    return doc or {"_key": doc_id, "filename": row["filename"]}
