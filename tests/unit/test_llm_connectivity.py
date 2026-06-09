"""Unit tests for LLM connectivity probes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import llm_connectivity


@pytest.mark.asyncio
async def test_probe_embedding_missing_key():
    with patch.object(llm_connectivity.settings, "openai_api_key", ""):
        result = await llm_connectivity._probe_embedding()
    assert result["ok"] is False
    assert "OPENAI_API_KEY" in result["message"]


@pytest.mark.asyncio
async def test_probe_embedding_success():
    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.1, 0.2, 0.3]
    mock_response = MagicMock()
    mock_response.data = [mock_embedding]
    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)
    with (
        patch.object(llm_connectivity.settings, "openai_api_key", "sk-test"),
        patch.object(llm_connectivity.settings, "embedding_model", "text-embedding-3-small"),
        patch("app.services.embedding._get_client", return_value=mock_client),
    ):
        result = await llm_connectivity._probe_embedding()
    assert result["ok"] is True
    assert result["dimension"] == 3


@pytest.mark.asyncio
async def test_probe_llm_connectivity_overall():
    with (
        patch(
            "app.services.llm_connectivity._probe_embedding",
            new_callable=AsyncMock,
            return_value={"ok": True, "message": "emb ok", "latency_ms": 10},
        ),
        patch(
            "app.services.llm_connectivity._probe_extraction",
            new_callable=AsyncMock,
            return_value={"ok": True, "message": "ext ok", "latency_ms": 20},
        ),
        patch.object(llm_connectivity.settings, "embedding_model", "text-embedding-3-small"),
        patch.object(llm_connectivity.settings, "llm_extraction_model", "gpt-4o-mini"),
    ):
        payload = await llm_connectivity.probe_llm_connectivity()
    assert payload["ok"] is True
    assert payload["embedding"]["ok"] is True
    assert payload["extraction"]["ok"] is True


@pytest.mark.asyncio
async def test_probe_extraction_uses_llm():
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="OK"))
    with (
        patch.object(llm_connectivity.settings, "llm_extraction_model", "gpt-4o-mini"),
        patch.object(llm_connectivity.settings, "openai_api_key", "sk-test"),
        patch("app.extraction.agents.extractor._get_llm", return_value=mock_llm),
    ):
        result = await llm_connectivity._probe_extraction()
    assert result["ok"] is True
    mock_llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_llm_connectivity_timeout_returns_stale_cache():
    stale = {
        "ok": True,
        "provider": "openai",
        "embedding": {"ok": True, "message": "emb ok"},
        "extraction": {"ok": True, "message": "ext ok"},
    }
    llm_connectivity._probe_cache["at"] = 0.0
    llm_connectivity._probe_cache["payload"] = stale

    async def _slow(*_args, **_kwargs):
        await asyncio.sleep(60)

    with (
        patch(
            "app.services.llm_connectivity._probe_embedding",
            side_effect=_slow,
        ),
        patch(
            "app.services.llm_connectivity._probe_extraction",
            side_effect=_slow,
        ),
        patch.object(llm_connectivity, "_PROBE_LIVE_TIMEOUT_SEC", 0.01),
    ):
        payload = await llm_connectivity.probe_llm_connectivity(force=True)

    assert payload.get("stale") is True
    assert payload["ok"] is True


@pytest.mark.asyncio
async def test_llm_status_route_handler():
    from app.api.system import llm_status

    with patch(
        "app.api.system.probe_llm_connectivity",
        new_callable=AsyncMock,
        return_value={
            "ok": True,
            "provider": "openai",
            "embedding_model": "text-embedding-3-small",
            "extraction_model": "gpt-4o-mini",
            "embedding": {"ok": True, "message": "ok"},
            "extraction": {"ok": True, "message": "ok"},
        },
    ):
        payload = await llm_status()
    assert payload["ok"] is True
