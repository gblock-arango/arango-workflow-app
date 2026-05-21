from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@patch("app.api.health.get_db")
@patch("app.api.health.gateway_connectivity_status")
def test_ready_when_gateway_and_arango_ok(mock_gw_status, mock_get_db):
    mock_gw_status.return_value = {
        "gateway_url": "https://arango-gateway-app.example.aws.databricksapps.com",
        "gateway_ok": True,
        "gateway_message": "Gateway reachable",
    }
    db = MagicMock()
    db.version.return_value = {"version": "3.12.4"}
    mock_get_db.return_value = db

    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert "Arango 3.12.4" in body["database"]
    assert body["gateway"] == "Gateway reachable"


@patch("app.api.health.gateway_connectivity_status")
def test_ready_not_ready_when_gateway_unreachable(mock_gw_status):
    mock_gw_status.return_value = {
        "gateway_url": "https://arango-gateway-app.example.aws.databricksapps.com",
        "gateway_ok": False,
        "gateway_message": "Gateway health HTTP 401",
    }

    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_ready"
    assert "401" in body["database"]
