"""Persist extraction prompt template overrides on the UC workflow volume."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

_OVERRIDES_REL = "extraction_prompts/overrides.json"
_VERSION = 1


def _read_overrides_file() -> dict[str, Any]:
    from app.workflow_platform import workflow_data_volume as vol

    try:
        raw = vol.read_bytes(_OVERRIDES_REL)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        log.warning("Could not read extraction prompt overrides: %s", exc)
        return {}


def _write_overrides_file(payload: dict[str, Any]) -> None:
    from app.workflow_platform import workflow_data_volume as vol

    vol.write_bytes(
        relative_path=_OVERRIDES_REL,
        content=json.dumps(payload, indent=2).encode("utf-8"),
    )


def load_template_override(key: str) -> dict[str, str] | None:
    data = _read_overrides_file()
    templates = data.get("templates")
    if not isinstance(templates, dict):
        return None
    entry = templates.get(key)
    if not isinstance(entry, dict):
        return None
    system_prompt = (entry.get("system_prompt") or "").strip()
    user_prompt = (entry.get("user_prompt") or "").strip()
    if not system_prompt and not user_prompt:
        return None
    return {
        "system_prompt": entry.get("system_prompt") or "",
        "user_prompt": entry.get("user_prompt") or "",
    }


def list_saved_template_keys() -> list[str]:
    data = _read_overrides_file()
    templates = data.get("templates")
    if not isinstance(templates, dict):
        return []
    return sorted(str(k) for k in templates)


def list_templates_catalog() -> list[dict[str, Any]]:
    from app.extraction.prompts import get_builtin_template, list_templates

    catalog: list[dict[str, Any]] = []
    for key in list_templates():
        builtin = get_builtin_template(key)
        override = load_template_override(key)
        effective_system = override["system_prompt"] if override else builtin.system_prompt
        effective_user = override["user_prompt"] if override else builtin.user_prompt
        catalog.append(
            {
                "key": key,
                "description": builtin.description,
                "system_prompt": effective_system,
                "user_prompt": effective_user,
                "has_override": override is not None,
                "source": "override" if override else "builtin",
            }
        )
    return catalog


def get_template_catalog_entry(key: str) -> dict[str, Any]:
    from app.extraction.prompts import get_builtin_template

    builtin = get_builtin_template(key)
    override = load_template_override(key)
    effective_system = override["system_prompt"] if override else builtin.system_prompt
    effective_user = override["user_prompt"] if override else builtin.user_prompt
    return {
        "key": key,
        "description": builtin.description,
        "system_prompt": effective_system,
        "user_prompt": effective_user,
        "has_override": override is not None,
        "source": "override" if override else "builtin",
    }


def save_template_override(
    key: str,
    *,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    from app.extraction.prompts import get_builtin_template

    get_builtin_template(key)
    data = _read_overrides_file()
    templates = data.get("templates")
    if not isinstance(templates, dict):
        templates = {}
    templates[key] = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "updated_at": time.time(),
    }
    payload = {"version": _VERSION, "templates": templates}
    _write_overrides_file(payload)
    builtin = get_builtin_template(key)
    return {
        "key": key,
        "description": builtin.description,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "has_override": True,
        "source": "override",
    }


def bootstrap_extraction_prompt_templates() -> None:
    """Warm the template registry at startup (builtins + any UC overrides)."""
    from app.extraction.prompts import list_templates

    try:
        keys = list_templates()
        log.info("extraction_prompt_templates_ready", count=len(keys), keys=keys)
    except Exception as exc:
        log.warning("extraction_prompt_templates_bootstrap_failed", error=str(exc))
