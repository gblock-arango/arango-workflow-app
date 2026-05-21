"""Workflow document storage on UC volume (upload + builtin sample domains)."""

from __future__ import annotations

from typing import Any

from app.workflow_platform import workflow_data_volume as vol


def workflow_data_status() -> dict[str, Any]:
    root = vol.workflow_data_root()
    builtin_root = vol.workflow_data_builtin_root()
    local_mount = vol.local_mount_available()
    builtin_manifest = (builtin_root / vol.SEED_MANIFEST_NAME).is_file()
    access_mode = "local_mount" if local_mount else "files_api"
    files_api_ok = False
    if not local_mount:
        try:
            files_api_ok = len(vol.list_files(prefix=vol.BUILTIN_SUBDIR, max_entries=1)) > 0
        except Exception:
            files_api_ok = False
    else:
        files_api_ok = True
    return {
        "workflow_data_root": str(root),
        "builtin_root": str(builtin_root),
        "builtin_uc_path": vol.workflow_data_builtin_uc_path(),
        "uploads_subdir": vol.UPLOADS_SUBDIR,
        "volume_name": vol.uc_graph_volume_name(),
        "exists": local_mount or files_api_ok,
        "local_mount": local_mount,
        "access_mode": access_mode,
        "files_api_reachable": files_api_ok,
        "builtin_manifest": builtin_manifest,
    }


def browse_volume(*, prefix: str = "builtin", limit: int = 500) -> list[dict[str, Any]]:
    return vol.list_files(prefix=prefix, max_entries=limit)


def read_staged_document_bytes(doc: dict[str, Any]) -> tuple[bytes, str, str]:
    """
    Load document bytes from UC workflow-data for parse/chunk/embed.

    Uses ``metadata.volume_relative_path`` (under ``uploads/<doc-id>/``).
    """
    meta = doc.get("metadata") or {}
    rel = (meta.get("volume_relative_path") or "").strip()
    if not rel:
        raise ValueError(
            "Document has no UC volume copy — re-upload the file or ingest from volume again."
        )
    return ingest_file_from_volume(relative_path=rel)


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
