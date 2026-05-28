"""Unit tests for Databricks Model Serving LLM wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import LlmProvider, settings
from app.llm import databricks_serving


def test_use_databricks_for_extraction_explicit_provider():
    with (
        patch.object(settings, "autograph_llm_provider", "databricks_serving"),
        patch.object(settings, "test_deployment_mode", "self_managed_platform"),
    ):
        assert settings.use_databricks_for_extraction() is True


def test_use_databricks_for_extraction_auto_requires_config():
    with (
        patch.object(settings, "autograph_llm_provider", "auto"),
        patch.object(settings, "test_deployment_mode", "self_managed_platform"),
        patch.object(settings, "autograph_llm_model_name", ""),
        patch.object(settings, "autograph_llm_resolve_query", ""),
    ):
        assert settings.use_databricks_for_extraction() is False

    with (
        patch.object(settings, "autograph_llm_provider", "auto"),
        patch.object(settings, "test_deployment_mode", "self_managed_platform"),
        patch.object(settings, "autograph_llm_model_name", "databricks-meta-llama-3-3-70b-instruct"),
    ):
        assert settings.use_databricks_for_extraction() is True


def test_effective_embedding_dimension_databricks():
    with (
        patch.object(settings, "autograph_llm_provider", "databricks_serving"),
        patch.object(settings, "autograph_embedding_dimension", 0),
        patch.object(settings, "autograph_embedding_model_name", "databricks-bge-large-en"),
    ):
        assert settings.effective_embedding_dimension == 1024


def test_resolved_chat_model_name_explicit():
    databricks_serving._resolved_endpoint_cached.cache_clear()
    with patch.object(settings, "autograph_llm_model_name", "my-chat-endpoint"):
        assert databricks_serving.resolved_chat_model_name() == "my-chat-endpoint"


def test_get_llm_uses_serving_when_configured():
    from app.extraction.agents.extractor import _get_llm

    mock_client = MagicMock()
    mock_client.api_key = "token"
    mock_client.base_url = "https://example.cloud.databricks.com/serving-endpoints"

    with (
        patch.object(settings, "autograph_llm_provider", "databricks_serving"),
        patch.object(settings, "autograph_llm_model_name", "llama-endpoint"),
        patch(
            "app.llm.databricks_serving.workspace_openai_client",
            return_value=mock_client,
        ),
        patch("app.llm.chat_databricks_serving.DatabricksServingChatOpenAI") as mock_chat,
    ):
        _get_llm("gpt-4o-mini")
    mock_chat.assert_called_once()
    kwargs = mock_chat.call_args.kwargs
    assert kwargs["model"] == "llama-endpoint"
    assert kwargs["base_url"] == str(mock_client.base_url)


@pytest.mark.asyncio
async def test_probe_embedding_databricks_without_openai_key():
    from app.services import llm_connectivity

    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.1] * 1024
    mock_response = MagicMock()
    mock_response.data = [mock_embedding]
    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)

    with (
        patch.object(settings, "autograph_llm_provider", "databricks_serving"),
        patch.object(settings, "autograph_embedding_model_name", "gte_large_en_v1_5"),
        patch.object(settings, "openai_api_key", ""),
        patch("app.services.embedding._get_client", return_value=mock_client),
        patch(
            "app.llm.databricks_serving.effective_embedding_model_name",
            return_value="gte_large_en_v1_5",
        ),
    ):
        result = await llm_connectivity._probe_embedding()
    assert result["ok"] is True
    assert result["dimension"] == 1024
