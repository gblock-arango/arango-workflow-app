"""Unit tests for UC embedding pipeline stages."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.embedding_pipeline import run_chunk_stage, run_parse_stage


@pytest.mark.asyncio
@patch("app.services.embedding_pipeline.status_svc.update_embedding_status")
@patch("app.services.embedding_pipeline.artifacts.write_parsed")
@patch("app.services.embedding_pipeline.artifacts.delete_pipeline_artifacts")
async def test_run_parse_stage_markdown(_mock_del, mock_write, mock_update):
    with patch(
        "app.services.embedding_pipeline._parse",
        new_callable=AsyncMock,
        return_value=MagicMock(sections=[MagicMock()]),
    ):
        await run_parse_stage("doc1", b"# Hi", "text/markdown")
    assert mock_update.call_count >= 2
    mock_write.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.embedding_pipeline.status_svc.update_embedding_status")
@patch("app.services.embedding_pipeline.artifacts.write_chunks")
@patch("app.services.embedding_pipeline.artifacts.read_parsed")
@patch("app.services.embedding_pipeline.chunk_document")
async def test_run_chunk_stage(mock_chunk, mock_read, mock_write, mock_update):
    mock_read.return_value = MagicMock()
    mock_chunk.return_value = [
        MagicMock(
            text="a",
            chunk_index=0,
            source_page=1,
            section_heading="",
            token_count=1,
        )
    ]
    await run_chunk_stage("doc1")
    mock_write.assert_called_once()
    assert mock_update.call_count >= 2
