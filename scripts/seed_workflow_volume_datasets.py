#!/usr/bin/env python3
"""Seed repo ``datasets/`` into UC ``workflow-data/builtin/<domain>/`` (deploy-time, from laptop/CI).

Uses the Databricks Files API (requires ``databricks auth login`` or profile).
App startup also seeds when ``WORKFLOW_DATA_SEED_ON_STARTUP=true`` and ``/Volumes`` is mounted.

Layout (layout_version 2): no ``builtin/corpora/`` — each repo domain folder maps to
``/Volumes/<catalog>/<schema>/<volume>/workflow-data/builtin/<domain>/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from app.workflow_platform import workflow_data_volume as vol  # noqa: E402


def _upload_via_sdk(
    *,
    catalog: str,
    schema: str,
    volume: str,
    datasets_dir: Path,
    profile: str | None,
    force: bool,
) -> dict:
    from databricks.sdk import WorkspaceClient

    kwargs: dict = {}
    if profile:
        kwargs["profile"] = profile
    w = WorkspaceClient(**kwargs)

    subdir = vol._workflow_data_dir_name()
    dest_prefix = f"/Volumes/{catalog}/{schema}/{volume}/{subdir}/{vol.BUILTIN_SUBDIR}"
    skip_dirs = vol._builtin_seed_skip_dirs()
    copied = 0
    domains: list[str] = []

    for domain_dir in sorted(datasets_dir.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name in skip_dirs or domain_dir.name.startswith("."):
            continue
        domain_files = 0
        for f in sorted(domain_dir.iterdir()):
            if not f.is_file() or not vol.is_allowed_document_file(f.name):
                continue
            remote = f"{dest_prefix}/{domain_dir.name}/{f.name}"
            with f.open("rb") as stream:
                w.files.upload(remote, stream, overwrite=True)
            copied += 1
            domain_files += 1
        if domain_files:
            domains.append(domain_dir.name)

    manifest_remote = f"{dest_prefix}/{vol.SEED_MANIFEST_NAME}"
    payload = {
        "ok": True,
        "skipped": False,
        "layout_version": 2,
        "files_copied": copied,
        "domains": domains,
        "source": str(datasets_dir),
        "destination": dest_prefix,
        "via": "databricks-sdk",
        "force": force,
        "note": "One UC folder per repo datasets/<domain>/ (no builtin/corpora/).",
    }
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        tmp.write(json.dumps(payload, indent=2))
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as stream:
            w.files.upload(manifest_remote, stream, overwrite=True)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="workspace")
    parser.add_argument("--schema", default="default")
    parser.add_argument("--volume", default="arango_workflow_volume")
    parser.add_argument("--datasets-dir", type=Path, default=REPO_ROOT / "datasets")
    parser.add_argument("--profile", default="")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Upload all files even if .seed_manifest.json already exists on the volume",
    )
    args = parser.parse_args()

    if not args.datasets_dir.is_dir():
        print(f"ERROR: datasets dir not found: {args.datasets_dir}", file=sys.stderr)
        return 1

    profile = (args.profile or "").strip() or None
    result = _upload_via_sdk(
        catalog=args.catalog,
        schema=args.schema,
        volume=args.volume,
        datasets_dir=args.datasets_dir,
        profile=profile,
        force=args.force,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
