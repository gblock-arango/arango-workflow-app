"""Migration runner — applies pending migrations in numeric filename order.

Tracks applied migrations in the ``aoe_system_meta`` collection with a document
keyed ``schema_state``.  Each migration is a Python module exposing an
``up(db: StandardDatabase)`` function.  The runner is idempotent: already-
applied migrations are skipped.

Usage::

    python -m migrations.runner          # from backend/
    # or programmatically:
    from migrations.runner import apply_all
    apply_all(db)
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.db.types import StandardDatabase

from app.db.utils import doc_get

log = logging.getLogger(__name__)

MigrationProgressFn = Callable[[str, dict[str, Any] | None], None]
DEFAULT_MIGRATION_HEARTBEAT_SEC = 10.0

MIGRATIONS_DIR = Path(__file__).resolve().parent
META_COLLECTION = "aoe_system_meta"
META_KEY = "schema_state"


def _ensure_meta_collection(db: StandardDatabase) -> None:
    if not db.has_collection(META_COLLECTION):
        db.create_collection(META_COLLECTION)
        log.info("created meta collection %s", META_COLLECTION)


def _load_schema_state(db: StandardDatabase) -> dict:
    col = db.collection(META_COLLECTION)
    try:
        return doc_get(col, META_KEY) or {}
    except Exception:
        return {}


def _save_schema_state(db: StandardDatabase, state: dict) -> None:
    col = db.collection(META_COLLECTION)
    state["_key"] = META_KEY
    if col.has(META_KEY):
        col.replace(state)
    else:
        col.insert(state)


def discover_migrations() -> list[str]:
    """Return migration module names sorted by numeric prefix."""
    modules: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9]*.py")):
        modules.append(path.stem)
    return modules


def apply_all(
    db: StandardDatabase,
    *,
    on_progress: MigrationProgressFn | None = None,
    heartbeat_sec: float = DEFAULT_MIGRATION_HEARTBEAT_SEC,
) -> list[str]:
    """Apply all pending migrations and return list of newly-applied names.

    Already-applied migrations (recorded in ``aoe_system_meta``) are skipped.
    ``on_progress`` is invoked before each migration and every ``heartbeat_sec``
    while a slow migration runs (keeps Diagnostics polls fresh).
    """
    def report(message: str, progress: dict[str, Any] | None = None) -> None:
        if on_progress:
            on_progress(message, progress)

    _ensure_meta_collection(db)
    state = _load_schema_state(db)
    applied: list[dict] = state.get("applied_migrations", [])
    applied_names: set[str] = {m["name"] for m in applied}

    all_migrations = discover_migrations()
    pending = [name for name in all_migrations if name not in applied_names]
    newly_applied: list[str] = []

    if pending:
        report(
            f"Applying {len(pending)} pending schema migration(s) (of {len(all_migrations)} total)…",
            {
                "phase": "schema_migration",
                "migration_pending": len(pending),
                "migration_total": len(all_migrations),
            },
        )
    else:
        report(
            f"Schema up to date ({len(all_migrations)} migrations already applied)",
            {
                "phase": "schema_migration",
                "migration_pending": 0,
                "migration_total": len(all_migrations),
            },
        )

    for mod_name in all_migrations:
        if mod_name in applied_names:
            log.debug("migration %s already applied — skipping", mod_name)
            continue

        index = len(newly_applied) + 1
        log.info("applying migration %s …", mod_name)
        report(
            f"Migration {index}/{len(pending)}: {mod_name}…",
            {
                "phase": "schema_migration",
                "migration": mod_name,
                "migration_index": index,
                "migration_pending": len(pending),
                "migration_total": len(all_migrations),
            },
        )

        module = importlib.import_module(f"migrations.{mod_name}")
        started = time.perf_counter()
        stop = threading.Event()

        def _heartbeat() -> None:
            while not stop.wait(max(1.0, float(heartbeat_sec))):
                elapsed_s = int(time.perf_counter() - started)
                report(
                    f"Still applying {mod_name} ({elapsed_s}s)…",
                    {
                        "phase": "schema_migration",
                        "migration": mod_name,
                        "migration_index": index,
                        "migration_pending": len(pending),
                        "migration_total": len(all_migrations),
                        "migration_elapsed_s": elapsed_s,
                    },
                )

        hb = threading.Thread(target=_heartbeat, name=f"migrate-hb-{mod_name}", daemon=True)
        hb.start()
        try:
            module.up(db)  # type: ignore[attr-defined]
        finally:
            stop.set()
            hb.join(timeout=1.0)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        applied.append({"name": mod_name, "applied_at": time.time()})
        newly_applied.append(mod_name)
        log.info("migration %s applied successfully", mod_name)
        report(
            f"Migration {index}/{len(pending)} done: {mod_name} ({elapsed_ms}ms)",
            {
                "phase": "schema_migration",
                "migration": mod_name,
                "migration_index": index,
                "migration_pending": len(pending),
                "migration_total": len(all_migrations),
                "migration_elapsed_ms": elapsed_ms,
                "migration_ok": True,
            },
        )

    state["schema_version"] = len(applied)
    state["applied_migrations"] = applied
    _save_schema_state(db, state)

    if newly_applied:
        log.info(
            "migration run complete — %d new, %d total",
            len(newly_applied),
            len(applied),
        )
    else:
        log.info("all %d migrations already applied — nothing to do", len(applied))

    return newly_applied


def _cli() -> None:
    """Entry-point when invoked as ``python -m migrations.runner``."""
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.db.client import get_db

    db = get_db()
    applied = apply_all(db)
    if applied:
        print(f"Applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        print("No pending migrations.")


if __name__ == "__main__":
    _cli()
