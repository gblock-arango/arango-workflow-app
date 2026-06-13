"""Capture the most recent extractor LLM prompt/response for debugging."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

_LAST_CALL_REL = "extraction_prompts/last_call.json"
_VERSION = 1

_last_call_memory: dict[str, Any] | None = None


def _format_actual_prompt(system_prompt: str, user_prompt: str, extra_messages: list[str] | None = None) -> str:
    parts = [
        "=== SYSTEM ===",
        system_prompt.strip(),
        "",
        "=== USER ===",
        user_prompt.strip(),
    ]
    for idx, msg in enumerate(extra_messages or [], start=1):
        parts.extend(["", f"=== USER (retry {idx}) ===", msg.strip()])
    return "\n".join(parts).strip()


def record_extractor_llm_call(
    *,
    run_id: str,
    template_key: str,
    system_prompt: str,
    user_prompt: str,
    response_text: str,
    pass_num: int,
    batch_idx: int,
    model_name: str,
    extra_messages: list[str] | None = None,
) -> None:
    """Persist the latest extractor prompt/response (memory + UC volume)."""
    global _last_call_memory
    payload = {
        "version": _VERSION,
        "run_id": run_id,
        "template_key": template_key,
        "step": f"extractor_pass_{pass_num}",
        "pass_number": pass_num,
        "batch_idx": batch_idx,
        "model_name": model_name,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "actual_prompt": _format_actual_prompt(system_prompt, user_prompt, extra_messages),
        "response_text": response_text,
        "recorded_at": time.time(),
    }
    _last_call_memory = payload
    try:
        from app.workflow_platform import workflow_data_volume as vol

        vol.write_bytes(
            relative_path=_LAST_CALL_REL,
            content=json.dumps(payload, indent=2).encode("utf-8"),
        )
    except Exception as exc:
        log.debug("could not persist last extractor prompt: %s", exc)


def load_last_extractor_llm_call(*, run_id: str | None = None) -> dict[str, Any] | None:
    """Return the latest extractor LLM call, optionally filtered by run_id."""
    global _last_call_memory
    payload = _last_call_memory
    if payload is None:
        try:
            from app.workflow_platform import workflow_data_volume as vol

            raw = vol.read_bytes(_LAST_CALL_REL)
            data = json.loads(raw.decode("utf-8"))
            payload = data if isinstance(data, dict) else None
            _last_call_memory = payload
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            log.warning("Could not read last extractor prompt: %s", exc)
            return None
    if payload is None:
        return None
    if run_id and payload.get("run_id") != run_id:
        return None
    return dict(payload)
