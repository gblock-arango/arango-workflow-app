"""Volume ingest uses Files API when local mount is empty."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import workflow_data as wd


def test_ingest_file_from_volume_uses_read_bytes():
    with patch("app.services.workflow_data.vol.read_bytes", return_value=b"# doc") as rb:
        content, name, mime = wd.ingest_file_from_volume(
            relative_path="builtin/financial/sample.md"
        )
    assert content == b"# doc"
    assert name == "sample.md"
    assert mime == "text/markdown"
    rb.assert_called_once_with("builtin/financial/sample.md")
