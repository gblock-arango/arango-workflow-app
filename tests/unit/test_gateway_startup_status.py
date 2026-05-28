"""Unit tests for gateway startup-status parsing."""

from __future__ import annotations

from app.services.gateway_startup_status import ready_payload_from_startup_status

SAMPLE_OK = {
    "checked_at": "2026-05-28T18:48:38.316319+00:00",
    "probe": {
        "details": {
            "latency_ms": 198,
            "reachable": True,
            "response_preview": '{"license":"community","server":"arango","version":"3.12.4"}',
            "status_code": 200,
            "url": "https://outdoor-auto-preceding-sensitive.trycloudflare.com:443/_api/version",
        },
        "status": "ok",
    },
    "registry": {
        "cluster_name": "local-minikube-dev",
        "ip_address": "outdoor-auto-preceding-sensitive.trycloudflare.com",
        "port": "443",
        "protocol": "https",
        "status": "ok",
    },
    "registry_table": "workspace.default.arango_connection_registry",
    "warehouse_id_present": True,
}


def test_ready_when_probe_and_registry_ok():
    out = ready_payload_from_startup_status(
        SAMPLE_OK,
        gateway_base_url="https://arango-gateway-app.example.aws.databricksapps.com",
    )
    assert out["status"] == "ready"
    assert "Arango 3.12.4" in out["detail"]
    assert "local-minikube-dev" in out["detail"]
    assert "198ms" in out["detail"]
    assert out["database"] == "Arango 3.12.4"


def test_not_ready_when_probe_fails():
    payload = {
        **SAMPLE_OK,
        "probe": {**SAMPLE_OK["probe"], "status": "error"},
    }
    out = ready_payload_from_startup_status(
        payload,
        gateway_base_url="https://gateway.example.com",
    )
    assert out["status"] == "not_ready"
    assert "probe=error" in out["gateway"]
