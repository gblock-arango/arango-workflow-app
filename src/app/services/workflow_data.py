"""Workflow document storage on UC volume (upload + builtin sample domains)."""

from __future__ import annotations

import time
from typing import Any

from app.workflow_platform import workflow_data_volume as vol

_files_api_probe_cache: dict[str, Any] = {"at": 0.0, "ok": False}


def workflow_data_status() -> dict[str, Any]:
    root = vol.workflow_data_root()
    builtin_root = vol.workflow_data_builtin_root()
    local_mount = vol.local_mount_available()
    files_api_io = vol.use_files_api_for_io()
    manifest_path = vol.workflow_data_root() / vol.SEED_MANIFEST_REL
    builtin_manifest = manifest_path.is_file() if local_mount and not files_api_io else False
    access_mode = "files_api" if files_api_io else "local_mount"
    now = time.monotonic()
    if now - float(_files_api_probe_cache.get("at") or 0.0) < 90.0:
        files_api_ok = bool(_files_api_probe_cache.get("ok"))
    else:
        files_api_ok = False
        try:
            files_api_ok = len(vol.list_files(prefix=vol.BUILTIN_SUBDIR, max_entries=1)) > 0
        except Exception:
            files_api_ok = False
        _files_api_probe_cache["at"] = now
        _files_api_probe_cache["ok"] = files_api_ok
    if not files_api_io and local_mount:
        builtin_manifest = manifest_path.is_file()
    return {
        "workflow_data_root": str(root),
        "builtin_root": str(builtin_root),
        "builtin_uc_path": vol.workflow_data_builtin_uc_path(),
        "uploads_subdir": vol.UPLOADS_SUBDIR,
        "volume_name": vol.uc_graph_volume_name(),
        "exists": files_api_ok or local_mount,
        "local_mount": local_mount,
        "access_mode": access_mode,
        "io_mode": access_mode,
        "files_api_reachable": files_api_ok,
        "builtin_manifest": builtin_manifest,
    }


def browse_volume(
    *, prefix: str = "builtin", limit: int = 500, file_kind: str = "all"
) -> list[dict[str, Any]]:
    return vol.list_files(prefix=prefix, max_entries=limit, file_kind=file_kind)


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

    Uses the Databricks Files API when ``/Volumes`` is not mounted (same path
    listing uses in ``list_files``), so browse + ingest stay consistent on Apps.

    Returns (content, filename, mime_type).
    """
    rel = vol.safe_relative_path(relative_path)
    filename = rel.rsplit("/", 1)[-1]
    if not vol.is_allowed_document_file(filename) and not vol.is_allowed_ontology_file(
        filename
    ):
        raise ValueError(f"Unsupported file type: {filename}")
    mime = vol.mime_for_filename(filename) or vol.mime_for_ontology_filename(filename)
    if not mime:
        raise ValueError(f"Unsupported file type: {filename}")
    try:
        content = vol.read_bytes(rel)
    except FileNotFoundError as exc:
        raise FileNotFoundError(rel) from exc
    return content, filename, mime


def persist_upload(*, doc_id: str, filename: str, content: bytes) -> str:
    return vol.save_upload(doc_id=doc_id, filename=filename, content=content)


def seed_builtin_if_configured(*, force: bool = False) -> dict[str, Any]:
    import os

    flag = (os.environ.get("WORKFLOW_DATA_SEED_ON_STARTUP", "true") or "true").strip().lower()
    if flag in ("0", "false", "no", "off") and not force:
        return {"ok": True, "skipped": True, "reason": "WORKFLOW_DATA_SEED_ON_STARTUP=false"}
    return vol.seed_builtin_datasets_from_bundle(force=force)
