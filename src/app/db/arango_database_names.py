"""Validation and default naming for per-run Arango databases."""

from __future__ import annotations

import logging
import re

from app.db.gateway_database import GatewayAPIError

log = logging.getLogger(__name__)

_ARANGO_DB_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_AUTO_GRAPH_PREFIX = "AutoGraph_"


def validate_arango_database_name(name: str) -> str:
    """Normalize and validate an ArangoDB user database name."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("Arango database name is required")
    if len(cleaned) > 64:
        raise ValueError("Arango database name must be at most 64 characters")
    if not _ARANGO_DB_NAME_RE.match(cleaned):
        raise ValueError(
            "Arango database name must start with a letter and contain only letters, digits, and underscores"
        )
    return cleaned


def suggest_auto_graph_database_name() -> str:
    """Return the next ``AutoGraph_<n>`` name based on existing Arango databases."""
    from app.db.client import get_system_db

    try:
        names = get_system_db().databases()
    except GatewayAPIError:
        log.warning("could not list Arango databases for AutoGraph suggestion", exc_info=True)
        return f"{_AUTO_GRAPH_PREFIX}1"

    nums: list[int] = []
    for name in names:
        if not name.startswith(_AUTO_GRAPH_PREFIX):
            continue
        tail = name[len(_AUTO_GRAPH_PREFIX) :]
        if tail.isdigit():
            nums.append(int(tail))
    next_num = (max(nums) + 1) if nums else 1
    return f"{_AUTO_GRAPH_PREFIX}{next_num}"


def resolve_arango_database_name(requested: str | None) -> str:
    """Use the requested name or suggest ``AutoGraph_<n>`` when empty."""
    if requested and requested.strip():
        return validate_arango_database_name(requested)
    return suggest_auto_graph_database_name()


def discover_extraction_databases() -> list[str]:
    """List user databases that may hold extraction runs (``AutoGraph_*`` + env default)."""
    from app.config import settings
    from app.db.client import get_system_db

    default = settings.arango_db
    try:
        names = get_system_db().databases()
    except GatewayAPIError:
        log.warning("could not list databases for run discovery", exc_info=True)
        return [default]

    found = sorted(
        {
            name
            for name in names
            if name == default or name.startswith(_AUTO_GRAPH_PREFIX)
        }
    )
    return found or [default]
