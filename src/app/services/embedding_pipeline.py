"""Parse → chunk → embed pipeline using UC volume artifacts + embedding_status table."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from app.services import embedding as embedding_svc
from app.services import embedding_artifacts as artifacts
from app.services import embedding_status as status_svc
from app.services.ingestion import (
    ParsedDocument,
    chunk_document,
    parse_doc,
    parse_docx,
    parse_markdown,
    parse_pdf,
    parse_pptx,
)
from app.services.workflow_data import read_staged_document_bytes

log = logging.getLogger(__name__)

_pipeline_cancelled: set[str] = set()


def request_pipeline_cancel(doc_id: str) -> None:
    _pipeline_cancelled.add(doc_id)


def clear_pipeline_cancel(doc_id: str) -> None:
    _pipeline_cancelled.discard(doc_id)


def is_pipeline_cancelled(doc_id: str) -> bool:
    return doc_id in _pipeline_cancelled


_MIME_PARSERS: dict[str, Callable[[bytes], ParsedDocument]] = {
    "application/pdf": lambda file_bytes: parse_pdf(file_bytes),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        lambda file_bytes: parse_docx(file_bytes)
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        lambda file_bytes: parse_pptx(file_bytes)
    ),
    "application/msword": lambda file_bytes: parse_doc(file_bytes),
}


async def run_parse_stage(doc_id: str, file_bytes: bytes, mime_type: str) -> None:
    clear_pipeline_cancel(doc_id)
    try:
        log.info("[embedding:%s] stage=parsing mime=%s bytes=%d", doc_id, mime_type, len(file_bytes))
        status_svc.update_embedding_status(
            doc_id, status="parsing", clear_error=True, parsed=False, chunked=False, embedded=False
        )
        parsed = await _parse(file_bytes, mime_type)
        if is_pipeline_cancelled(doc_id):
            raise RuntimeError("Cancelled")
        artifacts.delete_pipeline_artifacts(doc_id)
        artifacts.write_parsed(doc_id, parsed)
        status_svc.update_embedding_status(
            doc_id,
            status="parsed",
            parsed=True,
            chunked=False,
            embedded=False,
            chunk_count=0,
            clear_error=True,
        )
        log.info("[embedding:%s] parsing done, sections=%d", doc_id, len(parsed.sections))
    except Exception as exc:
        log.exception("[embedding:%s] parse stage failed", doc_id)
        status_svc.update_embedding_status(
            doc_id, status="failed", error_message=str(exc)
        )
        raise
    finally:
        clear_pipeline_cancel(doc_id)


async def run_chunk_stage(doc_id: str) -> None:
    clear_pipeline_cancel(doc_id)
    try:
        parsed = artifacts.read_parsed(doc_id)
        log.info("[embedding:%s] stage=chunking", doc_id)
        status_svc.update_embedding_status(doc_id, status="chunking", clear_error=True)
        chunks = chunk_document(parsed)
        if is_pipeline_cancelled(doc_id):
            raise RuntimeError("Cancelled")
        if not chunks:
            status_svc.update_embedding_status(
                doc_id, status="failed", error_message="No content extracted"
            )
            return
        artifacts.write_chunks(doc_id, chunks)
        status_svc.update_embedding_status(
            doc_id,
            status="chunked",
            parsed=True,
            chunked=True,
            embedded=False,
            chunk_count=len(chunks),
            clear_error=True,
        )
        log.info("[embedding:%s] chunking done, num_chunks=%d", doc_id, len(chunks))
    except Exception as exc:
        log.exception("[embedding:%s] chunk stage failed", doc_id)
        status_svc.update_embedding_status(
            doc_id, status="failed", error_message=str(exc)
        )
        raise
    finally:
        clear_pipeline_cancel(doc_id)


async def run_embed_stage(doc_id: str) -> None:
    clear_pipeline_cancel(doc_id)
    try:
        chunk_rows = artifacts.read_chunks(doc_id)
        if not chunk_rows:
            raise ValueError(f"No chunks found for document {doc_id} — run chunk stage first")
        log.info("[embedding:%s] stage=embedding, num_texts=%d", doc_id, len(chunk_rows))
        status_svc.update_embedding_status(doc_id, status="embedding", clear_error=True)
        texts = [str(r.get("text") or "") for r in chunk_rows]
        embeddings = await embedding_svc.embed_texts(texts)
        if is_pipeline_cancelled(doc_id):
            raise RuntimeError("Cancelled")
        emb_rows = [
            {
                "chunk_index": int(r.get("chunk_index") or i),
                "embedding": emb,
            }
            for i, (r, emb) in enumerate(zip(chunk_rows, embeddings, strict=True))
        ]
        artifacts.write_embeddings(doc_id, emb_rows)
        status_svc.update_embedding_status(
            doc_id,
            status="ready",
            parsed=True,
            chunked=True,
            embedded=True,
            chunk_count=len(chunk_rows),
            clear_error=True,
        )
        log.info("[embedding:%s] COMPLETE — document ready", doc_id)
    except Exception as exc:
        log.exception("[embedding:%s] embed stage failed", doc_id)
        status_svc.update_embedding_status(
            doc_id, status="failed", error_message=str(exc)
        )
        raise
    finally:
        clear_pipeline_cancel(doc_id)


async def process_embedding_document(doc_id: str, file_bytes: bytes, mime_type: str) -> None:
    """Full UC pipeline: parse → chunk → embed."""
    try:
        await run_parse_stage(doc_id, file_bytes, mime_type)
        row = status_svc.get_embedding_status(doc_id)
        if not row or row.get("status") == "failed":
            return
        await run_chunk_stage(doc_id)
        row = status_svc.get_embedding_status(doc_id)
        if not row or row.get("status") == "failed":
            return
        await run_embed_stage(doc_id)
    except Exception:
        return


async def run_pipeline_stage(doc_id: str, stage: str) -> None:
    row = status_svc.get_embedding_status(doc_id)
    if not row:
        log.warning("[embedding:%s] no embedding_status row for stage=%s", doc_id, stage)
        return
    if stage == "parse":
        content, _filename, mime = read_staged_document_bytes(
            {"metadata": {"volume_relative_path": row["volume_relative_path"]}}
        )
        await run_parse_stage(doc_id, content, mime)
    elif stage == "chunk":
        await run_chunk_stage(doc_id)
    elif stage == "embed":
        await run_embed_stage(doc_id)


async def _parse(file_bytes: bytes, mime_type: str) -> ParsedDocument:
    if mime_type == "text/markdown":
        text = file_bytes.decode("utf-8", errors="replace")
        return parse_markdown(text)
    parser = _MIME_PARSERS.get(mime_type)
    if parser is None:
        raise ValueError(f"Unsupported MIME type: {mime_type}")
    return await asyncio.to_thread(parser, file_bytes)
