from unittest.mock import patch

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


@patch("app.services.gateway_startup_status.fetch_gateway_startup_status")
@patch("app.db.gateway_config.effective_gateway_url")
def test_ready_sync_uses_startup_status(mock_gateway_url, mock_fetch):
    from tests.unit.test_gateway_startup_status import SAMPLE_OK

    mock_gateway_url.return_value = "https://arango-gateway-app.example.aws.databricksapps.com"
    mock_fetch.return_value = SAMPLE_OK

    from app.api.health import _ready_sync

    body = _ready_sync(force=True)
    assert body["status"] == "ready"
    assert "Arango 3.12.4" in body["detail"]
    mock_fetch.assert_called_once_with(
        gateway_base_url="https://arango-gateway-app.example.aws.databricksapps.com",
        refresh=True,
    )


@patch("app.services.gateway_startup_status.fetch_gateway_startup_status")
@patch("app.db.gateway_config.effective_gateway_url")
def test_ready_not_ready_when_startup_status_fails(mock_gateway_url, mock_fetch):
    mock_gateway_url.return_value = "https://arango-gateway-app.example.aws.databricksapps.com"
    mock_fetch.side_effect = RuntimeError("Gateway startup-status HTTP 503")

    from app.api.health import _ready_sync

    body = _ready_sync(force=True)
    assert body["status"] == "not_ready"
    assert "503" in body["detail"]
