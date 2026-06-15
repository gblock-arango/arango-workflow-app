"""Persist and apply user LLM provider / model preferences on the UC workflow volume."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Literal

from app.config import settings
from app.llm.databricks_serving import (
    default_embedding_dimension_for_model,
    effective_embedding_model_name,
    effective_extraction_model_name,
)

log = logging.getLogger(__name__)

_SETTINGS_REL = "settings/llm_preferences.json"
_VERSION = 1

LlmUiProvider = Literal["databricks", "openai"]

_DEFAULT_MODELS: dict[LlmUiProvider, dict[str, str]] = {
    "databricks": {
        "extraction_model": "databricks-meta-llama-3-3-70b-instruct",
        "embedding_model": "databricks-bge-large-en",
    },
    "openai": {
        "extraction_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
    },
}
_DEFAULT_DIMENSIONS: dict[LlmUiProvider, int] = {
    "databricks": 1024,
    "openai": 1536,
}

_last_applied_signature: str | None = None


def default_models_for_provider(provider: LlmUiProvider) -> dict[str, str | int]:
    models = dict(_DEFAULT_MODELS[provider])
    models["embedding_dimension"] = _DEFAULT_DIMENSIONS[provider]
    return models


def _normalize_ui_provider(raw: str | None) -> LlmUiProvider:
    value = (raw or "").strip().lower()
    if value in ("databricks", "databricks_serving"):
        return "databricks"
    return "openai"


def _provider_to_settings_value(provider: LlmUiProvider) -> str:
    return "databricks_serving" if provider == "databricks" else "openai"


def _provider_from_settings() -> LlmUiProvider:
    raw = (settings.autograph_llm_provider or "").strip().lower()
    if raw in ("databricks_serving", "databricks"):
        return "databricks"
    if raw == "openai":
        return "openai"
    if settings.use_databricks_for_extraction() or settings.use_databricks_for_embeddings():
        return "databricks"
    return "openai"


def _prefs_signature(data: dict[str, Any]) -> str:
    """Stable hash of persisted preferences (for cross-worker sync)."""
    normalized = {k: data.get(k) for k in sorted(data.keys())}
    blob = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _invalidate_probe_cache() -> None:
    from app.services import llm_connectivity

    llm_connectivity._probe_cache["at"] = 0.0
    llm_connectivity._probe_cache["payload"] = None


def sync_llm_preferences_from_volume() -> bool:
    """Apply saved UC preferences to this worker when the volume file changed.

    Databricks Apps run multiple uvicorn workers; a PUT /llm-settings only updates
    the process that handled the request unless we re-read the volume file.
    """
    global _last_applied_signature

    saved = _read_raw_preferences()
    if not saved:
        return False
    sig = _prefs_signature(saved)
    if sig == _last_applied_signature:
        return False
    apply_llm_preferences(saved)
    _last_applied_signature = sig
    _invalidate_probe_cache()
    log.info(
        "llm_preferences_synced_from_volume",
        provider=saved.get("provider"),
        extraction_model=saved.get("extraction_model"),
        embedding_model=saved.get("embedding_model"),
    )
    return True


def _read_raw_preferences() -> dict[str, Any] | None:
    from app.workflow_platform import workflow_data_volume as vol

    try:
        raw = vol.read_bytes(_SETTINGS_REL)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        log.warning("Could not read LLM preferences: %s", exc)
        return None


def _effective_settings_snapshot() -> dict[str, Any]:
    provider = _provider_from_settings()
    embedding_model = effective_embedding_model_name()
    return {
        "provider": provider,
        "extraction_model": effective_extraction_model_name(),
        "embedding_model": embedding_model,
        "embedding_dimension": settings.effective_embedding_dimension,
        "openai_api_key_configured": bool((settings.openai_api_key or "").strip()),
    }


def _resolve_embedding_dimension(
    *,
    provider: LlmUiProvider,
    embedding_model: str,
    explicit: Any = None,
) -> int:
    if explicit is not None:
        try:
            value = int(explicit)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    model = (embedding_model or "").strip()
    if model:
        return default_embedding_dimension_for_model(model)
    return _DEFAULT_DIMENSIONS[provider]


def load_llm_preferences() -> dict[str, Any]:
    """Return saved preferences merged with current effective settings."""
    sync_llm_preferences_from_volume()
    saved = _read_raw_preferences() or {}
    snapshot = _effective_settings_snapshot()
    provider = _normalize_ui_provider(saved.get("provider")) if saved.get("provider") else snapshot["provider"]
    defaults = default_models_for_provider(provider)
    embedding_model = (
        saved.get("embedding_model") or snapshot["embedding_model"] or defaults["embedding_model"]
    ).strip()
    return {
        "version": _VERSION,
        "provider": provider,
        "extraction_model": (saved.get("extraction_model") or snapshot["extraction_model"] or defaults["extraction_model"]).strip(),
        "embedding_model": embedding_model,
        "embedding_dimension": _resolve_embedding_dimension(
            provider=provider,
            embedding_model=embedding_model,
            explicit=saved.get("embedding_dimension") or snapshot.get("embedding_dimension"),
        ),
        "openai_api_key_configured": snapshot["openai_api_key_configured"],
        "defaults": defaults,
    }


def apply_llm_preferences(prefs: dict[str, Any]) -> None:
    """Apply preferences to the process-wide ``settings`` singleton."""
    provider = _normalize_ui_provider(prefs.get("provider"))
    extraction_model = (prefs.get("extraction_model") or "").strip()
    embedding_model = (prefs.get("embedding_model") or "").strip()
    openai_api_key = prefs.get("openai_api_key")
    embedding_dimension = _resolve_embedding_dimension(
        provider=provider,
        embedding_model=embedding_model,
        explicit=prefs.get("embedding_dimension"),
    )

    settings.autograph_llm_provider = _provider_to_settings_value(provider)
    if extraction_model:
        settings.autograph_llm_model_name = extraction_model
    if embedding_model:
        settings.autograph_embedding_model_name = embedding_model
    settings.autograph_embedding_dimension = embedding_dimension
    if isinstance(openai_api_key, str) and openai_api_key.strip():
        settings.openai_api_key = openai_api_key.strip()

    from app.llm import databricks_serving

    databricks_serving._resolved_endpoint_cached.cache_clear()


def save_llm_preferences(
    *,
    provider: str | None = None,
    extraction_model: str | None = None,
    embedding_model: str | None = None,
    embedding_dimension: int | None = None,
    openai_api_key: str | None = None,
) -> dict[str, Any]:
    """Persist preferences to UC volume and apply them in-process."""
    from app.workflow_platform import workflow_data_volume as vol

    current = load_llm_preferences()
    resolved_provider = _normalize_ui_provider(provider) if provider is not None else current["provider"]
    defaults = default_models_for_provider(resolved_provider)
    resolved_extraction = (extraction_model or current["extraction_model"] or defaults["extraction_model"]).strip()
    resolved_embedding = (embedding_model or current["embedding_model"] or defaults["embedding_model"]).strip()
    resolved_dimension = _resolve_embedding_dimension(
        provider=resolved_provider,
        embedding_model=resolved_embedding,
        explicit=embedding_dimension if embedding_dimension is not None else current.get("embedding_dimension"),
    )

    stored = _read_raw_preferences() or {}
    payload = {
        "version": _VERSION,
        "provider": resolved_provider,
        "extraction_model": resolved_extraction,
        "embedding_model": resolved_embedding,
        "embedding_dimension": resolved_dimension,
    }
    if isinstance(openai_api_key, str) and openai_api_key.strip():
        payload["openai_api_key"] = openai_api_key.strip()
    elif isinstance(stored.get("openai_api_key"), str) and stored["openai_api_key"].strip():
        payload["openai_api_key"] = stored["openai_api_key"].strip()

    vol.write_bytes(
        relative_path=_SETTINGS_REL,
        content=json.dumps(payload, indent=2).encode("utf-8"),
    )

    apply_payload = {
        "provider": resolved_provider,
        "extraction_model": resolved_extraction,
        "embedding_model": resolved_embedding,
        "embedding_dimension": resolved_dimension,
    }
    if payload.get("openai_api_key"):
        apply_payload["openai_api_key"] = payload["openai_api_key"]
    apply_llm_preferences(apply_payload)
    global _last_applied_signature
    _last_applied_signature = _prefs_signature(payload)

    _invalidate_probe_cache()

    result = load_llm_preferences()
    result["ok"] = True
    return result


def bootstrap_llm_preferences() -> None:
    """Load saved preferences at app startup (env vars remain the fallback)."""
    saved = _read_raw_preferences()
    if not saved:
        return
    try:
        apply_llm_preferences(saved)
        global _last_applied_signature
        _last_applied_signature = _prefs_signature(saved)
        log.info(
            "llm_preferences_loaded",
            provider=saved.get("provider"),
            extraction_model=saved.get("extraction_model"),
            embedding_model=saved.get("embedding_model"),
            embedding_dimension=saved.get("embedding_dimension"),
            openai_key=bool((saved.get("openai_api_key") or "").strip()),
        )
    except Exception as exc:
        log.warning("llm_preferences_apply_failed", error=str(exc))
