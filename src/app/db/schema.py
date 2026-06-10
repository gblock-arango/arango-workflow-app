"""
ArangoDB schema initialization via migration runner.

Delegates all collection, graph, index, and view creation to numbered
migration scripts in ``backend/migrations/``.  Idempotent — safe to run
on every startup.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.db.types import StandardDatabase

log = logging.getLogger(__name__)

MigrationProgressFn = Callable[[str, dict[str, Any] | None], None]

_MIGRATIONS_PACKAGE = Path(__file__).resolve().parent.parent.parent / "migrations"


def init_schema(
    db: StandardDatabase,
    *,
    on_progress: MigrationProgressFn | None = None,
) -> list[str]:
    """Apply all pending database migrations. Returns newly applied migration names."""
    migrations_parent = str(_MIGRATIONS_PACKAGE.parent)
    if migrations_parent not in sys.path:
        sys.path.insert(0, migrations_parent)

    from migrations.runner import apply_all

    applied = apply_all(db, on_progress=on_progress)
    if applied:
        log.info("schema init applied %d migration(s)", len(applied))
    else:
        log.info("schema already up to date")
    return applied
