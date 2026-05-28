import pytest

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.health import invalidate_ready_cache
from app.main import app

client = TestClient(app)


def setup_function() -> None:
    invalidate_ready_cache()


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@patch("app.api.health._ready_async", new_callable=AsyncMock)
def test_ready_when_gateway_and_arango_ok(mock_ready_async):
    mock_ready_async.return_value = {
        "status": "ready",
        "gateway": "Gateway startup-status ok",
        "database": "Arango 3.12.4",
        "detail": "Arango 3.12.4 · local-minikube-dev · 198ms",
        "gateway_url": "https://arango-gateway-app.example.aws.databricksapps.com",
    }

    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert "Arango 3.12.4" in body["detail"]


@patch("app.services.arango_connectivity.fetch_arango_startup_status")
@patch("app.db.gateway_config.effective_gateway_url")
@pytest.mark.asyncio
async def test_ready_async_uses_uc_arango_probe(mock_gateway_url, mock_fetch):
    from tests.unit.test_gateway_startup_status import SAMPLE_OK

    mock_gateway_url.return_value = "https://arango-gateway-app.example.aws.databricksapps.com"
    mock_fetch.return_value = SAMPLE_OK

    from app.api.health import _ready_async

    body = await _ready_async(force=True)
    assert body["status"] == "ready"
    assert "Arango 3.12.4" in body["detail"]
    mock_fetch.assert_called_once()


@patch("app.services.arango_connectivity.fetch_arango_startup_status")
@patch("app.db.gateway_config.effective_gateway_url")
@pytest.mark.asyncio
async def test_ready_serves_stale_when_refresh_fails(mock_gateway_url, mock_fetch):
    from tests.unit.test_gateway_startup_status import SAMPLE_OK

    from app.api.health import _ready_async, invalidate_ready_cache

    invalidate_ready_cache()
    mock_gateway_url.return_value = "https://arango-gateway-app.example.aws.databricksapps.com"
    mock_fetch.return_value = SAMPLE_OK
    warm = await _ready_async(force=True)
    assert warm["status"] == "ready"

    mock_fetch.side_effect = RuntimeError("registry empty")
    body = await _ready_async(force=True)
    assert body.get("stale") is True
    assert "Arango 3.12.4" in body.get("detail", "")


@patch("app.services.arango_connectivity.fetch_arango_startup_status")
@patch("app.db.gateway_config.effective_gateway_url")
@pytest.mark.asyncio
async def test_ready_not_ready_when_probe_fails(mock_gateway_url, mock_fetch):
    mock_gateway_url.return_value = "https://arango-gateway-app.example.aws.databricksapps.com"
    mock_fetch.return_value = {
        "checked_at": "2026-01-01T00:00:00+00:00",
        "registry": {"status": "ok", "cluster_name": "c"},
        "probe": {"status": "unreachable", "details": {"reachable": False}},
    }

    from app.api.health import _ready_async, invalidate_ready_cache

    invalidate_ready_cache()
    body = await _ready_async(force=True)
    assert body["status"] == "not_ready"
