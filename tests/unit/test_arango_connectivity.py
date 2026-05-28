"""Unit tests for UC-direct Arango connectivity (home /ready widget)."""

from __future__ import annotations

from unittest.mock import patch

from app.services.arango_connectivity import fetch_arango_startup_status
from app.services.gateway_startup_status import ready_payload_from_startup_status


@patch("app.services.arango_connectivity.ping_arango_endpoint")
@patch("app.services.arango_connectivity._get_active_registry_row")
@patch("app.services.arango_connectivity.workflow_config_dict")
def test_fetch_arango_startup_status_ok(mock_cfg, mock_row, mock_ping):
    mock_cfg.return_value = {
        "ARANGO_REGISTRY_TABLE": "workspace.default.arango_connection_registry",
        "DATABRICKS_SQL_WAREHOUSE_ID": "wh1",
    }
    mock_row.return_value = {
        "cluster_name": "local-minikube-dev",
        "ip_address": "tunnel.example.com",
        "port": 443,
        "protocol": "https",
    }
    mock_ping.return_value = {
        "reachable": True,
        "status_code": 200,
        "latency_ms": 190,
        "response_preview": '{"version":"3.12.4","server":"arango"}',
    }

    status = fetch_arango_startup_status()
    ready = ready_payload_from_startup_status(status, gateway_base_url="https://gw.example.com")

    assert status["registry"]["status"] == "ok"
    assert status["probe"]["status"] == "ok"
    assert ready["status"] == "ready"
    assert "3.12.4" in ready["detail"]
    assert "190ms" in ready["detail"]
