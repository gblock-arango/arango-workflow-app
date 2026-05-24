"""Async document processing pipeline.

Orchestrates: parse → chunk → embed → store.
Implemented as a plain async function for now; Celery/ARQ integration is a
future optimisation (IMPLEMENTATION_PLAN Week 2, task 2.5).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, cast

from app.db import documents_repo
from app.db.client import get_db
from app.db.utils import run_aql
from app.models.documents import DocumentStatus
from app.services import embedding as embedding_svc
from app.services.ingestion import (
    Chunk,
    ParsedDocument,
    Section,
    chunk_document,
    parse_doc,
    parse_docx,
    parse_markdown,
    parse_pdf,
    parse_pptx,
)

log = logging.getLogger(__name__)

_pipeline_cancelled: set[str] = set()


def request_pipeline_cancel(doc_id: str) -> None:
    _pipeline_cancelled.add(doc_id)


def clear_pipeline_cancel(doc_id: str) -> None:
    _pipeline_cancelled.discard(doc_id)


def is_pipeline_cancelled(doc_id: str) -> bool:
    return doc_id in _pipeline_cancelled


def _parsed_to_dict(parsed: ParsedDocument) -> dict[str, Any]:
    return {
        "sections": [
            {
                "heading": s.heading,
                "text": s.text,
                "page_number": s.page_number,
            }
            for s in parsed.sections
        ],
        "title": parsed.title,
        "author": parsed.author,
        "page_count": parsed.page_count,
    }


def _parsed_from_dict(data: dict[str, Any]) -> ParsedDocument:
    sections = [
        Section(
            heading=str(s.get("heading") or ""),
            text=str(s.get("text") or ""),
            page_number=s.get("page_number"),
        )
        for s in data.get("sections") or []
    ]
    return ParsedDocument(
        sections=sections,
        title=str(data.get("title") or ""),
        author=str(data.get("author") or ""),
        page_count=int(data.get("page_count") or 0),
    )


def _merge_pipeline_metadata(doc_id: str, **flags: Any) -> None:
    doc = documents_repo.get_document(doc_id) or {}
    existing = (doc.get("metadata") or {}).get("pipeline") or {}
    pipeline = {**existing, **flags}
    documents_repo.update_document_metadata(doc_id, metadata={"pipeline": pipeline})


def _load_stored_parsed(doc_id: str) -> ParsedDocument:
    doc = documents_repo.get_document(doc_id)
    if not doc:
        raise ValueError(f"Document {doc_id} not found")
    raw = (doc.get("metadata") or {}).get("pipeline", {}).get("parsed_document")
    if not raw:
        raise ValueError(f"Document {doc_id} has not been parsed yet")
    return _parsed_from_dict(raw)

_MIME_PARSERS: dict[str, Callable[[bytes], ParsedDocument]] = {
    "application/pdf": lambda file_bytes: parse_pdf(file_bytes),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        lambda file_bytes: parse_docx(file_bytes)
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        lambda file_bytes: parse_pptx(file_bytes)
    ),
    # Legacy Word binary; requires LibreOffice on the host.
    # parse_doc raises a clear RuntimeError if soffice is missing.
    "application/msword": lambda file_bytes: parse_doc(file_bytes),
}


async def run_parse_stage(doc_id: str, file_bytes: bytes, mime_type: str) -> None:
    """Parse document bytes and persist structured text under ``metadata.pipeline``."""
    clear_pipeline_cancel(doc_id)
    try:
        log.info("[ingest:%s] stage=parsing mime=%s bytes=%d", doc_id, mime_type, len(file_bytes))
        documents_repo.update_document_status(doc_id, DocumentStatus.PARSING)
        parsed = await _parse(file_bytes, mime_type)
        if is_pipeline_cancelled(doc_id):
            raise RuntimeError("Cancelled")
        log.info("[ingest:%s] parsing done, sections=%d", doc_id, len(parsed.sections))
        documents_repo.delete_chunks_for_document(doc_id)
        _merge_pipeline_metadata(
            doc_id,
            parsed=True,
            chunked=False,
            embedded=False,
            parsed_document=_parsed_to_dict(parsed),
        )
        documents_repo.update_document_chunk_count(doc_id, 0)
        documents_repo.update_document_status(doc_id, DocumentStatus.PARSED)
    except Exception as exc:
        log.exception("[ingest:%s] parse stage failed", doc_id)
        documents_repo.update_document_status(doc_id, DocumentStatus.FAILED, error_message=str(exc))
        raise
    finally:
        clear_pipeline_cancel(doc_id)


async def run_chunk_stage(doc_id: str) -> None:
    """Chunk a previously parsed document and store chunks without embeddings."""
    clear_pipeline_cancel(doc_id)
    try:
        parsed = _load_stored_parsed(doc_id)
        log.info("[ingest:%s] stage=chunking", doc_id)
        documents_repo.update_document_status(doc_id, DocumentStatus.CHUNKING)
        chunks = chunk_document(parsed)
        if is_pipeline_cancelled(doc_id):
            raise RuntimeError("Cancelled")
        if not chunks:
            documents_repo.update_document_status(
                doc_id, DocumentStatus.FAILED, error_message="No content extracted"
            )
            return
        log.info("[ingest:%s] chunking done, num_chunks=%d", doc_id, len(chunks))
        documents_repo.delete_chunks_for_document(doc_id)
        chunk_dicts = [
            {
                "doc_id": doc_id,
                "text": c.text,
                "chunk_index": c.chunk_index,
                "source_page": c.source_page,
                "section_heading": c.section_heading,
                "token_count": c.token_count,
            }
            for c in chunks
        ]
        stored = documents_repo.create_chunks(chunk_dicts)
        if not stored:
            raise RuntimeError(f"All {len(chunk_dicts)} chunk inserts failed — check ArangoDB logs")
        documents_repo.update_document_chunk_count(doc_id, len(stored))
        _merge_pipeline_metadata(doc_id, chunked=True, embedded=False)
        documents_repo.update_document_status(doc_id, DocumentStatus.CHUNKED)
    except Exception as exc:
        log.exception("[ingest:%s] chunk stage failed", doc_id)
        documents_repo.update_document_status(doc_id, DocumentStatus.FAILED, error_message=str(exc))
        raise
    finally:
        clear_pipeline_cancel(doc_id)


async def run_embed_stage(doc_id: str) -> None:
    """Embed and persist vectors for existing chunks."""
    clear_pipeline_cancel(doc_id)
    try:
        db = get_db()
        rows = list(
            run_aql(
                db,
                "FOR c IN @@col FILTER c.doc_id == @doc_id SORT c.chunk_index ASC RETURN c",
                bind_vars={"@col": documents_repo.CHUNKS_COLLECTION, "doc_id": doc_id},
            )
        )
        if not rows:
            raise ValueError(f"No chunks found for document {doc_id} — run chunk stage first")
        log.info("[ingest:%s] stage=embedding, num_texts=%d", doc_id, len(rows))
        documents_repo.update_document_status(doc_id, DocumentStatus.EMBEDDING)
        texts = [str(r.get("text") or "") for r in rows]
        embeddings = await embedding_svc.embed_texts(texts)
        if is_pipeline_cancelled(doc_id):
            raise RuntimeError("Cancelled")
        updates = [(str(r["_key"]), emb) for r, emb in zip(rows, embeddings, strict=True)]
        updated = documents_repo.update_chunk_embeddings(updates)
        if updated != len(updates):
            raise RuntimeError(f"Only {updated}/{len(updates)} chunk embeddings were stored")
        _ensure_vector_index()
        _merge_pipeline_metadata(doc_id, embedded=True)
        documents_repo.update_document_status(doc_id, DocumentStatus.READY)
        log.info("[ingest:%s] COMPLETE — document ready", doc_id)
    except Exception as exc:
        log.exception("[ingest:%s] embed stage failed", doc_id)
        documents_repo.update_document_status(doc_id, DocumentStatus.FAILED, error_message=str(exc))
        raise
    finally:
        clear_pipeline_cancel(doc_id)


async def process_document(doc_id: str, file_bytes: bytes, mime_type: str) -> None:
    """Full ingestion pipeline for a single document (parse → chunk → embed)."""
    try:
        await run_parse_stage(doc_id, file_bytes, mime_type)
        doc = documents_repo.get_document(doc_id)
        if not doc or doc.get("status") == DocumentStatus.FAILED:
            return
        await run_chunk_stage(doc_id)
        doc = documents_repo.get_document(doc_id)
        if not doc or doc.get("status") == DocumentStatus.FAILED:
            return
        await run_embed_stage(doc_id)
    except Exception:
        # Stages already set status=failed
        return


_VECTOR_INDEX_NAME = "idx_chunks_embedding_vector"
_EMBEDDING_DIMENSION = 1536


def _ensure_vector_index() -> None:
    """Create the Faiss IVF vector index on chunks.embedding if it doesn't exist.

    Must be called after chunks with embeddings have been inserted,
    since ArangoDB's vector index requires training data.
    """
    db = get_db()
    if not db.has_collection("chunks"):
        return

    col = db.collection("chunks")
    for idx in cast("list[dict[str, Any]]", col.indexes()):
        if idx.get("name") == _VECTOR_INDEX_NAME:
            return  # already exists

    import math

    chunk_count = cast(int, col.count())
    n_lists = max(1, int(math.sqrt(chunk_count) * 15))
    # nLists cannot exceed the number of training points
    n_lists = min(n_lists, chunk_count)
    n_probe = max(1, int(math.sqrt(n_lists)))

    log.info(
        "[ingest] vector index params: chunks=%d, nLists=%d, nProbe=%d",
        chunk_count,
        n_lists,
        n_probe,
    )

    body = {
        "type": "vector",
        "name": _VECTOR_INDEX_NAME,
        "fields": ["embedding"],
        "params": {
            "metric": "cosine",
            "dimension": _EMBEDDING_DIMENSION,
            "nLists": n_lists,
            "defaultNProbe": n_probe,
            "trainingIterations": 25,
        },
    }
    # Vector index creation can take a long time on first training; gateway HTTP
    # may time out while Arango still builds the index — re-check indexes afterward.
    try:
        col.add_index(body)
        log.info("[ingest] created vector index %s on chunks.embedding", _VECTOR_INDEX_NAME)
    except Exception as exc:
        log.warning(
            "[ingest] vector index POST raised %s; re-checking whether the index exists",
            exc.__class__.__name__,
        )
        for idx in cast("list[dict[str, Any]]", col.indexes()):
            if idx.get("name") == _VECTOR_INDEX_NAME:
                log.info(
                    "[ingest] vector index %s present after error -- treating as success",
                    _VECTOR_INDEX_NAME,
                )
                return
        raise RuntimeError(
            f"Vector index creation failed and index is not present on the cluster: {exc}"
        ) from exc


async def _parse(file_bytes: bytes, mime_type: str) -> ParsedDocument:
    """Dispatch to the correct parser based on MIME type."""
    if mime_type == "text/markdown":
        text = file_bytes.decode("utf-8", errors="replace")
        return parse_markdown(text)

    parser = _MIME_PARSERS.get(mime_type)
    if parser is None:
        raise ValueError(f"Unsupported MIME type: {mime_type}")

    return await asyncio.to_thread(parser, file_bytes)


def _build_chunk_dicts(
    doc_id: str,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> list[dict[str, Any]]:
    """Convert Chunk dataclasses + embeddings into dicts for storage."""
    result: list[dict[str, Any]] = []
    for chunk, emb in zip(chunks, embeddings, strict=True):
        result.append(
            {
                "doc_id": doc_id,
                "text": chunk.text,
                "chunk_index": chunk.chunk_index,
                "source_page": chunk.source_page,
                "section_heading": chunk.section_heading,
                "token_count": chunk.token_count,
                "embedding": emb,
            }
        )
    return result
