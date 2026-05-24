"""Resolve the original filename for multipart uploads (UC volume + Arango metadata)."""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote

logger = logging.getLogger(__name__)

# Multipart names that carry no user intent (proxies, empty blobs, API clients).
_GENERIC_UPLOAD_NAMES = frozenset(
    {
        "",
        "blob",
        "file",
        "upload",
        "download",
        "document",
        "untitled",
        "tmp",
        "temp",
    }
)


def _basename(name: str) -> str:
    cleaned = unquote(name).strip().replace("\\", "/")
    return cleaned.rsplit("/", 1)[-1].strip()


def _is_usable_filename(name: str) -> bool:
    if not name:
        return False
    lower = name.lower()
    if lower in _GENERIC_UPLOAD_NAMES:
        return False
    if "." not in name:
        return False
    return bool(re.search(r"[\w.\-]", name))


def _sniff_extension(content: bytes, content_type: str | None) -> str | None:
    if content.startswith(b"%PDF"):
        return ".pdf"
    if content[:4] == b"PK\x03\x04":
        ct = (content_type or "").lower()
        if "presentation" in ct or content_type == (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ):
            return ".pptx"
        if "word" in ct or content_type == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            return ".docx"
        return ".docx"
    if content.startswith(b"\x89PNG"):
        return ".png"
    try:
        sample = content[:4096].decode("utf-8")
        if sample and not "\x00" in sample:
            return ".md"
    except UnicodeDecodeError:
        pass
    return None


def resolve_upload_filename(
    *,
    upload_name: str | None,
    client_hint: str | None,
    content_type: str | None,
    content: bytes,
) -> str:
    """
    Pick a stable filename for UC ``uploads/<doc-id>/`` and the documents collection.

    Prefer the browser-provided hint (``X-Original-Filename``), then the multipart
    part name, then a content sniffed ``upload<ext>``.
    """
    candidates: list[tuple[str, str]] = []
    if client_hint:
        candidates.append(("client_hint", _basename(client_hint)))
    if upload_name:
        candidates.append(("multipart", _basename(upload_name)))

    for source, name in candidates:
        if _is_usable_filename(name):
            if source == "client_hint" or name != _basename(upload_name or ""):
                logger.debug("Resolved upload filename from %s: %s", source, name)
            return name

    ext = _sniff_extension(content, content_type)
    if ext:
        fallback = f"upload{ext}"
        logger.info(
            "Upload filename missing or generic; using sniffed name %s (multipart=%r hint=%r)",
            fallback,
            upload_name,
            client_hint,
        )
        return fallback

    logger.warning(
        "Upload filename missing or generic; falling back to untitled (multipart=%r hint=%r)",
        upload_name,
        client_hint,
    )
    return "untitled"
