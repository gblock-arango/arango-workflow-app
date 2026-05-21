"""Workflow document storage on UC volume (upload + builtin sample domains)."""

from __future__ import annotations

from typing import Any

from app.workflow_platform import workflow_data_volume as vol


def workflow_data_status() -> dict[str, Any]:
    root = vol.workflow_data_root()
    builtin_root = vol.workflow_data_builtin_root()
    return {
        "workflow_data_root": str(root),
        "builtin_root": str(builtin_root),
        "builtin_uc_path": vol.workflow_data_builtin_uc_path(),
        "uploads_subdir": vol.UPLOADS_SUBDIR,
        "volume_name": vol.uc_graph_volume_name(),
        "exists": root.is_dir(),
        "builtin_manifest": (builtin_root / vol.SEED_MANIFEST_NAME).is_file(),
    }


def browse_volume(*, prefix: str = "builtin", limit: int = 500) -> list[dict[str, Any]]:
    return vol.list_files(prefix=prefix, max_entries=limit)


def ingest_file_from_volume(*, relative_path: str) -> tuple[bytes, str, str]:
    """
    Read a file from workflow-data.

    Returns (content, filename, mime_type).
    """
    rel = vol.safe_relative_path(relative_path)
    full = vol.resolve_under_workflow_data(rel)
    if not full.is_file():
        raise FileNotFoundError(rel)
    if not vol.is_allowed_document_file(full.name):
        raise ValueError(f"Unsupported file type: {full.name}")
    mime = vol.mime_for_filename(full.name)
    if not mime:
        raise ValueError(f"Unsupported file type: {full.name}")
    return full.read_bytes(), full.name, mime


def persist_upload(*, doc_id: str, filename: str, content: bytes) -> str:
    return vol.save_upload(doc_id=doc_id, filename=filename, content=content)


def seed_builtin_if_configured(*, force: bool = False) -> dict[str, Any]:
    import os

    flag = (os.environ.get("WORKFLOW_DATA_SEED_ON_STARTUP", "true") or "true").strip().lower()
    if flag in ("0", "false", "no", "off") and not force:
        return {"ok": True, "skipped": True, "reason": "WORKFLOW_DATA_SEED_ON_STARTUP=false"}
    return vol.seed_builtin_datasets_from_bundle(force=force)
