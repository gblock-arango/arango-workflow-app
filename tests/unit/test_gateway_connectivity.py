"""Unit tests for gateway /health probe retries."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.db import gateway_connectivity as gc


class TestProbeGatewayHealthRetries:
    def test_succeeds_on_second_attempt_after_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARANGO_GATEWAY_HEALTH_PROBE_RETRIES", "2")
        monkeypatch.setenv("ARANGO_GATEWAY_HEALTH_RETRY_DELAY_SECONDS", "0")
        calls = {"n": 0}

        def fake_once(_base: str) -> tuple[bool, str]:
            calls["n"] += 1
            if calls["n"] == 1:
                return False, "The read operation timed out"
            return True, "Gateway reachable"

        with patch.object(gc, "_probe_gateway_health_once", side_effect=fake_once):
            ok, msg = gc.probe_gateway_health("https://gateway.example")
        assert ok is True
        assert "attempt 2/2" in msg
        assert calls["n"] == 2

    def test_does_not_retry_http_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARANGO_GATEWAY_HEALTH_PROBE_RETRIES", "3")
        monkeypatch.setenv("ARANGO_GATEWAY_HEALTH_RETRY_DELAY_SECONDS", "0")
        with patch.object(
            gc,
            "_probe_gateway_health_once",
            return_value=(False, "Gateway health HTTP 401"),
        ) as mock_once:
            ok, msg = gc.probe_gateway_health("https://gateway.example")
        assert ok is False
        assert "401" in msg
        assert mock_once.call_count == 1

    def test_default_health_timeout_is_at_least_30_seconds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARANGO_GATEWAY_HEALTH_TIMEOUT_SECONDS", raising=False)
        assert gc._health_probe_timeout_seconds() >= 30.0
