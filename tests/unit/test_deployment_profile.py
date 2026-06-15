"""Tests for deployment_profile (local_dev switch)."""

from __future__ import annotations

import pytest

from app.workflow_platform import deployment_profile as dp
from app.workflow_platform.services import agent_url_registry, gateway_url_registry


def test_local_dev_peer_urls(monkeypatch):
    monkeypatch.setenv("TEST_DEPLOYMENT_MODE", "local_dev")
    cfg = {}
    assert gateway_url_registry.effective_gateway_base_url(cfg) == "http://127.0.0.1:8001"
    assert agent_url_registry.effective_arango_agent_base_url(cfg) == "http://127.0.0.1:8002"


def test_should_not_attach_bearer_localhost(monkeypatch):
    monkeypatch.setenv("TEST_DEPLOYMENT_MODE", "local_dev")
    assert dp.should_attach_outbound_bearer("http://127.0.0.1:8001") is False
    assert dp.should_attach_outbound_bearer("https://foo.databricksapps.com") is True


def test_static_arango_registry_row(monkeypatch):
    monkeypatch.setenv("TEST_DEPLOYMENT_MODE", "local_dev")
    row = dp.static_arango_registry_row()
    assert row["ip_address"] == "127.0.0.1"
    assert row["port"] == 18529


def test_should_upsert_connection_registry_on_connect(monkeypatch):
    monkeypatch.setenv("TEST_DEPLOYMENT_MODE", "local_dev")
    assert dp.should_upsert_connection_registry_on_connect() is True
    monkeypatch.setenv("TEST_DEPLOYMENT_MODE", "self_managed_platform")
    assert dp.should_upsert_connection_registry_on_connect() is True
