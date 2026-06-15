"""Stable chunk document keys shared by UC artifacts, Arango, and LLM citations."""

from __future__ import annotations

import re
from typing import Any

_KEY_SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _sanitize_key_part(value: str) -> str:
    cleaned = _KEY_SAFE.sub("_", value).strip("_")
    return cleaned or "doc"


def chunk_document_key(doc_id: str, chunk_index: int) -> str:
    """Deterministic Arango ``_key`` for a document chunk.

    Keys are scoped by ``doc_id`` because the ``chunks`` collection is shared
    across documents. Format: ``{doc_id}_{chunk_index}`` (sanitized).
    """
    return f"{_sanitize_key_part(doc_id)}_{int(chunk_index)}"


def resolve_chunk_source_id(chunk: dict[str, Any]) -> str:
    """Return the stable id used in prompts and provenance lookups."""
    if chunk.get("_key"):
        return str(chunk["_key"])
    if chunk.get("chunk_key"):
        return str(chunk["chunk_key"])
    doc_id = chunk.get("doc_id")
    chunk_index = chunk.get("chunk_index")
    if doc_id is not None and chunk_index is not None:
        return chunk_document_key(str(doc_id), int(chunk_index))
    return str(chunk.get("chunk_index", ""))


def normalize_chunk_for_insert(chunk: dict[str, Any]) -> dict[str, Any]:
    """Ensure ``_key`` / ``chunk_key`` are set before Arango insert."""
    doc = dict(chunk)
    doc_id = doc.get("doc_id")
    chunk_index = doc.get("chunk_index")
    if doc_id is not None and chunk_index is not None:
        key = (
            doc.get("_key")
            or doc.get("chunk_key")
            or chunk_document_key(str(doc_id), int(chunk_index))
        )
        doc["_key"] = str(key)
        doc.setdefault("chunk_key", doc["_key"])
    return doc
