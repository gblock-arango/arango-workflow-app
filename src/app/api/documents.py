"""Document REST endpoints — PRD Section 7.1.

Thin route handlers that validate input, delegate to services/repo, and return
Pydantic-shaped responses.  Routes never import from ``db/`` directly; all data
access goes through the repository and service layers.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Query, UploadFile
from pydantic import BaseModel, Field

from app.api.dependencies import get_or_404
from app.api.errors import ConflictError, ValidationError
from app.db import documents_repo
from app.db.client import get_db
from app.db.utils import run_aql
from app.models.common import PaginatedResponse
from app.models.documents import DocumentStatus
from app.services.ingestion import compute_file_hash
from app.services.upload_filename import resolve_upload_filename
from app.workflow_platform import workflow_data_volume as vol
from app.services.schema_bootstrap import (
    ensure_ontology_schema_async,
    ensure_staging_schema,
    ensure_staging_schema_async,
)
from app.services.workflow_data import (
    browse_volume,
    ingest_file_from_volume,
    persist_upload,
    read_staged_document_bytes,
    workflow_data_status,
)
from app.tasks import (
    process_document,
    request_pipeline_cancel,
    run_chunk_stage,
    run_embed_stage,
    run_parse_stage,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_background_tasks: set[asyncio.Task[None]] = set()  # prevent GC of fire-and-forget tasks

_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",  # legacy .doc (pre-2007); requires LibreOffice on host
    "text/markdown",
}

# Browsers occasionally upload Office files with a generic or vendor-
# specific MIME type. Map well-known cases by filename suffix when the
# declared MIME doesn't match. Keep this list short -- it's a fallback,
# not a primary path.
_EXTENSION_FALLBACK: dict[str, str] = {
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
}


def _validate_mime(*, filename: str, content_type: str | None) -> str:
    """Return the validated MIME type, raising ValidationError if unsupported.

    Falls back to filename-extension sniffing for known Office formats so
    a misconfigured browser ("application/octet-stream") doesn't block a
    legitimate upload.
    """
    mime = content_type or ""
    if mime in _ALLOWED_MIME_TYPES:
        return mime

    lower = (filename or "").lower()
    for suffix, fallback in _EXTENSION_FALLBACK.items():
        if lower.endswith(suffix):
            return fallback

    raise ValidationError(
        f"Unsupported file type: {mime}",
        details={"allowed": sorted(_ALLOWED_MIME_TYPES), "filename": filename},
    )


class IngestFromVolumeBody(BaseModel):
    """Ingest a file already stored under UC workflow-data (e.g. builtin corpora)."""

    path: str = Field(
        ...,
        description="Path relative to workflow-data root, e.g. builtin/financial/foo.md",
    )


class PipelineBatchBody(BaseModel):
    doc_ids: list[str] = Field(..., min_length=1, max_length=100)
    stage: Literal["parse", "chunk", "embed"]


class PipelineCancelBody(BaseModel):
    doc_ids: list[str] = Field(default_factory=list)


def _resolve_duplicate_hash(file_hash: str) -> None:
    """Allow re-upload when the only existing record is FAILED; else raise ConflictError."""
    existing = documents_repo.find_document_by_hash(file_hash)
    if not existing:
        return
    prior_status = existing.get("status")
    if prior_status in (DocumentStatus.FAILED, DocumentStatus.STAGED):
        prior_id = existing["_key"]
        chunks_removed = documents_repo.delete_chunks_for_document(prior_id)
        documents_repo.hard_delete_document(prior_id)
        log.info(
            "discarded prior %s document %s (chunks_removed=%d) "
            "to allow re-upload of identical content (hash=%s)",
            prior_status,
            prior_id,
            chunks_removed,
            file_hash,
        )
        return
    raise ConflictError(
        "Duplicate document — a file with identical content already exists",
        details={
            "existing_doc_id": existing["_key"],
            "existing_status": prior_status,
            "file_hash": file_hash,
        },
    )


def _ensure_staging_store_ready_sync() -> None:
    """Create ``documents`` / ``chunks`` only (sync; safe inside ``asyncio.to_thread``)."""
    try:
        ensure_staging_schema()
    except Exception as exc:
        log.exception("staging schema failed before document write")
        raise ValidationError(
            "Document staging collections are not ready in Arango (via gateway). "
            f"Check gateway connectivity: {exc}",
            details={"exception_type": type(exc).__name__},
        ) from exc


async def _ensure_staging_store_ready() -> None:
    """Create ``documents`` / ``chunks`` before registering a staged upload."""
    try:
        await ensure_staging_schema_async()
    except Exception as exc:
        log.exception("staging schema failed before document write")
        raise ValidationError(
            "Document staging collections are not ready in Arango (via gateway). "
            f"Check gateway connectivity: {exc}",
            details={"exception_type": type(exc).__name__},
        ) from exc


async def _ensure_document_store_ready() -> None:
    """Apply full ontology migrations before parse/chunk/embed or extraction."""
    try:
        await ensure_ontology_schema_async()
    except Exception as exc:
        log.exception("schema bootstrap failed before document processing")
        raise ValidationError(
            "Ontology/document schema is not ready in Arango (via gateway). "
            f"Check gateway connectivity and migrations: {exc}",
            details={"exception_type": type(exc).__name__},
        ) from exc


def _persist_upload_metadata(
    doc_id: str,
    filename: str,
    content: bytes,
    *,
    required: bool = True,
) -> dict[str, Any]:
    """Write bytes to UC volume; return metadata dict with ``volume_relative_path``."""
    try:
        rel = persist_upload(doc_id=doc_id, filename=filename, content=content)
        return {"volume_relative_path": rel, "volume_source": "upload"}
    except (OSError, ValueError) as exc:
        if required:
            raise ValidationError(
                f"Could not save file to UC volume (READ/WRITE VOLUME grant on "
                f"workflow-data/uploads/ required): {exc}",
                details={"exception_type": type(exc).__name__},
            ) from exc
        log.warning("Could not persist upload to UC volume for %s: %s", doc_id, exc)
        return {}


async def _queue_processing(
    doc_id: str,
    content: bytes,
    mime: str,
) -> dict[str, Any]:
    """Ensure DB schema, then start parse → chunk → embed in the background."""
    schema_info = await ensure_ontology_schema_async()
    task = asyncio.create_task(process_document(doc_id, content, mime))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return schema_info


def _to_doc_response(doc: dict[str, Any]) -> dict[str, Any]:
    """Ensure the dict has the fields DocumentResponse expects."""
    return {
        "_key": doc["_key"],
        "filename": doc.get("filename", ""),
        "mime_type": doc.get("mime_type", ""),
        "org_id": doc.get("org_id"),
        "status": doc.get("status", "uploading"),
        "upload_date": doc.get("upload_date", ""),
        "chunk_count": doc.get("chunk_count", 0),
        "metadata": doc.get("metadata"),
        "file_hash": doc.get("file_hash"),
        "error_message": doc.get("error_message"),
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile,
    org_id: Annotated[str | None, Query()] = None,
    x_original_filename: Annotated[
        str | None,
        Header(
            alias="X-Original-Filename",
            description="Original client filename when multipart omits Content-Disposition",
        ),
    ] = None,
    process: Annotated[
        bool,
        Query(
            description=(
                "When true, run parse/chunk/embed immediately after saving to the UC volume. "
                "Default false: file is staged under workflow-data/uploads/ only."
            ),
        ),
    ] = False,
) -> dict[str, Any]:
    """Save upload to UC workflow-data; optionally start parse/chunk/embed."""
    content = await file.read()
    filename = resolve_upload_filename(
        upload_name=file.filename,
        client_hint=x_original_filename,
        content_type=file.content_type,
        content=content,
    )
    mime = _validate_mime(filename=filename, content_type=file.content_type)

    file_hash = compute_file_hash(content)
    await _ensure_staging_store_ready()
    await asyncio.to_thread(_resolve_duplicate_hash, file_hash)

    initial_status = DocumentStatus.UPLOADING if process else DocumentStatus.STAGED
    doc_id = secrets.token_hex(8)
    volume_meta: dict[str, Any] = {}
    try:
        volume_meta = await asyncio.to_thread(
            _persist_upload_metadata,
            doc_id=doc_id,
            filename=filename,
            content=content,
        )
        volume_meta["original_filename"] = filename
        if file.filename and file.filename != filename:
            volume_meta["multipart_filename"] = file.filename

        doc = await asyncio.to_thread(
            documents_repo.create_document,
            doc_id=doc_id,
            filename=filename,
            mime_type=mime,
            file_hash=file_hash,
            org_id=org_id,
            status=initial_status,
            metadata=volume_meta,
        )
    except ValidationError:
        rel = volume_meta.get("volume_relative_path")
        if rel:
            await asyncio.to_thread(vol.delete_relative, rel)
        raise
    except Exception as exc:
        log.exception("create_document failed during upload doc_id=%s", doc_id)
        rel = volume_meta.get("volume_relative_path")
        if rel:
            await asyncio.to_thread(vol.delete_relative, rel)
        raise ValidationError(
            f"Could not register document in Arango: {exc}",
            details={"exception_type": type(exc).__name__, "doc_id": doc_id},
        ) from exc
    schema_info: dict[str, Any] | None = None
    if process:
        schema_info = await _queue_processing(doc_id, content, mime)
    else:
        documents_repo.update_document_status(doc_id, DocumentStatus.STAGED)

    out: dict[str, Any] = {
        "doc_id": doc_id,
        "filename": doc["filename"],
        "status": DocumentStatus.UPLOADING.value if process else DocumentStatus.STAGED.value,
    }
    if volume_meta.get("volume_relative_path"):
        out["volume_path"] = volume_meta["volume_relative_path"]
    if schema_info is not None:
        out["schema"] = schema_info
    return out


@router.get("/volume/status")
async def volume_status() -> dict[str, Any]:
    """UC workflow-data mount status (for UI and ops)."""
    return workflow_data_status()


@router.get("/volume/browse")
async def volume_browse(
    prefix: str = Query(default="builtin", description="Subpath under workflow-data"),
    limit: int = Query(default=500, ge=1, le=2000),
    file_kind: str = Query(
        default="all",
        description="Filter: document, ontology, or all",
    ),
) -> dict[str, Any]:
    """List ingestible files on the UC volume (built-in corpora and prior uploads)."""
    if file_kind not in ("all", "document", "ontology", "instance"):
        raise ValidationError("file_kind must be all, document, ontology, or instance")
    try:
        files = await asyncio.to_thread(
            browse_volume, prefix=prefix, limit=limit, file_kind=file_kind
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return {"prefix": prefix, "files": files, **workflow_data_status()}


def _ingest_from_volume_impl(
    body: IngestFromVolumeBody,
    org_id: str | None,
    process: bool,
) -> tuple[dict[str, Any], tuple[str, bytes, str] | None]:
    """Sync UC ingest (run in worker thread). Returns response + optional process triple."""
    rel = body.path.strip().lstrip("/")
    try:
        content, filename, mime = ingest_file_from_volume(relative_path=rel)
    except FileNotFoundError as exc:
        raise ValidationError(
            f"Volume file not found at workflow-data/{rel}. "
            "Re-run deploy seed or check READ VOLUME on the app.",
            details={"path": rel},
        ) from exc
    except ValueError as exc:
        raise ValidationError(str(exc), details={"path": rel}) from exc
    except OSError as exc:
        raise ValidationError(
            f"Could not read workflow-data/{rel} from UC volume: {exc}",
            details={"path": rel, "exception_type": type(exc).__name__},
        ) from exc

    file_hash = compute_file_hash(content)
    _ensure_staging_store_ready_sync()
    try:
        _resolve_duplicate_hash(file_hash)
    except ConflictError as exc:
        raise ValidationError(
            exc.message,
            details={**(exc.details or {}), "path": rel},
        ) from exc

    source = "builtin" if rel.startswith("builtin/") else "upload"
    initial_status = DocumentStatus.UPLOADING if process else DocumentStatus.STAGED

    doc_id = secrets.token_hex(8)
    try:
        upload_rel = _persist_upload_metadata(doc_id=doc_id, filename=filename, content=content)
    except ValidationError as exc:
        raise ValidationError(
            exc.message,
            details={**(exc.details or {}), "path": rel, "doc_id": doc_id},
        ) from exc
    volume_meta = {
        **upload_rel,
        "volume_source_path": rel,
        "volume_source": source,
    }

    try:
        doc = documents_repo.create_document(
            doc_id=doc_id,
            filename=filename,
            mime_type=mime,
            file_hash=file_hash,
            org_id=org_id,
            status=initial_status,
            metadata=volume_meta,
        )
    except Exception as exc:
        log.exception("create_document failed during ingest-from-volume path=%s", rel)
        raise ValidationError(
            f"Could not register document in Arango for {filename}: {exc}",
            details={"path": rel, "doc_id": doc_id, "exception_type": type(exc).__name__},
        ) from exc
    if not process:
        try:
            documents_repo.update_document_status(doc_id, DocumentStatus.STAGED)
        except Exception as exc:
            log.exception("update_document_status failed path=%s", rel)
            raise ValidationError(
                f"Document saved but status update failed: {exc}",
                details={"path": rel, "doc_id": doc_id, "exception_type": type(exc).__name__},
            ) from exc

    out: dict[str, Any] = {
        "doc_id": doc_id,
        "filename": doc["filename"],
        "status": DocumentStatus.UPLOADING.value if process else DocumentStatus.STAGED.value,
        "volume_path": upload_rel.get("volume_relative_path"),
        "volume_source": source,
        "volume_source_path": rel,
    }
    process_args = (doc_id, content, mime) if process else None
    return out, process_args


@router.post("/ingest-from-volume")
async def ingest_from_volume(
    body: IngestFromVolumeBody,
    org_id: Annotated[str | None, Query()] = None,
    process: Annotated[
        bool,
        Query(
            description="When true, run parse/chunk/embed after copying into workflow-data/uploads/."
        ),
    ] = False,
) -> dict[str, Any]:
    """Register a UC workflow-data file and copy it under uploads/<doc-id>/ (no local picker)."""
    rel = body.path.strip().lstrip("/")
    try:
        out, process_args = await asyncio.to_thread(
            _ingest_from_volume_impl, body, org_id, process
        )
    except ValidationError:
        raise
    except Exception as exc:
        log.exception("ingest-from-volume failed path=%s", rel)
        raise ValidationError(
            f"Could not ingest workflow-data/{rel}: {exc}",
            details={"path": rel, "exception_type": type(exc).__name__},
        ) from exc

    if process_args is not None:
        doc_id, content, mime = process_args
        try:
            schema_info = await _queue_processing(doc_id, content, mime)
            out["schema"] = schema_info
        except Exception as exc:
            log.exception("queue_processing failed during ingest-from-volume path=%s", rel)
            raise ValidationError(
                f"Document saved but processing could not start: {exc}",
                details={"path": rel, "doc_id": doc_id, "exception_type": type(exc).__name__},
            ) from exc
    return out


_PREPARE_ALLOWED = frozenset(
    {
        DocumentStatus.STAGED,
        DocumentStatus.FAILED,
        DocumentStatus.UPLOADING,
    }
)

_ACTIVE_PIPELINE_STATUSES = frozenset(
    {
        DocumentStatus.PARSING,
        DocumentStatus.CHUNKING,
        DocumentStatus.EMBEDDING,
        DocumentStatus.UPLOADING,
    }
)


def _track_background_task(task: asyncio.Task[None]) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _pipeline_flags(doc: dict[str, Any]) -> dict[str, bool]:
    pipeline = (doc.get("metadata") or {}).get("pipeline") or {}
    status = doc.get("status", "")
    return {
        "parsed": bool(pipeline.get("parsed"))
        or status
        in (
            DocumentStatus.PARSED,
            DocumentStatus.CHUNKING,
            DocumentStatus.CHUNKED,
            DocumentStatus.EMBEDDING,
            DocumentStatus.READY,
        ),
        "chunked": bool(pipeline.get("chunked"))
        or status
        in (
            DocumentStatus.CHUNKED,
            DocumentStatus.EMBEDDING,
            DocumentStatus.READY,
        )
        or int(doc.get("chunk_count") or 0) > 0,
        "embedded": bool(pipeline.get("embedded")) or status == DocumentStatus.READY,
    }


async def _run_pipeline_stage(doc_id: str, stage: Literal["parse", "chunk", "embed"]) -> None:
    await ensure_ontology_schema_async()
    if stage == "parse":
        doc = documents_repo.get_document(doc_id)
        if not doc:
            return
        content, _filename, mime = read_staged_document_bytes(doc)
        await run_parse_stage(doc_id, content, mime)
    elif stage == "chunk":
        await run_chunk_stage(doc_id)
    else:
        await run_embed_stage(doc_id)


def _queue_pipeline_stage(doc_id: str, stage: Literal["parse", "chunk", "embed"]) -> None:
    task = asyncio.create_task(_run_pipeline_stage(doc_id, stage))
    _track_background_task(task)


def _assert_stage_allowed(doc: dict[str, Any], stage: Literal["parse", "chunk", "embed"]) -> None:
    status = doc.get("status", "")
    if status in _ACTIVE_PIPELINE_STATUSES:
        raise ConflictError(f"Document is already processing (status={status})")
    flags = _pipeline_flags(doc)
    if stage == "parse":
        if status == DocumentStatus.READY:
            raise ValidationError("Document is already completed")
        return
    if stage == "chunk":
        if not flags["parsed"]:
            raise ValidationError("Parse this document before chunking")
        if flags["embedded"]:
            raise ValidationError("Document is already completed")
        return
    if not flags["chunked"]:
        raise ValidationError("Chunk this document before embedding")
    if flags["embedded"]:
        raise ValidationError("Document is already embedded")


@router.post("/pipeline/batch")
async def pipeline_batch(body: PipelineBatchBody) -> dict[str, Any]:
    """Start parse, chunk, or embed for multiple documents (background tasks)."""
    queued: list[str] = []
    for doc_id in body.doc_ids:
        doc = documents_repo.get_document(doc_id)
        if not doc:
            continue
        try:
            _assert_stage_allowed(doc, body.stage)
        except (ValidationError, ConflictError):
            continue
        _queue_pipeline_stage(doc_id, body.stage)
        queued.append(doc_id)
    return {"stage": body.stage, "queued": queued, "count": len(queued)}


@router.post("/pipeline/cancel")
async def pipeline_cancel(body: PipelineCancelBody) -> dict[str, Any]:
    """Request cancellation between pipeline stages (best-effort)."""
    for doc_id in body.doc_ids:
        request_pipeline_cancel(doc_id)
    return {"cancelled": body.doc_ids, "count": len(body.doc_ids)}


@router.post("/{doc_id}/pipeline/parse")
async def pipeline_parse(doc_id: str) -> dict[str, Any]:
    doc = get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    _assert_stage_allowed(doc, "parse")
    _queue_pipeline_stage(doc_id, "parse")
    return {"doc_id": doc_id, "stage": "parse", "status": "queued"}


@router.post("/{doc_id}/pipeline/chunk")
async def pipeline_chunk(doc_id: str) -> dict[str, Any]:
    doc = get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    _assert_stage_allowed(doc, "chunk")
    _queue_pipeline_stage(doc_id, "chunk")
    return {"doc_id": doc_id, "stage": "chunk", "status": "queued"}


@router.post("/{doc_id}/pipeline/embed")
async def pipeline_embed(doc_id: str) -> dict[str, Any]:
    doc = get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    _assert_stage_allowed(doc, "embed")
    _queue_pipeline_stage(doc_id, "embed")
    return {"doc_id": doc_id, "stage": "embed", "status": "queued"}


@router.post("/{doc_id}/prepare")
async def prepare_document(doc_id: str) -> dict[str, Any]:
    """Parse, chunk, and embed a staged document (reads bytes from UC workflow-data/uploads/)."""
    doc = get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    status = doc.get("status", "")
    if status == DocumentStatus.READY:
        raise ValidationError("Document is already prepared (status=ready)")
    if status in _ACTIVE_PIPELINE_STATUSES:
        raise ConflictError(f"Document is already processing (status={status})")
    if status not in _PREPARE_ALLOWED:
        raise ValidationError(f"Cannot prepare document with status={status}")

    try:
        content, filename, mime = read_staged_document_bytes(doc)
    except FileNotFoundError as exc:
        raise ValidationError(str(exc)) from exc
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    documents_repo.delete_chunks_for_document(doc_id)
    documents_repo.update_document_status(doc_id, DocumentStatus.UPLOADING)
    schema_info = await _queue_processing(doc_id, content, mime)

    updated = documents_repo.get_document(doc_id)
    out: dict[str, Any] = {
        "doc_id": doc_id,
        "filename": filename,
        "status": (updated or doc).get("status", DocumentStatus.UPLOADING.value),
        "schema": schema_info,
    }
    meta = (updated or doc).get("metadata") or {}
    if meta.get("volume_relative_path"):
        out["volume_path"] = meta["volume_relative_path"]
    return out


@router.get("")
async def list_documents(
    limit: int = Query(default=25, ge=1, le=500),
    cursor: str | None = Query(default=None),
    sort: str = Query(default="upload_date"),
    order: str = Query(default="desc"),
    org_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> PaginatedResponse[dict[str, Any]]:
    """List all documents (paginated)."""
    return documents_repo.list_documents(
        limit=limit,
        cursor=cursor,
        sort_field=sort,
        sort_order=order,
        org_id=org_id,
        status=status,
    )


@router.get("/{doc_id}")
async def get_document(doc_id: str) -> dict[str, Any]:
    """Get document metadata and processing status."""
    doc = get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    return _to_doc_response(doc)


@router.get("/{doc_id}/chunks")
async def get_chunks(
    doc_id: str,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[dict[str, Any]]:
    """List chunks for a document (paginated)."""
    get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    return documents_repo.get_chunks_for_document(doc_id, limit=limit, cursor=cursor)


@router.put("/{doc_id}")
async def update_document(
    doc_id: str,
    file: UploadFile,
    org_id: str | None = Query(default=None),
    x_original_filename: Annotated[
        str | None,
        Header(alias="X-Original-Filename"),
    ] = None,
) -> dict[str, Any]:
    """Replace document content with a new file upload (J.1).

    Deletes existing chunks, re-chunks from the new file, and updates
    document metadata (filename, mime_type, file_hash, chunk_count).
    """
    doc = get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)

    content = await file.read()
    filename = resolve_upload_filename(
        upload_name=file.filename,
        client_hint=x_original_filename,
        content_type=file.content_type,
        content=content,
    )
    mime = _validate_mime(filename=filename, content_type=file.content_type)

    file_hash = compute_file_hash(content)

    existing = documents_repo.find_document_by_hash(file_hash)
    if existing and existing["_key"] != doc_id:
        raise ConflictError(
            "A different document with identical content already exists",
            details={"existing_doc_id": existing["_key"], "file_hash": file_hash},
        )

    documents_repo.delete_chunks_for_document(doc_id)
    volume_meta = _persist_upload_metadata(
        doc_id=doc_id, filename=filename, content=content, required=False
    )
    documents_repo.update_document_metadata(
        doc_id,
        filename=filename,
        mime_type=mime,
        file_hash=file_hash,
        chunk_count=0,
        metadata=volume_meta or None,
    )
    documents_repo.update_document_status(doc_id, DocumentStatus.UPLOADING)

    await _queue_processing(doc_id, content, mime)

    updated = documents_repo.get_document(doc_id)
    return _to_doc_response(updated or {"_key": doc_id})


@router.get("/{doc_id}/ontologies")
async def get_document_ontologies(doc_id: str) -> dict[str, Any]:
    """List ontologies extracted from a document (via ``extracted_from`` edges)."""
    get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)

    db = get_db()
    ontologies: list[dict[str, Any]] = []
    if db.has_collection("extracted_from") and db.has_collection("ontology_registry"):
        ontologies = list(
            run_aql(
                db,
                "FOR e IN extracted_from "
                "FILTER e._to == @doc_id "
                "LET oid = e.ontology_id "
                "COLLECT ontology_id = oid INTO group "
                "FOR o IN ontology_registry "
                "FILTER o._key == ontology_id "
                "RETURN {_key: o._key, name: o.name, tier: o.tier, "
                "class_count: o.class_count, status: o.status, edge_count: LENGTH(group)}",
                bind_vars={"doc_id": f"documents/{doc_id}"},
            )
        )

    return {"doc_id": doc_id, "ontologies": ontologies}


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    confirm: bool = Query(default=False, description="Set to true to actually delete"),
) -> dict[str, Any]:
    """Delete a document with cascade analysis and confirmation."""
    get_or_404(documents_repo.get_document(doc_id), "Document", doc_id)
    return documents_repo.delete_document(doc_id, confirm=confirm)
