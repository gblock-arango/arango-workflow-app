"""Unity Catalog workflow document storage under ``/Volumes/.../<volume>/workflow-data``."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def _workflow_data_dir_name() -> str:
    return (
        (os.environ.get("UC_WORKFLOW_DATA_SUBDIR") or "workflow-data").strip()
        or "workflow-data"
    )
BUILTIN_SUBDIR = "builtin"
UPLOADS_SUBDIR = "uploads"
SETTINGS_SUBDIR = "settings"
SEED_MANIFEST_NAME = ".seed_manifest.json"
SEED_MANIFEST_REL = f"{SETTINGS_SUBDIR}/{SEED_MANIFEST_NAME}"

# Extensions we ingest from volume (aligned with documents API).
ALLOWED_SUFFIXES = frozenset({".md", ".pdf", ".docx", ".pptx", ".doc"})

ONTOLOGY_SUFFIXES = frozenset(
    {".jsonld", ".json-ld", ".json", ".ttl", ".turtle", ".owl", ".rdf", ".n3", ".nt", ".xml", ".skos"}
)

_SUFFIX_TO_MIME: dict[str, str] = {
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
}

_ONTOLOGY_SUFFIX_TO_MIME: dict[str, str] = {
    ".jsonld": "application/ld+json",
    ".json-ld": "application/ld+json",
    ".json": "application/json",
    ".ttl": "text/turtle",
    ".turtle": "text/turtle",
    ".owl": "application/rdf+xml",
    ".rdf": "application/rdf+xml",
    ".n3": "text/n3",
    ".nt": "application/n-triples",
    ".xml": "application/xml",
    ".skos": "application/xml",
}


def _registry_catalog_schema() -> tuple[str, str]:
    table = (os.environ.get("ARANGO_REGISTRY_TABLE") or "workspace.default.arango_connection_registry").strip()
    parts = table.split(".")
    if len(parts) >= 3:
        return parts[0], parts[1]
    return "workspace", "default"


def uc_graph_volume_name() -> str:
    return (os.environ.get("UC_GRAPH_VOLUME_NAME") or "arango_workflow_volume").strip() or "arango_workflow_volume"


def workflow_data_root() -> Path:
    """Absolute UC path: ``/Volumes/<catalog>/<schema>/<volume>/workflow-data``."""
    catalog, schema = _registry_catalog_schema()
    vol = uc_graph_volume_name()
    return Path(f"/Volumes/{catalog}/{schema}/{vol}") / _workflow_data_dir_name()


def workflow_data_builtin_root() -> Path:
    """``…/workflow-data/builtin`` — one subdirectory per repo ``datasets/<domain>/``."""
    return workflow_data_root() / BUILTIN_SUBDIR


def workflow_data_builtin_uc_path() -> str:
    """Human-readable UC path for UI (e.g. ``/Volumes/workspace/default/…/builtin``)."""
    return str(workflow_data_builtin_root())


def repo_datasets_dir() -> Path:
    """Bundled ``datasets/`` in the deployed app tree (synced with the repo)."""
    here = Path(__file__).resolve()
    # src/app/workflow_platform/this_file.py -> repo root is parents[3]
    root = here.parents[3]
    return root / "datasets"


def safe_relative_path(relative: str) -> str:
    """Normalize and reject path traversal."""
    rel = (relative or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise ValueError("Invalid volume path")
    return rel


def resolve_under_workflow_data(relative: str) -> Path:
    rel = safe_relative_path(relative)
    root = workflow_data_root().resolve()
    full = (root / rel).resolve()
    if not str(full).startswith(str(root)):
        raise ValueError("Path escapes workflow-data root")
    return full


def ensure_workflow_data_dirs() -> Path:
    root = workflow_data_root()
    (root / BUILTIN_SUBDIR).mkdir(parents=True, exist_ok=True)
    (root / UPLOADS_SUBDIR).mkdir(parents=True, exist_ok=True)
    (root / SETTINGS_SUBDIR).mkdir(parents=True, exist_ok=True)
    return root


def mime_for_filename(filename: str) -> str | None:
    lower = (filename or "").lower()
    for suffix, mime in _SUFFIX_TO_MIME.items():
        if lower.endswith(suffix):
            return mime
    return mime_for_ontology_filename(filename)


def is_allowed_document_file(name: str) -> bool:
    lower = (name or "").lower()
    return any(lower.endswith(s) for s in ALLOWED_SUFFIXES)


def is_allowed_ontology_file(name: str) -> bool:
    lower = (name or "").lower()
    return any(lower.endswith(s) for s in ONTOLOGY_SUFFIXES)


def mime_for_ontology_filename(filename: str) -> str | None:
    lower = (filename or "").lower()
    for suffix, mime in _ONTOLOGY_SUFFIX_TO_MIME.items():
        if lower.endswith(suffix):
            return mime
    return None


def is_seed_manifest_name(name: str) -> bool:
    return (name or "").strip() == SEED_MANIFEST_NAME


def is_volume_file_allowed(name: str, *, file_kind: str = "all") -> bool:
    """``file_kind``: ``document``, ``ontology``, or ``all``."""
    if file_kind == "document":
        return is_allowed_document_file(name)
    if file_kind == "ontology":
        return is_allowed_ontology_file(name)
    return is_allowed_document_file(name) or is_allowed_ontology_file(name)


def is_volume_file_browsable(
    name: str, *, rel_path: str = "", file_kind: str = "all"
) -> bool:
    """Stricter filter for UC volume browse UI (hides seed manifest and instance JSON)."""
    if is_seed_manifest_name(name) or (name or "").startswith("."):
        return False
    rel = (rel_path or "").replace("\\", "/")
    if rel.endswith(SEED_MANIFEST_NAME) or f"/{SEED_MANIFEST_NAME}" in rel:
        return False
    if file_kind == "document":
        if rel.startswith(f"{BUILTIN_SUBDIR}/ontologies/"):
            return False
        return is_allowed_document_file(name)
    if file_kind == "ontology":
        lower = (name or "").lower()
        if lower.endswith(".json") and not (
            lower.endswith(".jsonld") or lower.endswith(".json-ld")
        ):
            return False
        if not is_allowed_ontology_file(name):
            return False
        return rel.startswith(f"{BUILTIN_SUBDIR}/ontologies/")
    return is_volume_file_allowed(name, file_kind=file_kind)


def write_bytes(*, relative_path: str, content: bytes) -> str:
    """Write file under workflow-data; returns normalized relative path."""
    rel = safe_relative_path(relative_path)
    try:
        if use_files_api_for_io():
            return _write_via_files_api(rel=rel, content=content)

        dest = resolve_under_workflow_data(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        root = workflow_data_root().resolve()
        out = str(dest.resolve().relative_to(root)).replace("\\", "/")
        logger.info("UC volume write (local_mount): %s (%d bytes)", dest, len(content))
        return out
    except Exception as exc:
        err_name = type(exc).__name__
        msg = str(exc).strip() or err_name
        logger.warning("write_bytes failed for %s: %s", rel, exc)
        raise OSError(f"UC volume write failed for workflow-data/{rel}: {msg}") from exc


def read_bytes(relative_path: str) -> bytes:
    rel = safe_relative_path(relative_path)
    try:
        if use_files_api_for_io():
            return _read_via_files_api(rel)

        return resolve_under_workflow_data(rel).read_bytes()
    except FileNotFoundError:
        raise
    except Exception as exc:
        err_name = type(exc).__name__
        msg = str(exc).strip() or err_name
        logger.warning("read_bytes failed for %s: %s", rel, exc)
        if "not found" in msg.lower() or err_name in ("NotFound", "ResourceDoesNotExist"):
            raise FileNotFoundError(rel) from exc
        raise OSError(f"UC volume read failed for workflow-data/{rel}: {msg}") from exc


def local_mount_available() -> bool:
    """True when ``/Volumes/.../workflow-data`` is mounted in the app runtime."""
    return workflow_data_root().is_dir()


def use_files_api_for_io() -> bool:
    """
    Whether UC reads/writes use the Databricks Files API instead of ``/Volumes`` paths.

    Deploy-time seed and the UC catalog UI use the Files API. On Databricks Apps the
  ``/Volumes`` mount can exist while writes there do not show up in the workspace volume
    browser — so default ``auto`` prefers Files API when ``TEST_DEPLOYMENT_MODE`` is set.
    """
    mode = (os.environ.get("UC_WORKFLOW_DATA_IO_MODE") or "auto").strip().lower()
    if mode in ("files_api", "api"):
        return True
    if mode in ("local_mount", "local", "mount"):
        return False
    if not local_mount_available():
        return True
    deploy = (os.environ.get("TEST_DEPLOYMENT_MODE") or "").strip().lower()
    if deploy and deploy not in ("local_docker", "local"):
        return True
    if (os.environ.get("DATABRICKS_RUNTIME_VERSION") or "").strip():
        return True
    return False


def _write_via_files_api(*, rel: str, content: bytes) -> str:
    from io import BytesIO

    from databricks.sdk import WorkspaceClient

    abs_path = f"{workflow_data_root_uc_path()}/{rel}"
    WorkspaceClient().files.upload(abs_path, BytesIO(content), overwrite=True)
    logger.info("UC volume write (files_api): %s (%d bytes)", abs_path, len(content))
    return rel


def _read_via_files_api(rel: str) -> bytes:
    from databricks.sdk import WorkspaceClient

    abs_path = f"{workflow_data_root_uc_path()}/{rel}"
    resp = WorkspaceClient().files.download(abs_path)
    if not resp.contents:
        raise FileNotFoundError(rel)
    return resp.contents.read()


def workflow_data_root_uc_path() -> str:
    """Absolute UC path string for Files API calls (no trailing slash)."""
    return str(workflow_data_root()).rstrip("/")


def _rel_from_uc_absolute(abs_path: str) -> str | None:
    root = workflow_data_root_uc_path()
    normalized = (abs_path or "").replace("\\", "/").rstrip("/")
    if normalized == root:
        return ""
    prefix = f"{root}/"
    if not normalized.startswith(prefix):
        return None
    return normalized[len(prefix) :]


def _list_files_local(
    *, prefix: str, max_entries: int, file_kind: str = "all"
) -> list[dict[str, Any]]:
    root = workflow_data_root()
    base = resolve_under_workflow_data(prefix) if prefix else root
    if not base.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for fn in sorted(filenames):
            if len(entries) >= max_entries:
                return entries
            full = Path(dirpath) / fn
            try:
                rel = str(full.resolve().relative_to(root.resolve())).replace("\\", "/")
            except ValueError:
                continue
            if not is_volume_file_browsable(fn, rel_path=rel, file_kind=file_kind):
                continue
            category = UPLOADS_SUBDIR if rel.startswith(f"{UPLOADS_SUBDIR}/") else BUILTIN_SUBDIR
            st = full.stat()
            entries.append(
                {
                    "path": rel,
                    "name": fn,
                    "size_bytes": st.st_size,
                    "category": category,
                    "mime_type": mime_for_filename(fn),
                }
            )
    return entries


def _list_files_via_files_api(
    *, prefix: str, max_entries: int, file_kind: str = "all"
) -> list[dict[str, Any]]:
    """List workflow-data files via Databricks Files API (works without /Volumes mount)."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import NotFound

    root = workflow_data_root_uc_path()
    base = f"{root}/{safe_relative_path(prefix)}" if prefix else root
    client = WorkspaceClient()
    entries: list[dict[str, Any]] = []
    dirs: list[str] = [base]
    seen: set[str] = set()

    while dirs and len(entries) < max_entries:
        current = dirs.pop(0)
        if current in seen:
            continue
        seen.add(current)
        try:
            children = list(client.files.list_directory_contents(current))
        except NotFound:
            continue
        except Exception as exc:
            logger.warning("Files API list failed for %s: %s", current, exc)
            continue

        subdirs: list[str] = []
        files: list[Any] = []
        for child in children:
            if child.is_directory:
                subdirs.append(child.path or f"{current}/{child.name}")
            else:
                files.append(child)

        for child in sorted(files, key=lambda c: (c.name or "")):
            if len(entries) >= max_entries:
                return entries
            name = child.name or ""
            abs_path = child.path or f"{current}/{name}"
            rel = _rel_from_uc_absolute(abs_path)
            if rel is None:
                continue
            if not is_volume_file_browsable(name, rel_path=rel, file_kind=file_kind):
                continue
            category = UPLOADS_SUBDIR if rel.startswith(f"{UPLOADS_SUBDIR}/") else BUILTIN_SUBDIR
            entries.append(
                {
                    "path": rel,
                    "name": name,
                    "size_bytes": child.file_size or 0,
                    "category": category,
                    "mime_type": mime_for_filename(name),
                }
            )

        for sub in sorted(subdirs):
            dirs.append(sub)

    return entries


def list_files(
    *, prefix: str = "", max_entries: int = 500, file_kind: str = "all"
) -> list[dict[str, Any]]:
    """
    List ingestible files under ``prefix`` (e.g. ``builtin`` or ``builtin/financial``).

    Uses the Files API when ``use_files_api_for_io()`` (Databricks Apps default), else the
    local ``/Volumes`` mount when present, with Files API fallback if the mount is empty.
    """
    if use_files_api_for_io():
        try:
            return _list_files_via_files_api(
                prefix=prefix, max_entries=max_entries, file_kind=file_kind
            )
        except Exception as exc:
            logger.warning("Files API browse failed for prefix=%s: %s", prefix, exc)
            return []

    if local_mount_available():
        local_entries = _list_files_local(
            prefix=prefix, max_entries=max_entries, file_kind=file_kind
        )
        if local_entries:
            return local_entries
    try:
        return _list_files_via_files_api(
            prefix=prefix, max_entries=max_entries, file_kind=file_kind
        )
    except Exception as exc:
        logger.warning("Files API browse failed for prefix=%s: %s", prefix, exc)
        return []


def save_upload(*, doc_id: str, filename: str, content: bytes) -> str:
    safe_name = re.sub(r"[^\w.\-]+", "_", filename or "untitled").strip("._") or "untitled"
    rel = f"{UPLOADS_SUBDIR}/{doc_id}/{safe_name}"
    return write_bytes(relative_path=rel, content=content)


def _builtin_seed_skip_dirs() -> frozenset[str]:
    """Domain folders under ``datasets/`` not copied to UC builtin (large graphs / gitignored)."""
    return frozenset({"cyber", "external", "__pycache__"})


def _seed_copy_file(*, rel: str, src: Path) -> None:
    """Copy a repo dataset file into workflow-data (Files API or local mount)."""
    if use_files_api_for_io():
        write_bytes(relative_path=rel, content=src.read_bytes())
        return
    dest = resolve_under_workflow_data(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def seed_builtin_datasets_from_bundle(*, force: bool = False) -> dict[str, Any]:
    """
    Copy repo ``datasets/<domain>/*.{md,...}`` into ``workflow-data/builtin/<domain>/``.

    Skips ``datasets/cyber`` and ``datasets/external``. Idempotent via ``.seed_manifest.json``.
    """
    root = ensure_workflow_data_dirs()
    dest_root = workflow_data_builtin_root()
    manifest_path = root / SEED_MANIFEST_REL
    src = repo_datasets_dir()

    if not force:
        try:
            if use_files_api_for_io():
                raw = read_bytes(SEED_MANIFEST_REL)
                existing = json.loads(raw.decode("utf-8"))
            elif manifest_path.is_file():
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            else:
                existing = None
            if existing and existing.get("ok") and existing.get("layout_version") == 2:
                return {"ok": True, "skipped": True, "reason": "already_seeded", **existing}
        except (OSError, json.JSONDecodeError, FileNotFoundError):
            pass

    if not src.is_dir():
        return {"ok": False, "error": f"datasets dir not found: {src}"}

    copied = 0
    domains: list[str] = []
    skip_dirs = _builtin_seed_skip_dirs()
    for domain_dir in sorted(src.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name in skip_dirs or domain_dir.name.startswith("."):
            continue
        out_domain = dest_root / domain_dir.name
        out_domain.mkdir(parents=True, exist_ok=True)
        domain_files = 0
        for f in sorted(domain_dir.iterdir()):
            if not f.is_file():
                continue
            if is_allowed_document_file(f.name):
                if not use_files_api_for_io():
                    out_domain.mkdir(parents=True, exist_ok=True)
                _seed_copy_file(rel=f"{BUILTIN_SUBDIR}/{domain_dir.name}/{f.name}", src=f)
                copied += 1
                domain_files += 1
            elif is_allowed_ontology_file(f.name):
                if not use_files_api_for_io():
                    (dest_root / "ontologies" / domain_dir.name).mkdir(parents=True, exist_ok=True)
                _seed_copy_file(
                    rel=f"{BUILTIN_SUBDIR}/ontologies/{domain_dir.name}/{f.name}",
                    src=f,
                )
                copied += 1
        if domain_files:
            domains.append(domain_dir.name)

    # Cyber ontology JSON-LD fixtures (domain skipped for documents).
    cyber_src = src / "cyber"
    if cyber_src.is_dir():
        if not use_files_api_for_io():
            (dest_root / "ontologies" / "cyber").mkdir(parents=True, exist_ok=True)
        for f in sorted(cyber_src.iterdir()):
            if f.is_file() and is_allowed_ontology_file(f.name):
                _seed_copy_file(rel=f"{BUILTIN_SUBDIR}/ontologies/cyber/{f.name}", src=f)
                copied += 1

    ontology_domains: list[str] = []
    ont_root = dest_root / "ontologies"
    if ont_root.is_dir():
        ontology_domains = sorted(
            d.name for d in ont_root.iterdir() if d.is_dir() and not d.name.startswith(".")
        )

    payload = {
        "ok": True,
        "skipped": False,
        "layout_version": 2,
        "files_copied": copied,
        "domains": domains,
        "ontology_domains": ontology_domains,
        "source": str(src),
        "destination": str(dest_root),
        "manifest_path": SEED_MANIFEST_REL,
        "note": (
            "Documents: datasets/<domain>/*.md -> builtin/<domain>/. "
            "Ontologies: *.jsonld -> builtin/ontologies/<domain>/. "
            "Instance CSV/JSON (cyber): repo only, not copied to UC."
        ),
    }
    try:
        manifest_body = json.dumps(payload, indent=2) + "\n"
        if use_files_api_for_io():
            write_bytes(relative_path=SEED_MANIFEST_REL, content=manifest_body.encode("utf-8"))
        else:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(manifest_body, encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write seed manifest: %s", exc)
    logger.info("Seeded %d builtin corpus files to %s", copied, dest_root)
    return payload
