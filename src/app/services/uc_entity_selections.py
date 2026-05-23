"""Persist UC table/column selections for extraction / entity-resolution context."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.workflow_platform import workflow_data_volume as vol

log = logging.getLogger(__name__)

_SETTINGS_REL = "settings/uc_entity_selections.json"


def _selections_path() -> str:
    return _SETTINGS_REL


def load_uc_entity_selections() -> list[dict[str, Any]]:
    """Return saved UC entity rows (table + column selections)."""
    rel = _selections_path()
    try:
        raw = vol.read_bytes(rel)
        data = json.loads(raw.decode("utf-8"))
        entities = data.get("entities")
        return list(entities) if isinstance(entities, list) else []
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        log.warning("Could not read UC entity selections: %s", exc)
        return []


def save_uc_entity_selections(entities: list[dict[str, Any]]) -> dict[str, Any]:
    """Write selections JSON to the UC workflow-data volume."""
    payload = {
        "version": 1,
        "entities": entities,
    }
    vol.write_bytes(
        relative_path=_selections_path(),
        content=json.dumps(payload, indent=2).encode("utf-8"),
    )
    return {"ok": True, "count": len(entities)}


def format_uc_entities_for_prompt(entities: list[dict[str, Any]] | None = None) -> str:
    """Format persisted UC selections for injection into extraction / ER prompts."""
    rows = entities if entities is not None else load_uc_entity_selections()
    if not rows:
        return ""
    lines = [
        "Unity Catalog entities selected for this workflow (use as domain context for "
        "entity resolution and alignment with document chunks):",
    ]
    for ent in rows:
        table = ent.get("table_full_name") or ""
        col = ent.get("column_name") or ""
        dtype = ent.get("type_text") or ent.get("data_type") or ""
        comment = (ent.get("comment") or "").strip()
        if col:
            line = f"- {table}.{col} ({dtype})"
        else:
            line = f"- {table} (table)"
        if comment:
            line += f": {comment}"
        lines.append(line)
    return "\n".join(lines)
