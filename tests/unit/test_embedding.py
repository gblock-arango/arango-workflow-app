"""Unit tests for app.services.embedding - batching, retries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.embedding import embed_texts


def _make_embedding_response(texts: list[str]) -> MagicMock:
    """Build a mock OpenAI embeddings response."""
    resp = MagicMock()
    data = []
    for i, _text in enumerate(texts):
        item = MagicMock()
        item.index = i
        item.embedding = [0.1 * (i + 1)] * 8
        data.append(item)
    resp.data = data
    return resp


@patch("app.services.embedding._get_client")
class TestEmbedTexts:
    @pytest.mark.asyncio
    async def test_single_text(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client
        client.embeddings.create = AsyncMock(
            return_value=_make_embedding_response(["hello"]),
        )

        result = await embed_texts(["hello"], model="text-embedding-3-small")

        assert len(result) == 1
        assert isinstance(result[0], list)
        assert len(result[0]) == 8

    @pytest.mark.asyncio
    async def test_multiple_texts(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client

        texts = [f"text_{i}" for i in range(5)]
        client.embeddings.create = AsyncMock(
            return_value=_make_embedding_response(texts),
        )

        result = await embed_texts(texts, model="test-model")
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_batching(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client

        texts = [f"text_{i}" for i in range(250)]

        async def side_effect(input: list[str], model: str):
            return _make_embedding_response(input)

        client.embeddings.create = AsyncMock(side_effect=side_effect)

        result = await embed_texts(texts, model="test-model")

        assert len(result) == 250
        assert client.embeddings.create.call_count >= 2

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client

        rate_error = Exception("Rate limit exceeded (429)")
        success_response = _make_embedding_response(["test"])

        client.embeddings.create = AsyncMock(
            side_effect=[rate_error, success_response],
        )

        with patch("app.services.embedding.asyncio.sleep", new_callable=AsyncMock):
            result = await embed_texts(["test"], model="test-model")

        assert len(result) == 1
        assert client.embeddings.create.call_count == 2

    @pytest.mark.asyncio
    async def test_non_rate_limit_error_propagates(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client

        client.embeddings.create = AsyncMock(
            side_effect=ValueError("bad input"),
        )

        with pytest.raises(ValueError, match="bad input"):
            await embed_texts(["test"], model="test-model")

    @pytest.mark.asyncio
    async def test_empty_list(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client

        result = await embed_texts([], model="test-model")
        assert result == []
