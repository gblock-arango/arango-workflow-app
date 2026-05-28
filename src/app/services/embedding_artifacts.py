"""Parse/chunk/embed artifacts on the UC workflow-data volume (no Arango)."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.ingestion import Chunk, ParsedDocument, Section
from app.workflow_platform import workflow_data_volume as vol

log = logging.getLogger(__name__)

PARSED_FILENAME = "parsed.json"
CHUNKS_FILENAME = "chunks.jsonl"
EMBEDDINGS_FILENAME = "embeddings.jsonl"


def _upload_dir(doc_id: str) -> str:
    return f"{vol.UPLOADS_SUBDIR}/{doc_id}"


def parsed_relative_path(doc_id: str) -> str:
    return f"{_upload_dir(doc_id)}/{PARSED_FILENAME}"


def chunks_relative_path(doc_id: str) -> str:
    return f"{_upload_dir(doc_id)}/{CHUNKS_FILENAME}"


def embeddings_relative_path(doc_id: str) -> str:
    return f"{_upload_dir(doc_id)}/{EMBEDDINGS_FILENAME}"


def delete_pipeline_artifacts(doc_id: str) -> None:
    for rel in (
        parsed_relative_path(doc_id),
        chunks_relative_path(doc_id),
        embeddings_relative_path(doc_id),
    ):
        try:
            vol.delete_relative(rel)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Could not delete %s: %s", rel, exc)


def parsed_to_dict(parsed: ParsedDocument) -> dict[str, Any]:
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


def parsed_from_dict(data: dict[str, Any]) -> ParsedDocument:
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


def write_parsed(doc_id: str, parsed: ParsedDocument) -> None:
    rel = parsed_relative_path(doc_id)
    vol.write_bytes(relative_path=rel, content=json.dumps(parsed_to_dict(parsed), indent=2).encode("utf-8"))


def read_parsed(doc_id: str) -> ParsedDocument:
    rel = parsed_relative_path(doc_id)
    try:
        raw = json.loads(vol.read_bytes(relative_path=rel).decode("utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Document {doc_id} has not been parsed yet") from exc
    return parsed_from_dict(raw)


def write_chunks(doc_id: str, chunks: list[Chunk]) -> None:
    rel = chunks_relative_path(doc_id)
    lines: list[str] = []
    for c in chunks:
        lines.append(
            json.dumps(
                {
                    "chunk_index": c.chunk_index,
                    "text": c.text,
                    "source_page": c.source_page,
                    "section_heading": c.section_heading,
                    "token_count": c.token_count,
                },
                ensure_ascii=False,
            )
        )
    body = ("\n".join(lines) + "\n") if lines else ""
    vol.write_bytes(relative_path=rel, content=body.encode("utf-8"))


def read_chunks(doc_id: str) -> list[dict[str, Any]]:
    rel = chunks_relative_path(doc_id)
    try:
        text = vol.read_bytes(relative_path=rel).decode("utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"No chunks found for document {doc_id} — run chunk stage first") from exc
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    rows.sort(key=lambda r: int(r.get("chunk_index") or 0))
    return rows


def write_embeddings(doc_id: str, rows: list[dict[str, Any]]) -> None:
    rel = embeddings_relative_path(doc_id)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    body = ("\n".join(lines) + "\n") if lines else ""
    vol.write_bytes(relative_path=rel, content=body.encode("utf-8"))


def read_embeddings(doc_id: str) -> list[dict[str, Any]]:
    rel = embeddings_relative_path(doc_id)
    try:
        text = vol.read_bytes(relative_path=rel).decode("utf-8")
    except FileNotFoundError:
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows
