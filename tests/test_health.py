from unittest.mock import MagicMock, patch

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


@patch("app.api.health._ready_sync")
def test_ready_when_gateway_and_arango_ok(mock_ready_sync):
    mock_ready_sync.return_value = {
        "status": "ready",
        "gateway": "Gateway reachable",
        "database": "Arango 3.12.4",
        "gateway_url": "https://arango-gateway-app.example.aws.databricksapps.com",
    }

    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert "Arango 3.12.4" in body["database"]


@patch("app.db.client._connect_gateway")
def test_ready_sync_impl_when_gateway_and_arango_ok(mock_connect):
    client = MagicMock()
    client.server_version = "3.12.4"
    mock_connect.return_value = client

    from app.api.health import _ready_sync

    body = _ready_sync()
    assert body["status"] == "ready"
    assert "Arango 3.12.4" in body["database"]
    assert body["gateway"] == "Gateway reachable"
    mock_connect.assert_called_once()


@patch("app.api.health.gateway_connectivity_status")
@patch("app.db.client._connect_gateway")
def test_ready_not_ready_when_gateway_unreachable(mock_connect, mock_gw_status):
    mock_connect.side_effect = RuntimeError("connect failed")
    mock_gw_status.return_value = {
        "gateway_url": "https://arango-gateway-app.example.aws.databricksapps.com",
        "gateway_ok": False,
        "gateway_message": "Gateway health HTTP 401",
    }

    from app.api.health import _ready_sync

    body = _ready_sync()
    assert body["status"] == "not_ready"
    assert "401" in body["database"]
