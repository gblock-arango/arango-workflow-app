"""Probe OpenAI / Anthropic connectivity for embeddings and extraction models."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage

from app.config import settings

log = logging.getLogger(__name__)

_PROBE_TEXT = "connectivity probe"
_PROBE_CACHE_TTL_SEC = 90.0
_probe_cache: dict[str, Any] = {"at": 0.0, "payload": None}


def _config_hints(
    embedding: dict[str, Any] | None = None,
    extraction: dict[str, Any] | None = None,
) -> list[str]:
    hints: list[str] = []
    emb_model = settings.embedding_model
    ext_model = settings.llm_extraction_model
    if not (settings.openai_api_key or "").strip():
        hints.append(
            "OPENAI_API_KEY is not set in Databricks App secrets (required for "
            f"embeddings via {emb_model} and OpenAI extraction models)."
        )
    if "claude" in ext_model.lower() or "anthropic" in ext_model.lower():
        if not (settings.anthropic_api_key or "").strip():
            hints.append(
                f"ANTHROPIC_API_KEY is not set (required for extraction model {ext_model})."
            )
    elif not (settings.openai_api_key or "").strip():
        hints.append(f"Extraction model {ext_model} uses OpenAI — set OPENAI_API_KEY.")
    if (settings.openai_base_url or "").strip():
        hints.append(f"OpenAI-compatible base URL: {settings.openai_base_url.strip()}")
    else:
        hints.append(
            "Models are called via OpenAI/Anthropic APIs (not Databricks Model Serving "
            "endpoints). To use a Databricks serving endpoint, set OPENAI_BASE_URL and "
            "OPENAI_API_KEY to the serving endpoint URL and token."
        )
    if (
        embedding
        and extraction
        and embedding.get("ok") is False
        and extraction.get("ok") is True
    ):
        hints.append(
            "Extraction works but embedding failed: usually outbound HTTPS to "
            "api.openai.com/v1/embeddings (workspace egress, proxy, or transient network). "
            "Retry the badge; confirm embeddings are enabled for your OpenAI project."
        )
    return hints


def _failure_summary(embedding: dict[str, Any], extraction: dict[str, Any]) -> str:
    parts: list[str] = []
    if not embedding.get("ok"):
        parts.append(f"Embedding ({settings.embedding_model}): {embedding.get('message', 'failed')}")
    if not extraction.get("ok"):
        parts.append(f"Extraction ({settings.llm_extraction_model}): {extraction.get('message', 'failed')}")
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
    payload = {
        "ok": overall_ok,
        "provider": provider,
        "embedding_model": settings.embedding_model,
        "extraction_model": settings.llm_extraction_model,
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
    """Shell commands to test OpenAI from a laptop (not from inside the Databricks App)."""
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
    if not (settings.openai_api_key or "").strip():
        return {
            "ok": False,
            "message": "OPENAI_API_KEY is not set (required for chunk embeddings)",
            "latency_ms": 0,
        }

    from app.services.embedding import _get_client

    start = time.perf_counter()
    try:
        client = _get_client()
        response = await client.embeddings.create(
            input=[_PROBE_TEXT],
            model=settings.embedding_model,
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
            "message": f"Embedding OK ({settings.embedding_model}, dim={dim})",
            "latency_ms": latency_ms,
            "dimension": dim,
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        log.warning("embedding connectivity probe failed: %s", exc, exc_info=True)
        msg = _format_probe_error(exc)
        if "connection" in msg.lower():
            msg += (
                " (HTTPS to api.openai.com/v1/embeddings from the app; "
                f"timeout={settings.llm_request_timeout_seconds}s)"
            )
        return {"ok": False, "message": msg, "latency_ms": latency_ms}


async def _probe_extraction() -> dict[str, Any]:
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
