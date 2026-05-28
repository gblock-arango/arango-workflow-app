"""Probe OpenAI / Anthropic / Databricks Model Serving connectivity."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage

from app.config import settings
from app.llm.databricks_serving import (
    effective_embedding_model_name,
    effective_extraction_model_name,
    uses_databricks_serving_for_embeddings,
    uses_databricks_serving_for_extraction,
)

log = logging.getLogger(__name__)

_PROBE_TEXT = "connectivity probe"
_PROBE_CACHE_TTL_SEC = 90.0
_probe_cache: dict[str, Any] = {"at": 0.0, "payload": None}


def _config_hints(
    embedding: dict[str, Any] | None = None,
    extraction: dict[str, Any] | None = None,
) -> list[str]:
    hints: list[str] = []
    if uses_databricks_serving_for_embeddings():
        hints.append(
            "Embeddings use Databricks Model Serving "
            f"({effective_embedding_model_name()}) via workspace OAuth."
        )
    elif not (settings.openai_api_key or "").strip():
        hints.append(
            "OPENAI_API_KEY is not set (required for chunk embeddings via "
            f"{settings.embedding_model})."
        )

    if uses_databricks_serving_for_extraction():
        hints.append(
            "Extraction uses Databricks Model Serving "
            f"({effective_extraction_model_name()}) via workspace OAuth."
        )
    else:
        ext_model = settings.llm_extraction_model
        if "claude" in ext_model.lower() or "anthropic" in ext_model.lower():
            if not (settings.anthropic_api_key or "").strip():
                hints.append(
                    f"ANTHROPIC_API_KEY is not set (required for extraction model {ext_model})."
                )
        elif not (settings.openai_api_key or "").strip():
            hints.append(f"Extraction model {ext_model} uses OpenAI — set OPENAI_API_KEY.")

    if not uses_databricks_serving_for_embeddings() and not uses_databricks_serving_for_extraction():
        if (settings.openai_base_url or "").strip():
            hints.append(f"OpenAI-compatible base URL: {settings.openai_base_url.strip()}")
        else:
            hints.append(
                "External OpenAI/Anthropic APIs. For Databricks serving, set "
                "AUTOGRAPH_LLM_MODEL_NAME / AUTOGRAPH_EMBEDDING_MODEL_NAME (or resolve queries) "
                "and AUTOGRAPH_LLM_PROVIDER=databricks_serving or auto on cluster."
            )

    if (
        embedding
        and extraction
        and embedding.get("ok") is False
        and extraction.get("ok") is True
    ):
        if uses_databricks_serving_for_embeddings():
            hints.append(
                "Extraction works but embedding failed: confirm the embedding serving "
                "endpoint is READY and the app SP can invoke it."
            )
        else:
            hints.append(
                "Extraction works but embedding failed: usually outbound HTTPS to "
                "api.openai.com/v1/embeddings (workspace egress, proxy, or transient network)."
            )
    return hints


def _failure_summary(embedding: dict[str, Any], extraction: dict[str, Any]) -> str:
    parts: list[str] = []
    if not embedding.get("ok"):
        emb_label = (
            effective_embedding_model_name()
            if uses_databricks_serving_for_embeddings()
            else settings.embedding_model
        )
        parts.append(f"Embedding ({emb_label}): {embedding.get('message', 'failed')}")
    if not extraction.get("ok"):
        ext_label = (
            effective_extraction_model_name()
            if uses_databricks_serving_for_extraction()
            else settings.llm_extraction_model
        )
        parts.append(f"Extraction ({ext_label}): {extraction.get('message', 'failed')}")
    return " · ".join(parts) if parts else "All probes passed"


async def probe_llm_connectivity(*, force: bool = False) -> dict[str, Any]:
    """Run lightweight live checks against configured LLM providers."""
    now = time.monotonic()
    if not force:
        cached = _probe_cache.get("payload")
        if (
            cached is not None
            and now - float(_probe_cache.get("at") or 0.0) < _PROBE_CACHE_TTL_SEC
        ):
            return dict(cached)

    embedding, extraction = await asyncio.gather(
        _probe_embedding(),
        _probe_extraction(),
    )
    overall_ok = bool(embedding.get("ok")) and bool(extraction.get("ok"))

    provider = _primary_provider_label()
    hints = _config_hints(embedding, extraction)
    summary = (
        "Embedding and extraction endpoints reachable"
        if overall_ok
        else _failure_summary(embedding, extraction)
    )
    emb_model = (
        effective_embedding_model_name()
        if uses_databricks_serving_for_embeddings()
        else settings.embedding_model
    )
    ext_model = (
        effective_extraction_model_name()
        if uses_databricks_serving_for_extraction()
        else settings.llm_extraction_model
    )
    configured_emb = (settings.autograph_embedding_model_name or "").strip() or None
    payload = {
        "ok": overall_ok,
        "provider": provider,
        "embedding_model": emb_model,
        "configured_embedding_model_name": configured_emb,
        "embedding_endpoint_resolved": (
            configured_emb != emb_model if configured_emb and uses_databricks_serving_for_embeddings() else None
        ),
        "extraction_model": ext_model,
        "autograph_llm_provider": settings.autograph_llm_provider,
        "use_databricks_embeddings": uses_databricks_serving_for_embeddings(),
        "use_databricks_extraction": uses_databricks_serving_for_extraction(),
        "embedding_dimension": settings.effective_embedding_dimension,
        "openai_base_url": (settings.openai_base_url or "").strip() or None,
        "openai_api_key_configured": bool((settings.openai_api_key or "").strip()),
        "anthropic_api_key_configured": bool((settings.anthropic_api_key or "").strip()),
        "embedding": embedding,
        "extraction": extraction,
        "summary": summary,
        "hints": hints,
        "curl_examples": _curl_examples(),
    }
    _probe_cache["at"] = now
    _probe_cache["payload"] = payload
    return payload


def _curl_examples() -> list[str]:
    """Shell commands to test providers from a laptop (not from inside the Databricks App)."""
    if uses_databricks_serving_for_embeddings() or uses_databricks_serving_for_extraction():
        return [
            "Databricks serving: use the workspace UI or "
            "'databricks serving-endpoints query <ENDPOINT_NAME>' with your profile."
        ]
    base = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
    emb = settings.embedding_model
    ext = settings.llm_extraction_model
    return [
        (
            f'curl -sS "{base}/embeddings" -H "Authorization: Bearer $OPENAI_API_KEY" '
            f'-H "Content-Type: application/json" '
            f'-d \'{{"model":"{emb}","input":"connectivity probe"}}\''
        ),
        (
            f'curl -sS "{base}/chat/completions" -H "Authorization: Bearer $OPENAI_API_KEY" '
            f'-H "Content-Type: application/json" '
            f'-d \'{{"model":"{ext}","messages":[{{"role":"user","content":"Reply OK"}}]}}\''
        ),
    ]


def _primary_provider_label() -> str:
    if uses_databricks_serving_for_extraction() or uses_databricks_serving_for_embeddings():
        return "databricks_serving"
    model = (settings.llm_extraction_model or "").lower()
    if "claude" in model or "anthropic" in model:
        return "anthropic"
    if settings.openai_api_key or settings.openai_base_url:
        return "openai"
    return "unconfigured"


def _format_probe_error(exc: BaseException) -> str:
    name = type(exc).__name__
    text = str(exc).strip() or name
    if text == name:
        return name
    return f"{name}: {text}"


async def _probe_embedding() -> dict[str, Any]:
    if not uses_databricks_serving_for_embeddings() and not (settings.openai_api_key or "").strip():
        return {
            "ok": False,
            "message": "OPENAI_API_KEY is not set (required for chunk embeddings)",
            "latency_ms": 0,
        }

    from app.services.embedding import _get_client

    model = effective_embedding_model_name()
    start = time.perf_counter()
    try:
        client = _get_client()
        response = await client.embeddings.create(
            input=[_PROBE_TEXT],
            model=model,
        )
        dim = len(response.data[0].embedding) if response.data else 0
        latency_ms = int((time.perf_counter() - start) * 1000)
        if dim < 1:
            return {
                "ok": False,
                "message": "Embedding API returned empty vectors",
                "latency_ms": latency_ms,
            }
        return {
            "ok": True,
            "message": f"Embedding OK ({model}, dim={dim})",
            "latency_ms": latency_ms,
            "dimension": dim,
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        log.warning("embedding connectivity probe failed: %s", exc, exc_info=True)
        return {"ok": False, "message": _format_probe_error(exc), "latency_ms": latency_ms}


async def _probe_extraction() -> dict[str, Any]:
    if uses_databricks_serving_for_extraction():
        model = effective_extraction_model_name()
    else:
        model = settings.llm_extraction_model
        model_lower = model.lower()

        if ("claude" in model_lower or "anthropic" in model_lower) and not (
            settings.anthropic_api_key or ""
        ).strip():
            return {
                "ok": False,
                "message": "ANTHROPIC_API_KEY is not set for extraction model",
                "latency_ms": 0,
            }

        if "claude" not in model_lower and "anthropic" not in model_lower:
            if not (settings.openai_api_key or "").strip():
                return {
                    "ok": False,
                    "message": "OPENAI_API_KEY is not set for extraction model",
                    "latency_ms": 0,
                }

    from app.extraction.agents.extractor import _get_llm

    start = time.perf_counter()
    try:
        llm = _get_llm(model)
        response = await llm.ainvoke(
            [HumanMessage(content='Reply with exactly the word OK.')],
        )
        text = (getattr(response, "content", None) or str(response)).strip()[:200]
        latency_ms = int((time.perf_counter() - start) * 1000)
        if not text:
            return {
                "ok": False,
                "message": "Extraction model returned empty content",
                "latency_ms": latency_ms,
            }
        return {
            "ok": True,
            "message": f"Extraction OK ({model}): {text[:40]}",
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        log.warning("extraction connectivity probe failed: %s", exc)
        return {
            "ok": False,
            "message": _format_probe_error(exc),
            "latency_ms": latency_ms,
        }
