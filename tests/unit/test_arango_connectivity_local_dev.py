"""Tests for local_dev gateway startup-status fetch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.unit.test_gateway_startup_status import SAMPLE_OK


def test_fetch_arango_startup_status_uses_gateway_in_local_dev(monkeypatch):
    monkeypatch.setenv("TEST_DEPLOYMENT_MODE", "local_dev")
    from app.services import arango_connectivity as conn

    mock_response = MagicMock()
    mock_response.content = b"{}"
    mock_response.json.return_value = dict(SAMPLE_OK)
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client
        with patch(
            "app.services.arango_connection_profiles.get_connection_ui_context",
            return_value={"active_profile": "aws"},
        ):
            out = conn.fetch_arango_startup_status()

    assert out["source"] == "gateway_startup_status"
    assert out["gateway_url"] == "http://127.0.0.1:8001"
    assert out["registry"]["status"] == "ok"
    mock_client.get.assert_called_once()
